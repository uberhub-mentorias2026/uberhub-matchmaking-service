from uuid import UUID, uuid4
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, status
import psycopg
from psycopg.types.json import Jsonb

from app.config import ALGORITHM_VERSION, DATABASE_URL
from app.matcher import process_match_request
from app.schemas import (
    CandidateMatch,
    MatchRequestAccepted,
    MatchRequestCreate,
    MatchResultResponse,
    MentorDecisionAudit,
    ScoreBreakdown,
)

app = FastAPI(title="Matchmaking Service", version="0.2.0")


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/match-requests",
    response_model=MatchRequestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_match_request(
    payload: MatchRequestCreate,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MatchRequestAccepted:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            if idempotency_key:
                cur.execute(
                    "SELECT id, status FROM match_requests WHERE idempotency_key = %s;",
                    (idempotency_key,),
                )
                existing = cur.fetchone()
                if existing:
                    return MatchRequestAccepted(
                        match_request_id=existing[0],
                        status=existing[1],
                    )

            request_id = uuid4()
            cur.execute(
                """
                INSERT INTO match_requests (
                    id, idempotency_key, status, revalidation_status, payload, algorithm_version
                )
                VALUES (%s, %s, 'processing', 'pending', %s, %s);
                """,
                (
                    request_id,
                    idempotency_key,
                    Jsonb(payload.model_dump()),
                    ALGORITHM_VERSION,
                ),
            )
        conn.commit()

    background_tasks.add_task(process_match_request, request_id, payload)
    return MatchRequestAccepted(match_request_id=request_id, status="processing")


@app.get("/match-requests/{match_request_id}", response_model=MatchResultResponse)
def get_match_request(match_request_id: UUID) -> MatchResultResponse:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, status, revalidation_status, algorithm_version, result, created_at
                FROM match_requests
                WHERE id = %s;
                """,
                (match_request_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Match request not found.",
        )

    raw_candidates = row[4] or []
    candidates = [CandidateMatch(**item) for item in raw_candidates]

    return MatchResultResponse(
        match_request_id=row[0],
        status=row[1],
        revalidation_status=row[2],
        algorithm_version=row[3],
        candidates=candidates,
        created_at=row[5],
    )


@app.get("/decisions/{mentor_id}", response_model=list[MentorDecisionAudit])
def get_mentor_decisions(mentor_id: str, limit: int = 20) -> list[MentorDecisionAudit]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, match_request_id, mentor_id, rank_position,
                       total_score, score_breakdown, algorithm_version, created_at
                FROM match_decisions
                WHERE mentor_id = %s
                ORDER BY created_at DESC
                LIMIT %s;
                """,
                (mentor_id, limit),
            )
            rows = cur.fetchall()

    return [
        MentorDecisionAudit(
            decision_id=row[0],
            match_request_id=row[1],
            mentor_id=row[2],
            rank_position=row[3],
            total_score=float(row[4]),
            score_breakdown=ScoreBreakdown(**row[5]),
            algorithm_version=row[6],
            created_at=row[7],
        )
        for row in rows
    ]
