import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://matchmaker:password@localhost:5433/matchmaking",
)
ALGORITHM_VERSION = "v0.1.0-vertical-slice"
CANDIDATE_MARGIN_MULTIPLIER = 4
