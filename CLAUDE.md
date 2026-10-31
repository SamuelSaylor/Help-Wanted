# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Hack Day 2026 (Hacktoberfest Hack Day San Antonio, Oct 31, 2026) entry. A CLI that helps newcomers find open-source projects to contribute to. Entered in: **MLH Best Open-Source AI Project (Gemma 4)** and **OSPO Open Source Education**, plus Best Overall automatically.

Repo is currently empty (LICENSE, README only). Stack: Python, CLI. Libraries and how Gemma 4 runs (local, e.g. Ollama, vs API) are still undecided; don't assume either until this file says so.

## Planned pipeline

1. Questionnaire: programming familiarity, interests, prior contributions.
2. Generate a profile markdown file from the answers. If the user opts in, also generate topic files (e.g. `Python.md`, `Engineering.md`).
3. Scan GitHub for projects matching the profile.
4. Later stages are still being planned.

Gemma must be central to the work (judged on this), not a chat wrapper.

## Hackathon constraints

- Submissions close 4:00 PM on the day; live demo follows. Teams of up to 4.
- Public repo with an open-source license (MIT/Apache 2.0). README must state: what it does, how to run it, who built it, which Gemma 4 model is used, and credit any data/APIs.
- Work must be done on the day; say in the README what was built vs. reused.
- Judging: Gemma use, openness (clone-and-run), usefulness, execution; for Education: reach to non-contributors, beginner clarity without help, reusability.
- Target users are beginners (e.g. high schoolers, non-CS majors, first-gen students, non-English speakers), so keep setup and output simple.
