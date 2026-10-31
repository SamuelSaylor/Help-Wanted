import asyncio
from pathlib import Path

from help_wanted.contracts import ContributorProfile, SetupResult
from help_wanted.pipeline import StageContext
from help_wanted.stages import questionnaire


class Script:
    """Answers prompts in order; None means the question is skipped."""

    def __init__(self, *answers):
        self.answers = list(answers)

    async def _next(self):
        return self.answers.pop(0)

    async def select(self, message, choices):
        return await self._next()

    async def checkbox(self, message, choices):
        return (await self._next()) or []

    async def text(self, message):
        return (await self._next()) or ""


class FakeModel:
    def __init__(self, keywords=None, fail=False):
        self.keywords, self.fail = keywords or [], fail

    def with_structured_output(self, schema, *, method):
        outer = self

        class Runnable:
            async def ainvoke(self, messages):
                if outer.fail:
                    raise RuntimeError("ollama down")
                return schema(search_keywords=outer.keywords)

        return Runnable()


def run_stage(prompter, model=None):
    context = StageContext(
        model=model or FakeModel(), tools=(), username="octocat",
        profile=ContributorProfile(), output_directory=Path("."),
    )
    return asyncio.run(questionnaire.run(context, setup=SetupResult(username="octocat"), prompter=prompter))


def test_skipping_everything_gives_model_defaults():
    profile = run_stage(Script(*[None] * 15))
    assert profile == ContributorProfile()


def test_answers_map_to_contract_values_and_gemma_fills_keywords():
    profile = run_stage(Script(
        "3+ years", None, "fixed a typo",
        ["Python", "Other"], "Rust, Zig",
        "Spanish", ["English"],
        "Build a portfolio", "A weekend", "Small", "Last month", "No", "2",
        "music, games", "healthcare", "CLI tool",
    ), FakeModel(keywords=["audio", "game dev"]))
    assert profile.years_programming == "3+"
    assert profile.git_experience == "none"
    assert profile.coding_languages == ["Python", "Rust", "Zig"]
    assert profile.spoken_languages == ["Spanish", "English"]
    assert profile.beginner_friendly_only is False
    assert profile.recommendation_count == 2
    assert profile.industries == ["healthcare"]
    assert profile.search_keywords == ["audio", "game dev"]


def test_keywords_fall_back_to_the_free_text_when_gemma_fails():
    profile = run_stage(Script(
        None, None, None, [], None, None, None, None, None, None, None,
        "music, games", None, None,
    ), FakeModel(fail=True))
    assert profile.search_keywords == ["music", "games"]


def test_non_interactive_run_keeps_the_given_profile():
    context = StageContext(
        model=None, tools=(), username="octocat",
        profile=ContributorProfile(spoken_languages=["French"]), output_directory=Path("."),
    )
    result = asyncio.run(questionnaire.run(context, setup=SetupResult(username="octocat")))
    assert result.spoken_languages == ["French"]
