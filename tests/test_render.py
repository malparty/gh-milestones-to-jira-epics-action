"""Rendering tests, including golden-file ADF (the rendering contract)."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from conftest import make_issue, make_milestone

from gh_jira_sync import render

GOLDEN = Path(__file__).parent / "golden"


def _check_golden(name: str, doc: object) -> None:
    path = GOLDEN / name
    actual = json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_GOLDEN"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == actual


def test_summary_is_title_verbatim() -> None:
    assert render.render_summary(make_milestone(title="M1 · Brain extraction")) == "M1 · Brain extraction"


def test_labels_structural_first_then_extras_deduped() -> None:
    assert render.render_labels(4, ["a", "b", "a", "gh-ms-4"]) == ["gh-ms-4", "a", "b"]


def test_labels_only_structural_when_no_extras() -> None:
    assert render.render_labels(7, []) == ["gh-ms-7"]


def test_due_date_takes_date_part() -> None:
    assert render.render_due_date(make_milestone(due_on="2026-08-01T00:00:00Z")) == "2026-08-01"


def test_due_date_none_when_absent() -> None:
    assert render.render_due_date(make_milestone(due_on=None)) is None


def test_fallback_due_date_adds_days() -> None:
    assert render.fallback_due_date(30, date(2026, 7, 29)) == "2026-08-28"


def test_fallback_due_date_zero_days_is_today() -> None:
    assert render.fallback_due_date(0, date(2026, 7, 29)) == "2026-07-29"


def test_fallback_due_date_none_when_disabled() -> None:
    assert render.fallback_due_date(None, date(2026, 7, 29)) is None


def test_description_golden_full() -> None:
    milestone = make_milestone(
        number=4,
        title="M4 · Ship it",
        description="Deliver the release.",
        state="open",
        due_on="2026-09-01T00:00:00Z",
    )
    issues = [
        make_issue(number=12, title="Wire the pipeline", state="open"),
        make_issue(number=3, title="Scaffold repo", state="closed", closed_at="2026-07-20T10:00:00Z"),
        make_issue(number=8, title="Write docs", state="open"),
    ]
    doc = render.render_description(milestone, issues, "malparty", "demo")
    _check_golden("description_full.json", doc)


def test_description_golden_empty() -> None:
    milestone = make_milestone(number=1, title="Empty", description=None, state="open")
    doc = render.render_description(milestone, [], "malparty", "demo")
    _check_golden("description_empty.json", doc)


def test_description_omits_empty_milestone_description() -> None:
    doc = render.render_description(make_milestone(description="   "), [], "o", "r")
    headings = [n for n in doc["content"] if n["type"] == "heading"]
    paragraphs = [n for n in doc["content"] if n["type"] == "paragraph"]
    # only the notice paragraph remains (no milestone-description paragraph)
    assert len(paragraphs) == 1
    assert headings[0]["content"][0]["text"] == "0/0 issues closed"


def test_counts_and_lists_agree() -> None:
    issues = [
        make_issue(number=1, state="closed", closed_at="2026-01-01T00:00:00Z"),
        make_issue(number=2, state="open"),
    ]
    doc = render.render_description(make_milestone(), issues, "o", "r")
    heading = next(n for n in doc["content"] if n["type"] == "heading")
    assert heading["content"][0]["text"] == "1/2 issues closed"


def test_canonical_stable_regardless_of_key_order() -> None:
    a = {"type": "doc", "version": 1, "content": []}
    b = {"content": [], "version": 1, "type": "doc"}
    assert render.canonical(a) == render.canonical(b)
