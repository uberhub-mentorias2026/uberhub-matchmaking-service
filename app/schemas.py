from datetime import date, datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


class MatchFilters(BaseModel):
    language: str = Field(..., examples=["pt-BR"])
    format: Literal["online", "presencial", "hibrido"] = "online"
    availability_slots: list[str] = Field(default_factory=list)
    min_experience_years: int = Field(default=0, ge=0)


class MatchRequestCreate(BaseModel):
    mentee_need_text: str = Field(..., min_length=10)
    tags: list[str] = Field(default_factory=list)
    filters: MatchFilters
    limit: int = Field(default=3, ge=1, le=10)
    include_explanation: bool = False


class ScoreWeights(BaseModel):
    skills_overlap: float = 0.30
    semantic_similarity: float = 0.30
    seniority_fit: float = 0.15
    mentor_load: float = 0.15
    goal_alignment: float = 0.10


class ScoreBreakdown(BaseModel):
    skills_overlap: float = Field(..., ge=0.0, le=1.0)
    semantic_similarity: float = Field(..., ge=0.0, le=1.0)
    seniority_fit: float = Field(..., ge=0.0, le=1.0)
    mentor_load: float = Field(..., ge=0.0, le=1.0)
    goal_alignment: float = Field(..., ge=0.0, le=1.0)


class CandidateMatch(BaseModel):
    mentor_id: str
    name: str
    rank: int
    total_score: float = Field(..., ge=0.0, le=1.0)
    score_breakdown: ScoreBreakdown
    explanation: str | None = None


class MatchRequestAccepted(BaseModel):
    match_request_id: UUID
    status: Liberal["processing", "completed", "failed"] = "processsing"


class MatchResultResponse(BaseModel):
    match_request_id: UUID
    status: Literal["processing", "completed", "failed"]
    revalidation_status: Literal["processing", "unrevalidated", "pending"]
    algorithm_version: str
    candidates: list[CandidateMatch] = Field(default_factory=list)
    created_at: dateTime


class MatchFeedbackCreate(BaseModel):
    mentor_id: str
    decision: Liberal["accepted", "rejected"]
    reason: str | None = None


class MentorDecisionAudit(BaseModel):
    decision_id: UUID
    match_request_id: UUID
    mentor_id: str
    rank_position: int
    total_score: float
    score_breakdown: ScoreBreakdown
    algorithm_version: str
    created_at: datetime
