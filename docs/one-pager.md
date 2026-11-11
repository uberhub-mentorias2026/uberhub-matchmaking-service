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
    

## 4. Pontos Chave e Resolução de Concorrência

Para evitar alocações indevidas devido ao atraso na atualização do índice de busca (eventual consistency), o sistema implementa mecanismos rigorosos:

- **Fonte da Verdade Isolada:** O Sistema de Origem aparece como uma caixa própria, atuando como a fonte da verdade. Ele recebe as consultas de ida e volta da etapa de revalidação e emite eventos de atualização para o índice do serviço de matching.
    
- **Prevenção de Dados Defasados:** Como demonstrado em simulações, se o Admin aloca uma vaga e cria uma nova necessidade imediatamente, o evento de atualização do índice pode ainda não ter sido processado. A etapa de **Revalidação em lote** resolve isso, checando diretamente na fonte da verdade e removendo candidatos defasados antes do ranqueamento final.
    
- **Alocação Atômica:** A operação de alocar a vaga ocorre junto com a revalidação e obedece à regra estrita `"só aloca se vagas > 0"`. Este é o limite final da solução de concorrência.
    

## 5. Algoritmo de Scoring

O cálculo do score de cada mentor utiliza a seguinte equação e distribuição de pesos:

```
Score Total = (
  expertise_match_weight * expertise_score +
  availability_match_weight * availability_score +
  language_match_weight * language_score +
  format_match_weight * format_score +
  experience_match_weight * experience_score
)
```

**Pesos Padrão:**

- Expertise: 0.40 (40%)
    
- Availability: 0.25 (25%)
    
- Language: 0.15 (15%)
    
- Format: 0.10 (10%)
    
- Experience: 0.10 (10%)
    

## 6. Endpoints Internos

|            |                                     |                            |
| ---------- | ----------------------------------- | -------------------------- |
| **Método** | **Endpoint**                        | **Descrição**              |
| POST       | `/matchmaking`                      | Encontrar melhor mentor    |
| POST       | `/matchmaking/batch`                | Lista ordenada de mentores |
| POST       | `/matchmaking/score`                | Calcular score específico  |
| GET        | `/matchmaking/decisions/{mentorId}` | Histórico de decisões      |