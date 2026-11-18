import json
import sys
from pathlib import Path
import psycopg
from pgvector.psycopg import register_vector

# Garante import do pacote app/ ao rodar diretamente da raiz
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import (
    ALGORITHM_VERSION,
    CANDIDATE_MARGIN_MULTIPLIER,
    DATABASE_URL,
    DEFAULT_WEIGHTS,
)
from app.embeddings import generate_embedding
from app.origin_client import FakeOriginClient
from app.schemas import MatchRequestCreate
from app.scoring import calculate_candidate_score

DATASET_PATH = Path(__file__).parent / "dataset.json"
SQL_BASELINE_P3 = 0.53


def reindex_mentors(conn: psycopg.Connection, mentors: list[dict]) -> None:
    query = """
        UPDATE mentors_index
        SET embedding = %(embedding)s,
            version = version + 1,
            updated_at = NOW()
        WHERE mentor_id = %(mentor_id)s;
    """
    with conn.cursor() as cur:
        for m in mentors:
            emb = generate_embedding(f"{m['bio']} {' '.join(m['skills'])}")
            cur.execute(query, {"mentor_id": m["mentor_id"], "embedding": emb})
    conn.commit()


def evaluate(conn: psycopg.Connection, test_cases: list[dict]) -> None:
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

    precisions: list[float] = []
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    origin_client = FakeOriginClient()

    print(f"\n=== AVALIAÇÃO SCORING PONDERADO ({ALGORITHM_VERSION}) ===\n")

    with conn.cursor() as cur:
        for tc in test_cases:
            payload = MatchRequestCreate(**tc["request"])
            query_text = f"{payload.mentee_need_text} {' '.join(payload.tags)}".strip()
            query_vec = generate_embedding(query_text)

            cur.execute(
                search_sql,
                {
                    "query_vec": query_vec,
                    "language": payload.filters.language,
                    "format": payload.filters.format,
                    "min_experience_years": payload.filters.min_experience_years,
                    "candidate_limit": payload.limit * CANDIDATE_MARGIN_MULTIPLIER,
                },
            )
            raw_candidates = cur.fetchall()
            origin_statuses = origin_client.revalidate_batch(
                [r[0] for r in raw_candidates]
            )

            scored = []
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

                total, breakdown = calculate_candidate_score(
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
                scored.append((mentor_id, name, total, breakdown))

            scored.sort(key=lambda item: item[2], reverse=True)
            top_n = scored[: payload.limit]

            predicted_ids = [item[0] for item in top_n]
            expected_ids = tc["expected_mentor_ids"]

            hits = len(set(predicted_ids) & set(expected_ids))
            p_at_k = hits / payload.limit
            r_at_k = hits / len(expected_ids) if expected_ids else 0.0

            rr = 0.0
            for rank_idx, mid in enumerate(predicted_ids, start=1):
                if mid in expected_ids:
                    rr = 1.0 / rank_idx
                    break

            precisions.append(p_at_k)
            recalls.append(r_at_k)
            reciprocal_ranks.append(rr)

            print(f"[{tc['case_id']}] {tc['description']}")
            print(f"  Esperado : {expected_ids}")
            print(
                f"  Retornado: {predicted_ids} | P@3: {p_at_k:.2f} | R@3: {r_at_k:.2f} | RR: {rr:.2f}"
            )
            for mid, name, total, bd in top_n:
                print(
                    f"    - {mid} ({name}): total={total:.4f} "
                    f"[skills={bd.skills_overlap:.2f}, sem={bd.semantic_similarity:.2f}, "
                    f"sen={bd.seniority_fit:.2f}, load={bd.mentor_load:.2f}, goal={bd.goal_alignment:.2f}]"
                )
            print()

    avg_p = sum(precisions) / len(precisions)
    avg_r = sum(recalls) / len(recalls)
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
    delta_p = avg_p - SQL_BASELINE_P3

    print("------------------------------------------------------------------")
    print(
        f"SCORING v0.2.0 -> Precision@3: {avg_p:.2f} (vs Baseline {SQL_BASELINE_P3:.2f}, delta {delta_p:+.2f})"
    )
    print(f"                  Recall@3   : {avg_r:.2f} | MRR: {mrr:.2f}")
    print("------------------------------------------------------------------\n")


def main() -> None:
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    with psycopg.connect(DATABASE_URL) as conn:
        register_vector(conn)
        reindex_mentors(conn, data["mentors"])
        evaluate(conn, data["test_cases"])


if __name__ == "__main__":
    main()
