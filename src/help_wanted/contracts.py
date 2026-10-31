"""Validated stage boundaries. profile.json follows the questionnaire contract."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContributorProfile(Contract):
    interests: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    search_keywords: list[str] = Field(default_factory=list)
    project_types: list[str] = Field(default_factory=list)
    coding_languages: list[str] = Field(default_factory=list)
    spoken_languages: list[str] = Field(default_factory=lambda: ["English"], min_length=1)
    years_programming: Literal["none", "<1", "1-3", "3+"] = "none"
    git_experience: Literal["none", "some", "comfortable"] = "none"
    past_contributions: str = ""
    contribution_goal: str = "learn"
    time_available: Literal["1-2 hours", "a weekend", "ongoing"] = "1-2 hours"
    project_popularity: Literal["small", "medium", "large", "any"] = "any"
    contributor_count: Literal["<10", "10-100", "100+", "any"] = "any"
    recent_activity: Literal["1 month", "6 months", "any"] = "any"
    beginner_friendly_only: bool = True
    recommendation_count: int = Field(default=3, ge=1)


class SetupResult(Contract):
    username: str
    message: str = "Setup placeholder: no installation or sign-in was performed."


class SkillAssessment(Contract):
    username: str
    experience_level: str
    summary: str
    coding_languages: list[str] = Field(default_factory=list)
    new_to_github: bool = False


class CandidateProject(Contract):
    full_name: str
    url: str
    description: str = ""
    language: str | None = None
    stars: int = 0
    reason: str = ""
    readme_status: str = ""


class CandidateProjects(Contract):
    projects: list[CandidateProject] = Field(default_factory=list)
    spares: list[CandidateProject] = Field(default_factory=list)
    reason: str = ""


class SelectedIssue(Contract):
    project: str
    number: int
    title: str
    url: str
    project_url: str
    labels: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None
    body: str = ""


class IssueSelection(Contract):
    issues: list[SelectedIssue] = Field(default_factory=list)
    reason: str = ""


class Recommendation(Contract):
    issue: SelectedIssue
    why_it_fits: str
    what_you_will_learn: str
    first_steps: list[str]


class Recommendations(Contract):
    recommendations: list[Recommendation] = Field(default_factory=list)
    markdown: str


class PipelineResult(Contract):
    username: str
    output_directory: str
    completed_stages: list[str]
    skipped_stages: list[str]
    recommendations: str
