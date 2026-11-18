# UberHub Matchmaking Service (`v0.4.0-resilient-origin`)

Serviço backend orientado a eventos para recomendação e alocação de mentores e mentorados, combinando **busca híbrida (Vetorial + Full-Text Search via Reciprocal Rank Fusion)**, **scoring multi-critério auditável** e **mitigação de eventual consistency** contra o Sistema de Origem.

---

## Arquitetura e Fluxo de Dados

```text
[Sistema de Origem]
   │  (Eventos versionados: v1, v2, v3...)
   ▼
POST /events/mentors ──► [Indexador Idempotente] ──► PostgreSQL (pgvector + tsvector GIN)
                                                            ▲
[Cliente / API]                                             │ 1. Pré-filtro SQL + Busca Híbrida RRF (K = 4x N)
   │  POST /match-requests (202 Accepted + Idempotency-Key) │
   ▼                                                        │
[Worker Assíncrono] ────────────────────────────────────────┘
   │
   ├──► 2. Revalidação Batch no Sistema de Origem (Timeout + Retry + Circuit Breaker)
   │       ├─ Sucesso ──► revalidation_status = "validated"
   │       └─ Falha   ──► Fallback p/ capacidade local (revalidation_status = "unrevalidated")
   │
   ├──► 3. Scoring Multi-Critério (5 pesos) + Atenuação Operacional
   └──► 4. Persistência do Ranking + Trilha de Auditoria (match_decisions)