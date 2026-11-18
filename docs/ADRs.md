# Architecture Decision Records (ADRs) — UberHub Matchmaking Service

Registro das decisões arquiteturais estruturais tomadas durante a concepção e evolução do serviço de matchmaking (`v0.1.0` a `v0.4.0`), detalhando o contexto técnico, as opções avaliadas, a decisão adotada e suas consequências operacionais.

---

## ADR-001: Processamento Assíncrono com `202 Accepted` e `Idempotency-Key`

* **Status:** Aceito
* **Data:** 2026-11
* **Contexto:** O fluxo de recomendação envolve geração de embeddings, busca híbrida no banco de dados, chamada de rede em lote ao Sistema de Origem para revalidação de vagas e gravação de trilha de auditoria. Executar todas essas etapas de forma síncrona na requisição HTTP acopla a latência do cliente ao tempo de resposta da rede externa e expõe o sistema a falhas em cascata ou duplicação de pedidos em caso de *retry* do cliente.
* **Decisão:** Expor `POST /match-requests` de forma assíncrona, persistindo o pedido com status inicial `processing`, retornando imediatamente `HTTP 202 Accepted` com um `match_request_id` (UUID) e delegando a execução para um worker em background. Exigir/suportar o cabeçalho `Idempotency-Key` para garantir que reenvios do cliente retornem o mesmo identificador sem reprocessar o pipeline.
* **Consequências:**
  * *Positivas:* Baixa latência de resposta na ingestão, isolamento contra lentidão do Sistema de Origem e proteção nativa contra cliques duplos ou retentativas de rede.
  * *Negativas / Trade-offs:* O cliente precisa realizar *polling* em `GET /match-requests/{id}` (ou aguardar webhook futuro) para obter o ranking final.

---

## ADR-002: Busca Híbrida (Vetorial + Full-Text Search) com Reciprocal Rank Fusion (RRF)

* **Status:** Aceito
* **Data:** 2026-11
* **Contexto:** Consultas baseadas exclusivamente em filtros SQL exatos falham quando o mentorado descreve sua necessidade sem usar as mesmas tags cadastradas pelo mentor (*gap lexical*, evidenciado no caso de teste `tc_02`). Por outro lado, buscas puramente vetoriais podem diluir correspondências exatas de termos técnicos específicos e exigem calibração complexa de limiares de distância.
* **Decisão:** Utilizar o próprio PostgreSQL como motor unificado de recuperação híbrida, combinando similaridade de cosseno via extensão `pgvector` (`<=>`) e busca lexical ponderada em português via `tsvector` + índice `GIN` (`ts_rank_cd`). Fundir os dois rankings utilizando **Reciprocal Rank Fusion (RRF)**:
  $$\text{RRF}(d) = \frac{1}{k + \text{rank}_{\text{vetorial}}(d)} + \frac{1}{k + \text{rank}_{\text{lexical}}(d)} \quad (k = 60)$$
  Aplicar o pré-filtro rígido (idioma, formato, experiência mínima) antes da fusão e recuperar uma margem de segurança de $K = 4 \times N$ candidatos.
* **Consequências:**
  * *Positivas:* Elimina a necessidade de manter duas infraestruturas separadas (ex: banco relacional + Elasticsearch), dispensa normalização entre escalas de cosseno e BM25/TSRank, e elevou o `MRR` para `1.00` no benchmark.
  * *Negativas / Trade-offs:* Aumenta o custo de escrita na tabela `mentors_index`, pois cada atualização precisa recalcular tanto o vetor de 384 dimensões quanto o `search_tsv`.

---

## ADR-003: Consistência Eventual em Duas Camadas (Indexação Versionada + Revalidação Batch)

