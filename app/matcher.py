from uuid import UUID, uuid4
import psycopg
from psycopg.types.json import Jsonb
from pgvector.psycopg import register_vector

from app.config import (
    ALGORITHM_VERSION,
    CANDIDATE_MARGIN_MULTIPLIER,
    DATABASE_URL,
    DEFAULT_WEIGHTS,
)
from app.embeddings import generate_embedding
from app.origin_client import FakeOriginClient
from app.schemas import CandidateMatch, MatchRequestCreate
from app.scoring import calculate_candidate_score


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
                    skills,
                    format,
                    experience_years,
                    max_load,
                    availability_slots,
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
            for (
                mentor_id,
                name,
                skills,
                mentor_format,
                experience_years,
                max_load,
                mentor_slots,
                cosine_sim,
            ) in raw_candidates:
                status = origin_statuses.get(mentor_id)
                if not status or not status.is_active or status.available_slots <= 0:
                    continue

                total_score, breakdown = calculate_candidate_score(
                    requested_tags=payload.tags,
                    mentor_skills=skills,
                    cosine_sim=float(cosine_sim),
                    experience_years=experience_years,
                    min_experience_years=payload.filters.min_experience_years,
                    available_slots=status.available_slots,
                    max_load=max_load,
                    requested_slots=payload.filters.availability_slots,
                    mentor_slots=mentor_slots,
                    requested_format=payload.filters.format,
                    mentor_format=mentor_format,
                    weights=DEFAULT_WEIGHTS,
                )

                validated_candidates.append(
                    CandidateMatch(
                        mentor_id=mentor_id,
                        name=name,
                        rank=0,
                        total_score=total_score,
                        score_breakdown=breakdown,
                        explanation=None,
                    )
                )

            # Ordena, aplica corte Top-N e atribui posições
            validated_candidates.sort(key=lambda c: c.total_score, reverse=True)
            top_n = validated_candidates[: payload.limit]
            for idx, candidate in enumerate(top_n, start=1):
                candidate.rank = idx

            serialized_result = [c.model_dump() for c in top_n]

            with conn.cursor() as cur:
                # Persiste trilha de auditoria por mentor recomendado
                for candidate in top_n:
                    cur.execute(
                        """
                        INSERT INTO match_decisions (
                            id, match_request_id, mentor_id, rank_position,
                            total_score, score_breakdown, algorithm_version
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                        """,
                        (
                            uuid4(),
                            request_id,
                            candidate.mentor_id,
                            candidate.rank,
                            candidate.total_score,
                            Jsonb(candidate.score_breakdown.model_dump()),
                            ALGORITHM_VERSION,
                        ),
                    )

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
