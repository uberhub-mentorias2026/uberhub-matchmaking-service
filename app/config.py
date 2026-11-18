import os
from app.schemas import ScoreWeights

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://matchmaker:password@localhost:5433/matchmaking",
)
ALGORITHM_VERSION = "v0.1.0-vertical-slice"
CANDIDATE_MARGIN_MULTIPLIER = 4

DEFAULT_WEIGHTS = ScoreWeights(
    skills_overlap=0.30,
    semantic_similarity=0.30,
    seniority_fit=0.15,
    mentor_load=0.15,
    goal_alignment=0.10,
)
