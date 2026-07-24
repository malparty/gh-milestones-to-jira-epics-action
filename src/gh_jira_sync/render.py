"""Pure rendering: summary, labels, ADF description, due date. No I/O.

Everything here is a deterministic function of its inputs so it can be
golden-file tested against fixtures.
"""

from __future__ import annotations

import json
from typing import Any

from .models import Issue, Milestone

Adf = dict[str, Any]

NOTICE_PREFIX = "Epic sync from "
NOTICE_SUFFIX = ". Do NOT edit in Jira!"


def structural_label(number: int) -> str:
    """The per-milestone idempotency key label."""
    return f"gh-ms-{number}"


def render_summary(milestone: Milestone) -> str:
    """Epic summary: the milestone title verbatim (no prefix)."""
    return milestone.title


def render_labels(number: int, extra_labels: list[str]) -> list[str]:
    """The label set applied to an epic: structural key first, then extras (deduped)."""
    labels = [structural_label(number)]
    for label in extra_labels:
        if label not in labels:
            labels.append(label)
    return labels


def render_due_date(milestone: Milestone) -> str | None:
    """``YYYY-MM-DD`` if the milestone has a due date, else ``None`` (omit the key)."""
    return milestone.due_date


# --- tiny ADF builder ---------------------------------------------------------


def _text(value: str, marks: list[Adf] | None = None) -> Adf:
    node: Adf = {"type": "text", "text": value}
    if marks:
        node["marks"] = marks
    return node


def _paragraph(content: list[Adf]) -> Adf:
    return {"type": "paragraph", "content": content}


def _heading(text: str, level: int = 3) -> Adf:
    return {"type": "heading", "attrs": {"level": level}, "content": [_text(text)]}


def _bullet_list(items: list[str]) -> Adf:
    return {
        "type": "bulletList",
        "content": [
            {"type": "listItem", "content": [_paragraph([_text(item)])]} for item in items
        ],
    }


def _notice_paragraph(owner: str, repo: str) -> Adf:
    em = {"type": "em"}
    link = {
        "type": "link",
        "attrs": {"href": f"https://github.com/{owner}/{repo}/milestones"},
    }
    return _paragraph(
        [
            _text(NOTICE_PREFIX, [em]),
            _text("GitHub", [em, link]),
            _text(NOTICE_SUFFIX, [em]),
        ]
    )


def render_description(milestone: Milestone, issues: list[Issue], owner: str, repo: str) -> Adf:
    """Build the ADF description document (§6.4).

    Order: italic notice → ``closed/total`` heading → milestone description →
    Open issues list → Closed issues list. Empty sections are omitted.
    """
    ordered = sorted(issues, key=lambda i: i.number)
    open_issues = [i for i in ordered if i.state != "closed"]
    closed_issues = [i for i in ordered if i.state == "closed"]
    total = len(ordered)
    closed = len(closed_issues)

    content: list[Adf] = [
        _notice_paragraph(owner, repo),
        _heading(f"{closed}/{total} issues closed"),
    ]

    if milestone.description and milestone.description.strip():
        content.append(_paragraph([_text(milestone.description.strip())]))

    if open_issues:
        content.append(_heading("Open issues"))
        content.append(_bullet_list([f"#{i.number} {i.title}" for i in open_issues]))

    if closed_issues:
        content.append(_heading("Closed issues"))
        content.append(
            _bullet_list(
                [f"#{i.number} {i.title} — closed {i.closed_date}" for i in closed_issues]
            )
        )

    return {"type": "doc", "version": 1, "content": content}


def canonical(adf: Adf | None) -> str:
    """Canonical JSON serialization used for change detection (§6.5)."""
    return json.dumps(adf, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
