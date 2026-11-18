import logging
from uuid import UUID, uuid4
import psycopg
from psycopg.types.json import Jsonb
from pgvector.psycopg import register_vector

from app.config import (
    ALGORITHM_VERSION,
    CANDIDATE_MARGIN_MULTIPLIER,
    DATABASE_URL,
    DEFAULT_WEIGHTS,
    RRF_K,
)
from app.embeddings import generate_embedding
from app.origin_client import (
    OriginMentorStatus,
    OriginServiceUnavailableError,
    ResilientOriginClient,
)
from app.schemas import CandidateMatch, MatchRequestCreate
from app.scoring import calculate_candidate_score

logger = logging.getLogger("matchmaking.matcher")

HYBRID_SEARCH_SQL = """
    WITH filtered_mentors AS (
        SELECT
            mentor_id,
            name,
            skills,
            format,
            experience_years,
            current_load,
            max_load,
            availability_slots,
            embedding,
            search_tsv
        FROM mentors_index
        WHERE is_active = TRUE
          AND language = %(language)s
          AND (format = %(format)s OR format = 'hibrido')
          AND experience_years >= %(min_experience_years)s
    ),
    vector_ranked AS (
        SELECT
            mentor_id,
            1 - (embedding <=> %(query_vec)s::vector) AS cosine_sim,
            ROW_NUMBER() OVER (ORDER BY embedding <=> %(query_vec)s::vector ASC) AS vec_rank
        FROM filtered_mentors
        LIMIT %(candidate_limit)s
    ),
    lexical_ranked AS (
        SELECT
            mentor_id,
            ROW_NUMBER() OVER (
                ORDER BY ts_rank_cd(search_tsv, websearch_to_tsquery('portuguese', %(fts_query)s)) DESC
            ) AS lex_rank
        FROM filtered_mentors
        WHERE search_tsv @@ websearch_to_tsquery('portuguese', %(fts_query)s)
        LIMIT %(candidate_limit)s
    ),
    rrf_fused AS (
        SELECT
            COALESCE(v.mentor_id, l.mentor_id) AS mentor_id,
            COALESCE(v.cosine_sim, 0.0) AS cosine_sim,
            (
                COALESCE(1.0 / (%(rrf_k)s + v.vec_rank), 0.0) +
                COALESCE(1.0 / (%(rrf_k)s + l.lex_rank), 0.0)
            ) AS rrf_raw
        FROM vector_ranked v
        FULL OUTER JOIN lexical_ranked l ON v.mentor_id = l.mentor_id
    )
    SELECT
        f.mentor_id,
        f.name,
        f.skills,
        f.format,
        f.experience_years,
        f.current_load,
        f.max_load,
        f.availability_slots,
        r.cosine_sim,
        r.rrf_raw
    FROM rrf_fused r
    JOIN filtered_mentors f ON f.mentor_id = r.mentor_id
    ORDER BY r.rrf_raw DESC
    LIMIT %(candidate_limit)s;
"""


def process_match_request(
    request_id: UUID,
    payload: MatchRequestCreate,
    origin_client: ResilientOriginClient | None = None,
) -> None:
    query_text = f"{payload.mentee_need_text} {' '.join(payload.tags)}".strip()
    query_vec = generate_embedding(query_text)
    fts_terms = " OR ".join(
        token for token in query_text.replace("-", " ").split() if len(token) >= 3
    )
    candidate_limit = payload.limit * CANDIDATE_MARGIN_MULTIPLIER
    client = origin_client or ResilientOriginClient()

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            register_vector(conn)

            with conn.cursor() as cur:
                cur.execute(
                    HYBRID_SEARCH_SQL,
                    {
                        "query_vec": query_vec,
                        "fts_query": fts_terms or query_text,
                        "language": payload.filters.language,
                        "format": payload.filters.format,
                        "min_experience_years": payload.filters.min_experience_years,
                        "candidate_limit": candidate_limit,
                        "rrf_k": RRF_K,
                    },
                )
                raw_candidates = cur.fetchall()

            candidate_ids = [row[0] for row in raw_candidates]

            # Etapa 3: Revalidação em lote com fallback gracioso para cache local
            revalidation_status = "validated"
            try:
                origin_statuses = client.revalidate_batch(candidate_ids)
            except OriginServiceUnavailableError as exc:
                logger.warning(
                    "Origem indisponível para request %s (%s). Aplicando fallback local.",
                    request_id,
                    exc,
                )
                revalidation_status = "unrevalidated"
                origin_statuses = {
                    row[0]: OriginMentorStatus(
                        mentor_id=row[0],
                        is_active=True,
                        available_slots=max(0, row[6] - row[5]),
                    )
                    for row in raw_candidates
                }

            validated_candidates: list[CandidateMatch] = []
            for (
                mentor_id,
                name,
                skills,
                mentor_format,
                experience_years,
                _current_load,
                max_load,
                mentor_slots,
                cosine_sim,
                rrf_raw,
            ) in raw_candidates:
                status = origin_statuses.get(mentor_id)
                if not status or not status.is_active or status.available_slots <= 0:
                    continue

                total_score, breakdown = calculate_candidate_score(
                    requested_tags=payload.tags,
                    mentor_skills=skills,
                    cosine_sim=float(cosine_sim),
                    rrf_raw=float(rrf_raw),
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

                explanation = None
                if payload.include_explanation:
                    explanation = (
                        f"Score {total_score:.2f} | Skills: {breakdown.skills_overlap:.0%}, "
                        f"Relevância Híbrida: {breakdown.semantic_similarity:.0%}, "
                        f"Vagas ({revalidation_status}): {status.available_slots}/{max_load}."
                    )

                validated_candidates.append(
                    CandidateMatch(
                        mentor_id=mentor_id,
                        name=name,
                        rank=0,
                        total_score=total_score,
                        score_breakdown=breakdown,
                        explanation=explanation,
                    )
                )

            validated_candidates.sort(key=lambda c: c.total_score, reverse=True)
            top_n = validated_candidates[: payload.limit]
            for idx, candidate in enumerate(top_n, start=1):
                candidate.rank = idx

            serialized_result = [c.model_dump() for c in top_n]

            with conn.cursor() as cur:
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
                        revalidation_status = %(revalidation_status)s,
                        result = %(result)s,
                        algorithm_version = %(algorithm_version)s,
                        updated_at = NOW()
                    WHERE id = %(id)s;
                    """,
                    {
                        "id": request_id,
                        "revalidation_status": revalidation_status,
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