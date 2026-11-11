# One-Pager: Sistema de Matchmaking e Alocação de Mentores

## 1. Contexto e Objetivo

O sistema realiza a recomendação e alocação de mentores baseando-se em um pipeline de busca, ranqueamento e revalidação. O fluxo é acionado pelo **Admin**, que cria a necessidade, recebe o resultado ranqueado e decide a alocação final da vaga.

## 2. Responsabilidades do Serviço

- Processamento de texto via LLM (extração de tags).

- Cálculo de score de compatibilidade mentor-mentorando.

- Algoritmo de pontuação multi-critério.

## 3. Arquitetura e Pipeline de Decisão

O pipeline completo ocorre de forma isolada dentro do serviço de matching, processando os candidatos nas seguintes etapas:

1. **Pré-filtro:** Filtra o índice próprio (que contém skills, bio e embeddings) por idioma (ex: pt-BR) e status de mentor ativo.

2. **Busca Híbrida:** Utiliza busca vetorial combinada com palavra-chave. A busca é feita com uma margem de segurança maior (3 a 5 vezes o tamanho do pedido) para separar da revalidação.

3. **Revalidação:** Executa uma consulta em lote à fonte da verdade no Sistema de Origem para garantir que os dados dos candidatos estão atualizados.

4. **Ranqueamento:** Descarta candidatos inválidos (ex: sem vagas) e corta a lista para o tamanho `N` necessário.

5. **Explicação via LLM:** Passo opcional para justificar o match (o sistema funciona normalmente sem esta etapa).

## 4. Endpoints Internos

|            |                                     |                            |
| ---------- | ----------------------------------- | -------------------------- |
| **Método** | **Endpoint**                        | **Descrição**              |
| POST       | `/matchmaking`                      | Encontrar melhor mentor    |
| POST       | `/matchmaking/batch`                | Lista ordenada de mentores |
| POST       | `/matchmaking/score`                | Calcular score específico  |
| GET        | `/matchmaking/decisions/{mentorId}` | Histórico de decisões      |
