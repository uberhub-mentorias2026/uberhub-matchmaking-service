import os
from app.schemas import ScoreWeights

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://matchmaker:password@localhost:5433/matchmaking",
)
ALGORITHM_VERSION = "v0.3.0-hybrid-rrf"
CANDIDATE_MARGIN_MULTIPLIER = 4
RRF_K = 60

DEFAULT_WEIGHTS = ScoreWeights(
    skills_overlap=0.30,
    semantic_similarity=0.35,
    seniority_fit=0.15,
    mentor_load=0.10,
    goal_alignment=0.10,
)
