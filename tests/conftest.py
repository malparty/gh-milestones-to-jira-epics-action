"""Shared fixtures and fakes for the test suite."""

from __future__ import annotations

from gh_jira_sync.models import Issue, Milestone


def make_milestone(**kw: object) -> Milestone:
    defaults: dict[str, object] = {
        "number": 1,
        "title": "M1 · Brain extraction",
        "description": "Extract the brain.",
        "state": "open",
        "due_on": None,
    }
    defaults.update(kw)
    return Milestone(**defaults)  # type: ignore[arg-type]


def make_issue(**kw: object) -> Issue:
    defaults: dict[str, object] = {
        "number": 1,
        "title": "Do the thing",
        "state": "open",
        "closed_at": None,
    }
    defaults.update(kw)
    return Issue(**defaults)  # type: ignore[arg-type]
