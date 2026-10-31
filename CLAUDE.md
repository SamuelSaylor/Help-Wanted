# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Hack Day 2026 (Hacktoberfest Hack Day San Antonio, Oct 31, 2026) entry. A CLI that helps newcomers find open-source projects to contribute to. Entered in: **MLH Best Open-Source AI Project (Gemma 4)** and **OSPO Open Source Education**, plus Best Overall automatically.

Repo is currently empty (LICENSE, README only). Stack: Python, CLI. Libraries and how Gemma 4 runs (local, e.g. Ollama, vs API) are still undecided; don't assume either until this file says so.

## Planned pipeline

1. Questionnaire (15 questions, **every question is optional**; unanswered ones fall back to defaults). Mostly multiple choice, with a few free-text fields. Topics: optional GitHub username, years programming, Git/GitHub experience, past contributions, programming languages, spoken languages, industry/interests, contribution goal, time available, project popularity, contributor-count range, beginner-friendly only, recent-activity requirement, number of projects to recommend, whether to generate topic files.
2. Gemma writes `master.md` from the answers: all information the GitHub search needs. This is the search's input.
3. If the user opts in, Gemma also writes topic profiles (e.g. `Python.md`, `Engineering.md`) into a `Questionaire/` folder (spelling is intentional).
4. Scan GitHub using `master.md` (language, topic, stars, contributors, good-first-issue, recent activity).
5. Later stages are still being planned.

Free-text answers (interests) are where Gemma turns input into search keywords and profiles.

Gemma must be central to the work (judged on this), not a chat wrapper.

## Hackathon constraints

- Submissions close 4:00 PM on the day; live demo follows. Teams of up to 4.
- Public repo with an open-source license (MIT/Apache 2.0). README must state: what it does, how to run it, who built it, which Gemma 4 model is used, and credit any data/APIs.
- Work must be done on the day; say in the README what was built vs. reused.
- Judging: Gemma use, openness (clone-and-run), usefulness, execution; for Education: reach to non-contributors, beginner clarity without help, reusability.
- Target users are beginners (e.g. high schoolers, non-CS majors, first-gen students, non-English speakers), so keep setup and output simple.
