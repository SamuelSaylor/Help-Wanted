import asyncio
import json

import pytest

from help_wanted.contracts import (
    CandidateProject, CandidateProjects, ContributorProfile, IssueSelection,
    SelectedIssue, SkillAssessment,
)
from help_wanted.pipeline import run_pipeline


def cache_inputs(tmp_path, *, language="Spanish", issues=None, count=1, reason=""):
    folder = tmp_path / "octocat"
    folder.mkdir()
    values = {
        "profile.json": ContributorProfile(
            spoken_languages=[language, "English"], interests=["music"],
            coding_languages=["Python"], recommendation_count=count,
        ),
        "skills.json": SkillAssessment(
            username="octocat", experience_level="beginner",
            summary="New to GitHub", new_to_github=True,
        ),
        "projects.json": CandidateProjects(projects=[CandidateProject(
            full_name="music/player", url="https://github.com/music/player",
            description="A Python music player",
        )]),
        "issues.json": IssueSelection(issues=issues if issues is not None else [
            SelectedIssue(
                project="music/player", number=12, title="Fix playlist ordering",
                url="https://github.com/music/player/issues/12",
                project_url="https://github.com/music/player",
                body="The playlist sorts backwards. See CONTRIBUTING.md for tests.",
            ),
        ], reason=reason),
    }
    for filename, value in values.items():
        (folder / filename).write_text(value.model_dump_json(), encoding="utf-8")
    return folder


class ScriptedModel:
    def __init__(self, response):
        self.response = response

    def with_structured_output(self, schema, *, method):
        assert method == "json_schema"
        response = self.response

        class Reply:
            async def ainvoke(self, messages):
                if callable(response):
                    return response(json.loads(messages[-1]["content"]))
                return response

        return Reply()


def spanish_response():
    return {
        "heading": "Tus recomendaciones",
        "why_heading": "Por qué encaja contigo",
        "learn_heading": "Qué aprenderás",
        "steps_heading": "Primeros pasos",
        "notice": "",
        "narratives": [{
            "why_it_fits": "Combina tu interés por la música con Python y tu meta de aprender.",
            "what_you_will_learn": "Aprenderás a corregir el orden de una lista.",
            "first_steps": [
                "Abre la incidencia y lee la descripción del problema.",
                "Crea tu copia del proyecto con el botón Fork de GitHub.",
                "Lee CONTRIBUTING.md para encontrar las instrucciones de pruebas.",
            ],
            "title": "Título traducido que no debe sustituir al original",
            "url": "https://example.com/fabricated",
        }],
    }


def test_native_language_recommendations_keep_original_issue_identity(tmp_path):
    folder = cache_inputs(tmp_path)

    def localized_response(data):
        if data["native_language"] == "Spanish":
            return spanish_response()
        response = spanish_response()
        response["heading"] = "Vos recommandations"
        response["narratives"][0]["why_it_fits"] = "Ce projet correspond à vos intérêts."
        return response

    result = asyncio.run(run_pipeline(
        ScriptedModel(localized_response), [], username="octocat", output_root=tmp_path,
        profile=ContributorProfile(spoken_languages=["French"]),
    ))
    markdown = (folder / "recommendations.md").read_text()
    assert result.recommendations == markdown
    assert result.skipped_stages == ["questionnaire", "skill_scan", "discovery", "issue_search"]
    assert "[Fix playlist ordering](https://github.com/music/player/issues/12)" in markdown
    assert "[music/player](https://github.com/music/player)" in markdown
    assert "## 1. Fix playlist ordering" in markdown
    assert "### Por qué encaja contigo" in markdown
    assert "Combina tu interés por la música" in markdown
    assert "### Qué aprenderás" in markdown
    assert "Aprenderás a corregir" in markdown
    assert "1. Abre la incidencia" in markdown
    assert "3. Lee CONTRIBUTING.md" in markdown
    assert "fabricated" not in markdown
    assert "Título traducido" not in markdown


def test_shortfall_explanation_is_saved_with_remaining_recommendations(tmp_path):
    folder = cache_inputs(tmp_path, count=3, reason="Only one issue met the search rules.")
    response = spanish_response()
    response["notice"] = (
        "Encontré 1 incidencia en lugar de 3: solo una cumplía las reglas de búsqueda. "
        "Inténtalo de nuevo más tarde."
    )
    asyncio.run(run_pipeline(
        ScriptedModel(response), [], username="octocat", output_root=tmp_path,
    ))
    markdown = (folder / "recommendations.md").read_text()
    assert "Encontré 1 incidencia en lugar de 3" in markdown
    assert "solo una cumplía las reglas" in markdown
    assert "Inténtalo de nuevo más tarde" in markdown
    assert markdown.count("## 1.") == 1


def test_no_issues_gives_localized_explanation_without_inventing_recommendations(tmp_path):
    folder = cache_inputs(tmp_path, issues=[], count=3)
    response = spanish_response()
    response["narratives"] = []
    response["notice"] = (
        "No encontré recomendaciones: 0 de 3 incidencias cumplieron las reglas. "
        "Inténtalo de nuevo más tarde."
    )
    result = asyncio.run(run_pipeline(
        ScriptedModel(response), [], username="octocat", output_root=tmp_path,
    ))
    assert result.recommendations == (
        "# Tus recomendaciones\n\nNo encontré recomendaciones: 0 de 3 incidencias "
        "cumplieron las reglas. Inténtalo de nuevo más tarde.\n"
    )
    assert (folder / "recommendations.md").read_text() == result.recommendations


def test_missing_narrative_does_not_save_partial_recommendations(tmp_path):
    folder = cache_inputs(tmp_path)
    response = spanish_response()
    response["narratives"] = []
    with pytest.raises(ValueError, match="one Recommendation per selected issue"):
        asyncio.run(run_pipeline(
            ScriptedModel(response), [], username="octocat", output_root=tmp_path,
        ))
    assert not (folder / "recommendations.md").exists()


def test_recommendations_are_reused_without_calling_model(tmp_path):
    folder = cache_inputs(tmp_path)
    asyncio.run(run_pipeline(
        ScriptedModel(spanish_response()), [], username="octocat", output_root=tmp_path,
    ))
    saved = (folder / "recommendations.md").read_text()
    result = asyncio.run(run_pipeline(
        None, [], username="octocat", output_root=tmp_path,
    ))
    assert result.recommendations == saved
    assert result.completed_stages == ["setup"]


def test_blank_first_step_is_not_saved_as_guidance(tmp_path):
    from pydantic import ValidationError

    folder = cache_inputs(tmp_path)
    response = spanish_response()
    response["narratives"][0]["first_steps"] = ["   "]
    with pytest.raises(ValidationError):
        asyncio.run(run_pipeline(
            ScriptedModel(response), [], username="octocat", output_root=tmp_path,
        ))
    assert not (folder / "recommendations.md").exists()
