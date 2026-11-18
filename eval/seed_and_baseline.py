import hashlib
import json
from pathlib import Path
import numpy as np
import psycopg
from pgvector.psycopg import register_vector

DB_DSN = "postgresql://matchmaker:password@localhost:5433/matchmaking"
DATASET_PATH = Path(__file__).parent / "dataset.json"


def deterministic_embedding(text: str, dim: int = 384) -> list[float]:
    """Gera um vetor unitário determinístico de 384 dimensões para estruturar o índice no Bloco 1."""
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    vec = rng.normal(size=dim).astype(np.float32)
    norm = np.linalg.norm(vec)
    return (vec / norm).tolist() if norm > 0 else vec.tolist()


def seed_mentors(conn: psycopg.Connection, mentors: list[dict]) -> None:
    query = """
        INSERT INTO mentors_index (
            mentor_id, name, bio, skills, language, format,
            experience_years, current_load, max_load,
            availability_slots, is_active, embedding, version
        )
        VALUES (
            %(mentor_id)s, %(name)s, %(bio)s, %(skills)s, %(language)s, %(format)s,
            %(experience_years)s, %(current_load)s, %(max_load)s,
            %(availability_slots)s, %(is_active)s, %(embedding)s, 1
        )
        ON CONFLICT (mentor_id) DO UPDATE SET
            name = EXCLUDED.name,
            bio = EXCLUDED.bio,
            skills = EXCLUDED.skills,
            language = EXCLUDED.language,
            format = EXCLUDED.format,
            experience_years = EXCLUDED.experience_years,
            current_load = EXCLUDED.current_load,
            max_load = EXCLUDED.max_load,
            availability_slots = EXCLUDED.availability_slots,
            is_active = EXCLUDED.is_active,
            embedding = EXCLUDED.embedding,
            version = mentors_index.version + 1,
            updated_at = NOW();
    """
    with conn.cursor() as cur:
        for m in mentors:
            record = {
                **m,
                "embedding": deterministic_embedding(
                    f"{m['bio']} {' '.join(m['skills'])}"
                ),
            }
            cur.execute(query, record)
    conn.commit()


def run_sql_baseline(conn: psycopg.Connection, test_cases: list[dict]) -> None:
    baseline_sql = """
        SELECT
            mentor_id,
            name,
            COALESCE(cardinality(ARRAY(
                SELECT unnest(skills) INTERSECT SELECT unnest(%(tags)s::text[])
            )), 0) AS matched_tags
        FROM mentors_index
        WHERE is_active = TRUE
          AND language = %(language)s
          AND (format = %(format)s OR format = 'hibrido')
          AND experience_years >= %(min_experience_years)s
        ORDER BY matched_tags DESC, experience_years DESC, current_load ASC
        LIMIT %(limit)s;
    """

    precisions = []
    recalls = []

    print("\n=== AVALIAÇÃO BASELINE SQL PURO (TOP-3) ===\n")
    with conn.cursor() as cur:
        for tc in test_cases:
            req = tc["request"]
            filters = req["filters"]
            cur.execute(
                baseline_sql,
                {
                    "tags": req["tags"],
                    "language": filters["language"],
                    "format": filters["format"],
                    "min_experience_years": filters["min_experience_years"],
                    "limit": req["limit"],
                },
            )
            rows = cur.fetchall()
            predicted_ids = [r[0] for r in rows]
            expected_ids = tc["expected_mentor_ids"]

            hits = len(set(predicted_ids) & set(expected_ids))
            precision_at_k = hits / req["limit"]
            recall_at_k = hits / len(expected_ids) if expected_ids else 0.0

            precisions.append(precision_at_k)
            recalls.append(recall_at_k)

            print(f"[{tc['case_id']}] {tc['description']}")
            print(f"  Esperado : {expected_ids}")
            print(
                f"  Retornado: {predicted_ids} | Hits: {hits} | P@3: {precision_at_k:.2f} | R@3: {recall_at_k:.2f}\n"
            )

    avg_p = sum(precisions) / len(precisions)
    avg_r = sum(recalls) / len(recalls)
    print("------------------------------------------")
    print(
        f"MÉTRICA BASELINE -> Precision@3 média: {avg_p:.2f} | Recall@3 média: {avg_r:.2f}"
    )
    print("------------------------------------------\n")


def main() -> None:
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    with psycopg.connect(DB_DSN) as conn:
        register_vector(conn)
        seed_mentors(conn, data["mentors"])
        print(
            f"Carga concluída: {len(data['mentors'])} mentores indexados no PostgreSQL."
        )
        run_sql_baseline(conn, data["test_cases"])


if __name__ == "__main__":
    main()
