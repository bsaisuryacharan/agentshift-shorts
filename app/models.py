from datetime import datetime
from typing import Literal
from pathlib import Path

from pydantic import BaseModel, Field, HttpUrl


class Source(BaseModel):
    url: HttpUrl
    title: str
    publisher: str
    retrieved_at: datetime
    excerpt: str


class Claim(BaseModel):
    text: str
    source_ids: list[str] = Field(min_length=1)
    numeric: bool = False


class Idea(BaseModel):
    title: str
    angle: str
    score: float = Field(ge=0, le=100)
    sources: list[Source] = Field(min_length=1)


class TrendSignal(BaseModel):
    source: str
    format: str
    title: str
    url: str
    observed_at: datetime
    published_at: datetime | None = None
    metric: int | None = None
    short_form_confidence: float = Field(ge=0, le=1)
    notes: str = ""


class TrendReport(BaseModel):
    generated_at: datetime
    region: str
    signals: list[TrendSignal]
    source_status: dict[str, str]


class Script(BaseModel):
    hook: str
    body: list[str] = Field(min_length=2)
    ending: str
    title: str
    description: str
    claims: list[Claim] = Field(min_length=1)

    @property
    def narration(self) -> str:
        return " ".join([self.hook, *self.body, self.ending])


class Review(BaseModel):
    hook: int = Field(ge=1, le=10)
    visual_quality: int = Field(ge=1, le=10)
    accuracy: int = Field(ge=1, le=10)
    originality: int = Field(ge=1, le=10)
    policy: int = Field(ge=1, le=10)
    notes: str

    def approved(self, threshold: int) -> bool:
        return min(self.hook, self.visual_quality, self.accuracy, self.originality, self.policy) >= threshold


class CreativeTreatment(BaseModel):
    """An art-direction plan, not a request to generate generic effects."""

    id: str
    name: str
    concept: str
    visual_language: str
    object_chain: list[str] = Field(min_length=3)
    banned: list[str] = Field(min_length=3)
    palette: list[str] = Field(min_length=3)
    reference_techniques: list[str] = Field(min_length=1)
    iteration_directives: list[str] = Field(default_factory=list)


class VisualReview(BaseModel):
    hook: int = Field(ge=1, le=10)
    visual_hierarchy: int = Field(ge=1, le=10)
    motion_readability: int = Field(ge=1, le=10)
    composition: int = Field(ge=1, le=10)
    text_legibility: int = Field(ge=1, le=10)
    factual_visual_alignment: int = Field(ge=1, le=10)
    originality: int = Field(ge=1, le=10)
    verdict: str
    repair_notes: list[str] = Field(default_factory=list)

    def approved(self, threshold: int = 8) -> bool:
        scores = (
            self.hook, self.visual_hierarchy, self.motion_readability, self.composition,
            self.text_legibility, self.factual_visual_alignment, self.originality,
        )
        return min(scores) >= threshold and self.verdict == "approve"

    @property
    def average(self) -> float:
        return sum((self.hook, self.visual_hierarchy, self.motion_readability, self.composition,
                    self.text_legibility, self.factual_visual_alignment, self.originality)) / 7


class RunManifest(BaseModel):
    run_id: str
    created_at: datetime
    status: str
    idea: Idea | None = None
    script: Script | None = None
    review: Review | None = None
    creative_reviews: dict[str, VisualReview] = Field(default_factory=dict)
    selected_treatment: str | None = None
    video: Path | None = None
    errors: list[str] = Field(default_factory=list)


class Beat(BaseModel):
    """One visual beat. `say` is narration; the rest is art direction."""

    id: str
    kind: Literal["hook", "stat", "compare", "timeline", "diagram", "statement", "close"]
    say: str
    kicker: str = ""
    headline: str = ""
    sub: str = ""
    value: str = ""
    unit: str = ""
    left: str = ""
    right: str = ""
    left_pct: int = Field(default=60, ge=1, le=100)
    right_pct: int = Field(default=40, ge=1, le=100)
    ticks: list[str] = Field(default_factory=list)
    meta: list[str] = Field(default_factory=list)
    accent: Literal["hot", "electric", "acid"] = "hot"
    visual: str | None = None
    credit: str = ""
    duration: float | None = None
    claims: list[str] = Field(default_factory=list)


class VideoSpec(BaseModel):
    """Everything the deterministic frame generator needs. LLM produces this, code renders it."""

    id: str
    title: str
    thesis: str
    promise: str
    audience: str = "curiosity-scrollers, 16-34"
    voice: str = "michael"
    beats: list[Beat] = Field(min_length=4)
    sources: list[Source] = Field(min_length=1)
    claims: list[Claim] = Field(min_length=1)
    description: str = ""

    def estimate_durations(self) -> dict[str, float]:
        result = {}
        for beat in self.beats:
            words = len(beat.say.split())
            estimate = max(3.2, min(12.0, words / 2.55 + 0.55))
            result[beat.id] = round(beat.duration or estimate, 3)
        return result

    def to_script(self) -> Script:
        says = [beat.say for beat in self.beats]
        return Script(
            hook=says[0],
            body=says[1:-1],
            ending=says[-1],
            title=self.title,
            description=self.description or self.thesis,
            claims=self.claims,
        )
