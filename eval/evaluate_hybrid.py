import json
import sys
from pathlib import Path
import psycopg
from pgvector.psycopg import register_vector

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import (
    ALGORITHM_VERSION,
    CANDIDATE_MARGIN_MULTIPLIER,
    DATABASE_URL,
    DEFAULT_WEIGHTS,
    RRF_K,
)
from app.embeddings import generate_embedding
from app.matcher import HYBRID_SEARCH_SQL
from app.origin_client import FakeOriginClient
from app.schemas import MatchRequestCreate
from app.scoring import calculate_candidate_score

DATASET_PATH = Path(__file__).parent / "dataset.json"
SQL_BASELINE_P3 = 0.53


def evaluate(conn: psycopg.Connection, test_cases: list[dict]) -> None:
    precisions: list[float] = []
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    origin_client = FakeOriginClient()

    print(f"\n=== AVALIAÇÃO BUSCA HÍBRIDA + RRF ({ALGORITHM_VERSION}) ===\n")

    with conn.cursor() as cur:
        for tc in test_cases:
            payload = MatchRequestCreate(**tc["request"])
            query_text = f"{payload.mentee_need_text} {' '.join(payload.tags)}".strip()
            query_vec = generate_embedding(query_text)
            fts_terms = " OR ".join(
                token
                for token in query_text.replace("-", " ").split()
                if len(token) >= 3
            )

            cur.execute(
                HYBRID_SEARCH_SQL,
                {
                    "query_vec": query_vec,
                    "fts_query": fts_terms or query_text,
                    "language": payload.filters.language,
                    "format": payload.filters.format,
                    "min_experience_years": payload.filters.min_experience_years,
                    "candidate_limit": payload.limit * CANDIDATE_MARGIN_MULTIPLIER,
                    "rrf_k": RRF_K,
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
                rrf_raw,
            ) in raw_candidates:
                status = origin_statuses.get(mentor_id)
                if not status or not status.is_active or status.available_slots <= 0:
                    continue

                total, breakdown = calculate_candidate_score(
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
                    f"[skills={bd.skills_overlap:.2f}, hyb={bd.semantic_similarity:.2f}, "
                    f"sen={bd.seniority_fit:.2f}, load={bd.mentor_load:.2f}, goal={bd.goal_alignment:.2f}]"
                )
            print()

    avg_p = sum(precisions) / len(precisions)
    avg_r = sum(recalls) / len(recalls)
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
    delta_p = avg_p - SQL_BASELINE_P3

    print("------------------------------------------------------------------")
    print(
        f"HYBRID RRF v0.3.0 -> Precision@3: {avg_p:.2f} (vs Baseline {SQL_BASELINE_P3:.2f}, delta {delta_p:+.2f})"
    )
    print(f"                     Recall@3   : {avg_r:.2f} | MRR: {mrr:.2f}")
    print("------------------------------------------------------------------\n")


def main() -> None:
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    with psycopg.connect(DATABASE_URL) as conn:
        register_vector(conn)
        evaluate(conn, data["test_cases"])


if __name__ == "__main__":
    main()
