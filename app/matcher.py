from uuid import UUID
import psycopg
from psycopg.types.json import Jsonb
from pgvector.psycopg import register_vector

from app.config import (
    ALGORITHM_VERSION,
    CANDIDATE_MARGIN_MULTIPLIER,
    DATABASE_URL,
)
from app.embeddings import generate_embedding
from app.origin_client import FakeOriginClient
from app.schemas import CandidateMatch, MatchRequestCreate, ScoreBreakdown


def process_match_request(request_id: UUID, payload: MatchRequestCreate) -> None:
    query_text = f"{payload.mentee_need_text} {' '.join(payload.tags)}".strip()
    query_vec = generate_embedding(query_text)
    candidate_limit = payload.limit * CANDIDATE_MARGIN_MULTIPLIER

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            register_vector(conn)

            # Etapa 2: Pré-filtro rígido + Busca vetorial com margem 4x N
            search_sql = """
                SELECT
                    mentor_id,
                    name,
                    1 - (embedding <=> %(query_vec)s::vector) AS cosine_sim
                FROM mentors_index
                WHERE is_active = TRUE
                  AND language = %(language)s
                  AND (format = %(format)s OR format = 'hibrido')
                  AND experience_years >= %(min_experience_years)s
                ORDER BY embedding <=> %(query_vec)s::vector ASC
                LIMIT %(candidate_limit)s;
            """
            with conn.cursor() as cur:
                cur.execute(
                    search_sql,
                    {
                        "query_vec": query_vec,
                        "language": payload.filters.language,
                        "format": payload.filters.format,
                        "min_experience_years": payload.filters.min_experience_years,
                        "candidate_limit": candidate_limit,
                    },
                )
                raw_candidates = cur.fetchall()

            # Etapa 3: Revalidação em lote no Sistema de Origem
            candidate_ids = [row[0] for row in raw_candidates]
            origin_statuses = FakeOriginClient().revalidate_batch(candidate_ids)

            validated_candidates: list[CandidateMatch] = []
            for mentor_id, name, cosine_sim in raw_candidates:
                status = origin_statuses.get(mentor_id)
                if not status or not status.is_active or status.available_slots <= 0:
                    continue

                # Normaliza cosseno [-1, 1] -> [0, 1] para o ranking básico da fatia vertical
                normalized_sim = round(
                    max(0.0, min(1.0, (float(cosine_sim) + 1.0) / 2.0)), 4
                )

                breakdown = ScoreBreakdown(
                    skills_overlap=0.0,
                    semantic_similarity=normalized_sim,
                    seniority_fit=0.0,
                    mentor_load=0.0,
                    goal_alignment=0.0,
                )
                validated_candidates.append(
                    CandidateMatch(
                        mentor_id=mentor_id,
                        name=name,
                        rank=0,
                        total_score=normalized_sim,
                        score_breakdown=breakdown,
                        explanation=None,
                    )
                )

            # Ordena e aplica corte Top-N
            validated_candidates.sort(key=lambda c: c.total_score, reverse=True)
            top_n = validated_candidates[: payload.limit]
            for idx, candidate in enumerate(top_n, start=1):
                candidate.rank = idx

            serialized_result = [c.model_dump() for c in top_n]

            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE match_requests
                    SET status = 'completed',
                        revalidation_status = 'validated',
                        result = %(result)s,
                        algorithm_version = %(algorithm_version)s,
                        updated_at = NOW()
                    WHERE id = %(id)s;
                    """,
                    {
                        "id": request_id,
                        "result": Jsonb(serialized_result),
                        "algorithm_version": ALGORITHM_VERSION,
                    },
                )
            conn.commit()

    except Exception:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE match_requests
                    SET status = 'failed',
                        updated_at = NOW()
                    WHERE id = %(id)s;
                    """,
                    {"id": request_id},
                )
            conn.commit()
        raise
