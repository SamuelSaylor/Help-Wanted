"""Questionnaire stage: every question is optional; skipped ones keep model defaults."""

import re
import sys

import questionary
from pydantic import BaseModel, Field
from rich.console import Console

from help_wanted.contracts import ContributorProfile

SKIP = "Skip"
OTHER = "Other"

YEARS = {"Never": "none", "Under 1 year": "<1", "1-3 years": "1-3", "3+ years": "3+"}
GIT = {"New to it": "none", "Some experience": "some", "Comfortable": "comfortable"}
GOALS = {"Learn": "learn", "Build a portfolio": "portfolio", "Give back": "give back"}
TIME = {"1-2 hours": "1-2 hours", "A weekend": "a weekend", "Ongoing": "ongoing"}
POPULARITY = {"Small": "small", "Medium": "medium", "Large": "large", "No preference": "any"}
RECENT = {"Last month": "1 month", "Last 6 months": "6 months", "No preference": "any"}
COUNTS = {"1": 1, "2": 2, "3": 3}
CODING = ["Python", "JavaScript", "TypeScript", "Java", "C/C++", "C#", "Go", "Rust"]
SPOKEN = ["English", "Spanish", "Mandarin Chinese", "Hindi", "Arabic", "Portuguese", "French"]


class Keywords(BaseModel):
    search_keywords: list[str] = Field(default_factory=list)


class QuestionaryPrompter:
    """Async prompts: questionary's sync ask() cannot run inside the pipeline's event loop."""

    async def select(self, message, choices):
        answer = await questionary.select(message, choices=[*choices, SKIP]).unsafe_ask_async()
        return None if answer == SKIP else answer

    async def checkbox(self, message, choices):
        return await questionary.checkbox(
            message + " (space to select, enter to continue; none = skip)", choices=choices,
        ).unsafe_ask_async()

    async def text(self, message):
        return (await questionary.text(message + " (enter to skip)").unsafe_ask_async()).strip()


def _split(text):
    return [item.strip() for item in re.split(r"[,\n]", text or "") if item.strip()][:20]


def _unique(items):
    return list(dict.fromkeys(items))


async def _with_other(prompter, message, options):
    chosen = await prompter.checkbox(message, [*options, OTHER])
    if OTHER in chosen:
        chosen = [item for item in chosen if item != OTHER]
        chosen += _split(await prompter.text("Which others?"))
    return _unique(chosen)


async def ask_profile(prompter) -> dict:
    """Return only the answered fields; unanswered ones fall back to model defaults."""
    answers = {}

    async def pick(field, message, options):
        value = await prompter.select(message, list(options))
        if value is not None:
            answers[field] = options[value]

    await pick("years_programming", "How long have you been programming?", YEARS)
    await pick("git_experience", "How comfortable are you with Git?", GIT)
    past = await prompter.text("Any past contributions to open source or team projects?")
    if past:
        answers["past_contributions"] = past
    coding = await _with_other(prompter, "Which programming languages do you use?", CODING)
    if coding:
        answers["coding_languages"] = coding
    native = await prompter.select("What is your native language? (Recommendations use it)", [*SPOKEN, OTHER])
    if native == OTHER:
        native = (_split(await prompter.text("Which language?")) or [None])[0]
    if native:
        others = [lang for lang in SPOKEN if lang != native]
        extra = await _with_other(prompter, "Any other languages you read comfortably?", others)
        answers["spoken_languages"] = _unique([native, *extra])
    await pick("contribution_goal", "What is your main goal?", GOALS)
    await pick("time_available", "How much time do you have?", TIME)
    await pick("project_popularity", "What size of project do you want?", POPULARITY)
    await pick("recent_activity", "How recently should the project have been active?", RECENT)
    beginner = await prompter.select("Only show issues labelled for beginners?", ["Yes", "No"])
    if beginner is not None:
        answers["beginner_friendly_only"] = beginner == "Yes"
    await pick("recommendation_count", "How many recommendations do you want?", COUNTS)
    for field, message in (
        ("interests", "What topics or hobbies excite you? (comma-separated)"),
        ("industries", "What industry or field are you in, or want to work in?"),
        ("project_types", "What kind of project would you like to help build? (e.g. web app, CLI tool)"),
    ):
        items = _split(await prompter.text(message))
        if items:
            answers[field] = items
    return answers


async def extract_keywords(context, answers) -> list[str]:
    """Gemma turns the free-text answers into search keywords; commas are the fallback."""
    texts = [item for field in ("interests", "industries", "project_types") for item in answers.get(field, [])]
    if answers.get("past_contributions"):
        texts.append(answers["past_contributions"])
    if not texts:
        return []
    try:
        result = await context.structured(Keywords, [
            ("system", "Extract up to 10 short GitHub search keywords (topics, domains, technologies) "
                       "from a newcomer's answers. Reply only with the structured result."),
            ("human", "\n".join(texts)),
        ])
        keywords = [word.strip() for word in result.search_keywords if word.strip()]
    except Exception:
        keywords = []
    return _unique(keywords or texts)[:10]


async def run(context, *, setup, prompter=None):
    if prompter is None:
        if not sys.stdin.isatty():
            return context.profile
        prompter = QuestionaryPrompter()
        Console().print("Every question is optional: choose Skip or press enter to use defaults.")
    answers = await ask_profile(prompter)
    answers["search_keywords"] = await extract_keywords(context, answers)
    return ContributorProfile(**answers)
