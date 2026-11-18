from app.schemas import ScoreBreakdown, ScoreWeights


def _normalize_tokens(items: list[str]) -> set[str]:
    return {item.strip().lower() for item in items if item.strip()}


def compute_skills_overlap(requested_tags: list[str], mentor_skills: list[str]) -> float:
    req = _normalize_tokens(requested_tags)
    if not req:
        return 1.0
    skills = _normalize_tokens(mentor_skills)
    return len(req & skills) / len(req)


def compute_hybrid_relevance(cosine_sim: float, rrf_raw: float, rrf_k: int = 60) -> float:
    max_rrf = 2.0 / (rrf_k + 1)
    norm_rrf = max(0.0, min(1.0, float(rrf_raw) / max_rrf))
    norm_cos = max(0.0, min(1.0, float(cosine_sim)))
    return (0.55 * norm_cos) + (0.45 * norm_rrf)


def compute_seniority_fit(experience_years: int, min_experience_years: int) -> float:
    if min_experience_years <= 0:
        return min(1.0, experience_years / 10.0)
    if experience_years < min_experience_years:
        return max(0.0, experience_years / min_experience_years)
    bonus = min(1.0, (experience_years - min_experience_years) / 5.0)
    return 0.70 + (0.30 * bonus)


def compute_mentor_load(available_slots: int, max_load: int) -> float:
    capacity = max(1, max_load)
    return max(0.0, min(1.0, available_slots / capacity))


def compute_goal_alignment(
    requested_slots: list[str],
    mentor_slots: list[str],
    requested_format: str,
    mentor_format: str,
) -> float:
    req = _normalize_tokens(requested_slots)
    if not req:
        slot_score = 1.0
    else:
        avail = _normalize_tokens(mentor_slots)
        slot_score = len(req & avail) / len(req)

    format_score = 1.0 if mentor_format == requested_format else 0.85
    return (0.80 * slot_score) + (0.20 * format_score)


def calculate_candidate_score(
    *,
    requested_tags: list[str],
    mentor_skills: list[str],
    cosine_sim: float,
    rrf_raw: float,
    experience_years: int,
    min_experience_years: int,
    available_slots: int,
    max_load: int,
    requested_slots: list[str],
    mentor_slots: list[str],
    requested_format: str,
    mentor_format: str,
    weights: ScoreWeights,
) -> tuple[float, ScoreBreakdown]:
    skills_score = compute_skills_overlap(requested_tags, mentor_skills)
    hybrid_score = compute_hybrid_relevance(cosine_sim, rrf_raw)
    seniority_score = compute_seniority_fit(experience_years, min_experience_years)
    load_score = compute_mentor_load(available_slots, max_load)
    goal_score = compute_goal_alignment(
        requested_slots, mentor_slots, requested_format, mentor_format
    )

    breakdown = ScoreBreakdown(
        skills_overlap=round(skills_score, 4),
        semantic_similarity=round(hybrid_score, 4),
        seniority_fit=round(seniority_score, 4),
        mentor_load=round(load_score, 4),
        goal_alignment=round(goal_score, 4),
    )

    total_weight = (
        weights.skills_overlap
        + weights.semantic_similarity
        + weights.seniority_fit
        + weights.mentor_load
        + weights.goal_alignment
    ) or 1.0

    technical_fit = (skills_score + hybrid_score) / 2.0
    operational_multiplier = 1.0 if technical_fit >= 0.25 else 0.35

    weighted_sum = (
        breakdown.skills_overlap * weights.skills_overlap
        + breakdown.semantic_similarity * weights.semantic_similarity
        + (breakdown.seniority_fit * weights.seniority_fit) * operational_multiplier
        + (breakdown.mentor_load * weights.mentor_load) * operational_multiplier
        + (breakdown.goal_alignment * weights.goal_alignment) * operational_multiplier
    ) / total_weight

    return round(max(0.0, min(1.0, weighted_sum)), 4), breakdown
