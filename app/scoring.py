from app.schemas import ScoreBreakdown, ScoreWeights


def _normalize_tokens(items: list[str]) -> set[str]:
    return {item.strip().lower() for item in items if item.strip()}


def compute_skills_overlap(
    requested_tags: list[str], mentor_skills: list[str]
) -> float:
    req = _normalize_tokens(requested_tags)
    if not req:
        return 1.0
    skills = _normalize_tokens(mentor_skills)
    return len(req & skills) / len(req)


def compute_semantic_similarity(cosine_sim: float) -> float:
    return max(0.0, min(1.0, float(cosine_sim)))


def compute_seniority_fit(experience_years: int, min_experience_years: int) -> float:
    if min_experience_years <= 0:
        return min(1.0, experience_years / 10.0)
    if experience_years < min_experience_years:
        return max(0.0, experience_years / min_experience_years)
    # 0.70 por atingir o mínimo + até 0.30 de bônus por até +5 anos de experiência adicional
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
    breakdown = ScoreBreakdown(
        skills_overlap=round(compute_skills_overlap(requested_tags, mentor_skills), 4),
        semantic_similarity=round(compute_semantic_similarity(cosine_sim), 4),
        seniority_fit=round(
            compute_seniority_fit(experience_years, min_experience_years), 4
        ),
        mentor_load=round(compute_mentor_load(available_slots, max_load), 4),
        goal_alignment=round(
            compute_goal_alignment(
                requested_slots, mentor_slots, requested_format, mentor_format
            ),
            4,
        ),
    )

    total_weight = (
        weights.skills_overlap
        + weights.semantic_similarity
        + weights.seniority_fit
        + weights.mentor_load
        + weights.goal_alignment
    ) or 1.0

    weighted_sum = (
        breakdown.skills_overlap * weights.skills_overlap
        + breakdown.semantic_similarity * weights.semantic_similarity
        + breakdown.seniority_fit * weights.seniority_fit
        + breakdown.mentor_load * weights.mentor_load
        + breakdown.goal_alignment * weights.goal_alignment
    ) / total_weight

    return round(max(0.0, min(1.0, weighted_sum)), 4), breakdown