* **Status:** Aceito
* **Data:** 2026-11
* **Contexto:** O serviço de matchmaking mantém uma projeção local (`mentors_index`) alimentada por eventos assíncronos vindos do Sistema de Origem. Em arquiteturas orientadas a eventos, mensagens podem chegar duplicadas, fora de ordem ou com atraso suficiente para que um mentor fique sem vagas antes que o índice local seja atualizado.
* **Decisão:** Mitigar a inconsistência eventual em duas frentes complementares:
  1. **Na Escrita (Ingestão de Eventos):** Registrar `event_id` na tabela `processed_events` para idempotência estrita e aplicar *upsert* monotônico (`ON CONFLICT (mentor_id) DO UPDATE ... WHERE EXCLUDED.version > mentors_index.version`), descartando eventos atrasados (`stale_version_ignored`).
  2. **Na Leitura (Execução do Match):** Consultar o Sistema de Origem em lote (`revalidate_batch`) para os $4 \times N$ candidatos recuperados antes de definir o `Top-N` final, descartando mentores inativos ou com `available_slots <= 0` na fonte da verdade.
* **Consequências:**
  * *Positivas:* Impede corrupção do índice por eventos reordenados na fila e garante que o mentorado não receba recomendações de mentores indisponíveis no momento do match.
  * *Negativas / Trade-offs:* Adiciona uma chamada de rede em lote no caminho crítico do worker de matching.

---

## ADR-004: Resiliência na Revalidação com Circuit Breaker e Degradação Controlada

* **Status:** Aceito
* **Data:** 2026-11
* **Contexto:** Tornar a revalidação síncrona no Sistema de Origem um requisito bloqueante faria com que qualquer indisponibilidade ou pico de latência na origem derrubasse integralmente o serviço de matchmaking.
* **Decisão:** Encapsular a comunicação no `ResilientOriginClient` com timeout estrito, retentativas com *backoff* e padrão **Circuit Breaker** (abertura automática após 3 falhas consecutivas por 15 segundos). Quando o circuito estiver aberto ou as tentativas falharem, acionar fallback automático para a capacidade local estimada (`max_load - current_load` em `mentors_index`), concluindo o pedido com `"status": "completed"` e sinalizando explicitamente `"revalidation_status": "unrevalidated"`.
* **Consequências:**
  * *Positivas:* Alta disponibilidade do serviço mesmo sob falha total do Sistema de Origem, mantendo transparência para o consumidor da API sobre o nível de garantia da disponibilidade retornada.
  * *Negativas / Trade-offs:* Durante janelas de degradação (`unrevalidated`), existe risco residual de recomendar um mentor cuja vaga foi ocupada segundos antes da falha da origem.

---

## ADR-005: Scoring Multi-Critério Configurável, Atenuação Operacional e Trilha Auditável

* **Status:** Aceito
* **Data:** 2026-11
* **Contexto:** Algoritmos de recomendação opacos dificultam a depuração de resultados ruins e geram desconfiança operacional. Além disso, durante os experimentos da `v0.2.0`, observou-se que critérios logísticos (agenda livre e horários) podiam somar pontos suficientes para promover candidatos sem aderência técnica ao `Top-3`.
* **Decisão:** Decompor o score final em 5 dimensões normalizadas `[0.0, 1.0]` (`skills_overlap`, `semantic_similarity`, `seniority_fit`, `mentor_load`, `goal_alignment`) governadas por pesos configuráveis (`ScoreWeights`). Introduzir um fator de atenuação (`0.35x`) sobre os critérios operacionais sempre que a aderência técnica média for inferior a `0.25`. Persistir cada recomendação, seu `score_breakdown` e a `algorithm_version` na tabela `match_decisions`, complementada pelo endpoint `POST /match-requests/{id}/feedback`.
* **Consequências:**
  * *Positivas:* Toda recomendação é reproduzível, explicável via API (`GET /decisions/{mentor_id}` e campo `explanation`), protegida contra distorções logísticas e preparada para calibração futura orientada a dados reais de aceite/rejeição.
  * *Negativas / Trade-offs:* Crescimento contínuo das tabelas `match_decisions` e `match_feedback`, exigindo política de retenção ou particionamento em escala de produção.