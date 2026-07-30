"""Upsert orchestration — the §7 algorithm, change detection and reconciliation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from . import render
from .config import Config
from .fetch import GitHubClient
from .jira import JiraClient, JiraIssue, Transition
from .models import Milestone

Json = dict[str, Any]
Logger = Callable[[str], None]

STORY_TYPE_NAME = "Story"


@dataclass(frozen=True)
class Target:
    """What a milestone is mirrored *as* — resolved once per run.

    Epic mode (the default): an epic per milestone, no parent. Stories mode
    (``stories-inside-epic-id``): a story per milestone, parented to that epic.
    """

    issue_type_id: str
    parent_key: str | None
    noun: str  # "epic" | "story" — for log lines only


def resolve_target(cfg: Config, jira: JiraClient, log: Logger) -> Target:
    """Pick the issue type (and parent) to create, failing fast if unusable.

    Both lookups are reads, so they also run under ``--dry-run``: a bad parent key
    or a project without a Story type is reported before the first milestone.
    """
    if cfg.stories_inside_epic is None:
        return Target(cfg.jira_epic_issue_type_id, None, "epic")

    issue_type_id = cfg.jira_story_issue_type_id or jira.resolve_issue_type_id(
        cfg.jira_project_key, STORY_TYPE_NAME
    )
    log(
        f"stories mode: creating stories (issue type {issue_type_id}) under parent "
        f"{jira.describe_issue(cfg.stories_inside_epic)}"
    )
    return Target(issue_type_id, cfg.stories_inside_epic, "story")


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    failed: int = 0
    messages: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 1 if (self.failed or self.skipped) else 0


def compute_field_updates(
    issue: JiraIssue,
    *,
    summary: str,
    description: render.Adf,
    duedate: str | None,
    labels: list[str],
) -> Json:
    """Fields that actually differ and must be PUT (§6.5).

    - summary / description: sent when they differ.
    - duedate: sent only when the target has one and it differs — never cleared (§2.7).
    - labels: superset merge; sent only when the issue is missing some (never pruned, §6.2).
    """
    updates: Json = {}
    if issue.summary != summary:
        updates["summary"] = summary
    if render.canonical(issue.description) != render.canonical(description):
        updates["description"] = description
    if duedate is not None and issue.duedate != duedate:
        updates["duedate"] = duedate

    missing = [label for label in labels if label not in issue.labels]
    if missing:
        updates["labels"] = issue.labels + missing
    return updates


def plan_status_transition(
    milestone_state: str,
    current_category: str,
    transitions: list[Transition],
) -> Transition | None:
    """Decide the transition to apply, honouring manual in-progress states (§2.6).

    Matches by ``to.statusCategory`` (``done``/``new``) rather than literal name,
    so it survives status renames and non-English projects (§10).
    """

    def by_category(target: str) -> Transition | None:
        return next((t for t in transitions if t.to_category == target), None)

    if milestone_state == "closed":
        if current_category != "done":
            return by_category("done")
        return None
    # milestone open
    if current_category == "done":
        return by_category("new")
    return None


def _sync_one(
    milestone: Milestone,
    cfg: Config,
    gh: GitHubClient,
    jira: JiraClient,
    result: SyncResult,
    log: Logger,
    today: date,
    target: Target,
) -> None:
    issues = gh.fetch_issues(milestone.number)
    summary = render.render_summary(milestone)
    labels = render.render_labels(milestone.number, cfg.jira_extra_labels)
    description = render.render_description(milestone, issues, cfg.owner, cfg.repo)
    duedate = render.render_due_date(milestone)
    label = render.structural_label(milestone.number)

    existing = jira.find_issues_by_label(cfg.jira_project_key, label, target.issue_type_id)

    if len(existing) > 1:
        keys = ", ".join(e.key for e in existing)
        msg = (
            f"milestone #{milestone.number} {milestone.title!r}: "
            f"{len(existing)} {target.noun}s carry label {label} ({keys}); "
            "skipping to avoid guessing."
        )
        log(f"ERROR {msg}")
        result.skipped += 1
        result.messages.append(msg)
        return

    if not existing:
        # Creation only: a milestone with no due date gets the configured fallback
        # (§2.7 — later runs never write or rewrite a due date from the fallback).
        create_duedate = duedate
        origin = ""
        if create_duedate is None:
            create_duedate = render.fallback_due_date(cfg.default_due_in_days, today)
            if create_duedate is not None:
                origin = f" (default +{cfg.default_due_in_days}d)"
        parent = f" parent={target.parent_key}" if target.parent_key else ""
        if cfg.dry_run:
            log(
                f"[dry-run] would CREATE {target.noun} for milestone #{milestone.number} "
                f"{summary!r} labels={labels} duedate={create_duedate}{origin}{parent}"
            )
        else:
            key = jira.create_issue(
                cfg.jira_project_key,
                target.issue_type_id,
                summary=summary,
                description=description,
                labels=labels,
                duedate=create_duedate,
                parent_key=target.parent_key,
            )
            log(
                f"created {target.noun} {key} for milestone #{milestone.number} {summary!r}"
                + (f" duedate={create_duedate}{origin}" if origin else "")
                + parent
            )
            if milestone.state == "closed":
                _apply_status(jira, key, milestone.state, "new", cfg, log)
        result.created += 1
        return

    issue = existing[0]
    updates = compute_field_updates(
        issue,
        summary=summary,
        description=description,
        duedate=duedate,
        labels=labels,
    )
    # Transitions are always queried (even in dry-run) so reporting is faithful.
    transition = plan_status_transition(
        milestone.state, issue.status_category, jira.get_transitions(issue.key)
    )

    changed = False
    if updates:
        changed = True
        fields_changed = ", ".join(sorted(updates))
        if cfg.dry_run:
            log(f"[dry-run] would UPDATE {issue.key} fields: {fields_changed}")
        else:
            jira.update_fields(issue.key, updates)
            log(f"updated {issue.key} fields: {fields_changed}")

    if transition is not None:
        changed = True
        if cfg.dry_run:
            log(
                f"[dry-run] would TRANSITION {issue.key} → "
                f"{transition.name} ({transition.to_category})"
            )
        else:
            jira.transition(issue.key, transition.id)
            log(f"transitioned {issue.key} → {transition.name} ({transition.to_category})")

    if changed:
        result.updated += 1
    else:
        result.unchanged += 1
        log(f"unchanged {issue.key} (milestone #{milestone.number})")


def _apply_status(
    jira: JiraClient,
    key: str,
    milestone_state: str,
    current_category: str,
    cfg: Config,
    log: Logger,
) -> None:
    transition = plan_status_transition(
        milestone_state, current_category, jira.get_transitions(key)
    )
    if transition is not None:
        jira.transition(key, transition.id)
        log(f"transitioned {key} → {transition.name} ({transition.to_category})")


def sync(
    cfg: Config,
    gh: GitHubClient,
    jira: JiraClient,
    log: Logger,
    today: date | None = None,
) -> SyncResult:
    """Run the full upsert pass and return counts (§7).

    ``today`` (UTC date, read once so every milestone in a pass shares it) anchors
    the ``default-due-in-days`` fallback; injectable for deterministic tests.
    """
    result = SyncResult()
    today = today if today is not None else datetime.now(UTC).date()
    log(f"authenticated to Jira as {jira.verify_auth()}")
    target = resolve_target(cfg, jira, log)
    milestones = gh.fetch_milestones()
    if cfg.only is not None:
        milestones = [m for m in milestones if m.number == cfg.only]
        if not milestones:
            log(f"no milestone with number {cfg.only}; nothing to do")

    for milestone in milestones:
        try:
            _sync_one(milestone, cfg, gh, jira, result, log, today, target)
        except Exception as exc:  # continue other milestones (§10)
            msg = f"milestone #{milestone.number} {milestone.title!r} failed: {exc}"
            log(f"ERROR {msg}")
            result.failed += 1
            result.messages.append(msg)

    log(
        f"done: created={result.created} updated={result.updated} "
        f"unchanged={result.unchanged} skipped={result.skipped} failed={result.failed}"
    )
    return result
