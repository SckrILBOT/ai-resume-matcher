from enum import Enum

from pydantic import BaseModel, Field


class Tone(str, Enum):
    PROFESSIONAL = "Профессиональный"
    STARTUP = "Уверенный / Стартап"
    CONCISE = "Краткий и по делу"


class CategoryScores(BaseModel):
    hard_skills_score: int = Field(ge=0, le=100, description="Совпадение по стеку и технологиям")
    experience_score: int = Field(ge=0, le=100, description="Релевантность опыта и проектов")
    ats_readability_score: int = Field(
        ge=0, le=100, description="Структура и насыщенность ключевыми словами"
    )


class BulletImprovement(BaseModel):
    original_or_weak_point: str = Field(
        description="Цитата слабого буллита из резюме или описание того, чего не хватает"
    )
    improved_bullet: str = Field(
        description="Готовая сильная формулировка по методу XYZ (достижение + метрика + технологии)"
    )
    why_it_works: str = Field(description="Почему эта формулировка усилит резюме")


class AnalysisResult(BaseModel):
    overall_match_score: int = Field(ge=0, le=100, description="Общий процент совпадения")
    category_scores: CategoryScores
    executive_summary: str = Field(description="Вердикт AI-рекрутера, 2-3 предложения")
    matched_keywords: list[str] = Field(description="Ключевые слова вакансии, найденные в резюме")
    missing_keywords: list[str] = Field(description="Критичные ключевые слова вакансии, которых нет в резюме")
    bullet_improvements: list[BulletImprovement] = Field(min_length=3)
    cover_letter: str = Field(description="Готовое сопроводительное письмо")


class LLMInfo(BaseModel):
    """Какая модель сделала разбор. Не входит в схему для LLM, добавляется сервером."""

    provider: str
    vendor: str
    model: str
    label: str
    fallback: bool = Field(description="Ответила резервная модель, потому что основная была недоступна")


class AnalysisResponse(AnalysisResult):
    llm: LLMInfo
