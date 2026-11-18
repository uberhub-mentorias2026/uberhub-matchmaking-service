import psycopg
from pgvector.psycopg import register_vector

from app.config import DATABASE_URL
from app.embeddings import generate_embedding
from app.schemas import EventIngestionResult, MentorProfileEvent


def upsert_mentor_event(event: MentorProfileEvent) -> EventIngestionResult:
    embedding = generate_embedding(f"{event.bio} {' '.join(event.skills)}")
    skills_str = " ".join(event.skills)

    with psycopg.connect(DATABASE_URL) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            # 1. Proteção de idempotência por event_id
            cur.execute(
                """
                SELECT status FROM processed_events WHERE event_id = %s;
                """,
                (event.event_id,),
            )
            existing_event = cur.fetchone()
            if existing_event:
                return EventIngestionResult(
                    event_id=event.event_id,
                    mentor_id=event.mentor_id,
                    version=event.version,
                    status="duplicate_ignored",
                )

            # 2. Upsert versionado monotônico (descarta eventos fora de ordem)
            cur.execute(
                """
                INSERT INTO mentors_index (
                    mentor_id, name, bio, skills, language, format,
                    experience_years, current_load, max_load,
                    availability_slots, is_active, embedding, search_tsv, version, updated_at
                )
                VALUES (
                    %(mentor_id)s, %(name)s, %(bio)s, %(skills)s, %(language)s, %(format)s,
                    %(experience_years)s, %(current_load)s, %(max_load)s,
                    %(availability_slots)s, %(is_active)s, %(embedding)s,
                    setweight(to_tsvector('portuguese', %(fts_skills)s), 'A') ||
                    setweight(to_tsvector('portuguese', %(fts_name)s), 'B') ||
                    setweight(to_tsvector('portuguese', %(fts_bio)s), 'C'),
                    %(version)s,
                    NOW()
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
                    search_tsv = EXCLUDED.search_tsv,
                    version = EXCLUDED.version,
                    updated_at = NOW()
                WHERE EXCLUDED.version > mentors_index.version;
                """,
                {
                    **event.model_dump(exclude={"event_id"}),
                    "embedding": embedding,
                    "fts_skills": skills_str,
                    "fts_name": event.name,
                    "fts_bio": event.bio,
                },
            )

            status = "applied" if cur.rowcount > 0 else "stale_version_ignored"

            cur.execute(
                """
                INSERT INTO processed_events (event_id, mentor_id, event_version, status)
                VALUES (%s, %s, %s, %s);
                """,
                (event.event_id, event.mentor_id, event.version, status),
            )
        conn.commit()

    return EventIngestionResult(
        event_id=event.event_id,
        mentor_id=event.mentor_id,
        version=event.version,
        status=status,
    )
