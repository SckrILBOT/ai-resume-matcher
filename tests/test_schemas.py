import pytest
from pydantic import ValidationError

from app.schemas.analysis import AnalysisResult

BULLET = {"original_or_weak_point": "a", "improved_bullet": "b", "why_it_works": "c"}


def make(**over):
    data = {
        "overall_match_score": 70,
        "category_scores": {"hard_skills_score": 60, "experience_score": 70, "ats_readability_score": 80},
        "executive_summary": "ok",
        "matched_keywords": ["Python"],
        "missing_keywords": ["Redis"],
        "bullet_improvements": [BULLET] * 3,
        "cover_letter": "Hi",
    }
    data.update(over)
    return data


def test_valid():
    assert AnalysisResult(**make()).overall_match_score == 70


@pytest.mark.parametrize("score", [-1, 101, 120])
def test_score_out_of_range(score):
    with pytest.raises(ValidationError):
        AnalysisResult(**make(overall_match_score=score))


def test_min_three_bullets():
    with pytest.raises(ValidationError):
        AnalysisResult(**make(bullet_improvements=[BULLET] * 2))


def test_gemini_config_accepts_schema():
    """response_schema из Pydantic-модели должен приниматься google-genai."""
    from google.genai import types

    cfg = types.GenerateContentConfig(response_mime_type="application/json", response_schema=AnalysisResult)
    assert cfg.response_schema is AnalysisResult
