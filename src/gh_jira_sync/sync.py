"""Upsert orchestration — the §7 algorithm, change detection and reconciliation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import render
from .config import Config
from .fetch import GitHubClient
from .jira import Epic, JiraClient, Transition
from .models import Milestone

Json = dict[str, Any]
Logger = Callable[[str], None]


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
    epic: Epic,
    *,
    summary: str,
    description: render.Adf,
    duedate: str | None,
    labels: list[str],
) -> Json:
    """Fields that actually differ and must be PUT (§6.5).

    - summary / description: sent when they differ.
    - duedate: sent only when the target has one and it differs — never cleared (§2.7).
    - labels: superset merge; sent only when the epic is missing some (never pruned, §6.2).
    """
    updates: Json = {}
    if epic.summary != summary:
        updates["summary"] = summary
    if render.canonical(epic.description) != render.canonical(description):
        updates["description"] = description
    if duedate is not None and epic.duedate != duedate:
        updates["duedate"] = duedate

    missing = [label for label in labels if label not in epic.labels]
    if missing:
        updates["labels"] = epic.labels + missing
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
) -> None:
    issues = gh.fetch_issues(milestone.number)
    summary = render.render_summary(milestone)
    labels = render.render_labels(milestone.number, cfg.jira_extra_labels)
    description = render.render_description(milestone, issues, cfg.owner, cfg.repo)
    duedate = render.render_due_date(milestone)
    label = render.structural_label(milestone.number)

    epics = jira.find_epics_by_label(cfg.jira_project_key, label)

    if len(epics) > 1:
        keys = ", ".join(e.key for e in epics)
        msg = (
            f"milestone #{milestone.number} {milestone.title!r}: "
            f"{len(epics)} epics carry label {label} ({keys}); skipping to avoid guessing."
        )
        log(f"ERROR {msg}")
        result.skipped += 1
        result.messages.append(msg)
        return

    if not epics:
        if cfg.dry_run:
            log(
                f"[dry-run] would CREATE epic for milestone #{milestone.number} "
                f"{summary!r} labels={labels} duedate={duedate}"
            )
        else:
            key = jira.create_epic(
                cfg.jira_project_key,
                cfg.jira_epic_issue_type_id,
                summary=summary,
                description=description,
                labels=labels,
                duedate=duedate,
            )
            log(f"created {key} for milestone #{milestone.number} {summary!r}")
            if milestone.state == "closed":
                _apply_status(jira, key, milestone.state, "new", cfg, log)
        result.created += 1
        return

    epic = epics[0]
    updates = compute_field_updates(
        epic,
        summary=summary,
        description=description,
        duedate=duedate,
        labels=labels,
    )
    # Transitions are always queried (even in dry-run) so reporting is faithful.
    transition = plan_status_transition(
        milestone.state, epic.status_category, jira.get_transitions(epic.key)
    )

    changed = False
    if updates:
        changed = True
        fields_changed = ", ".join(sorted(updates))
        if cfg.dry_run:
            log(f"[dry-run] would UPDATE {epic.key} fields: {fields_changed}")
        else:
            jira.update_fields(epic.key, updates)
            log(f"updated {epic.key} fields: {fields_changed}")

    if transition is not None:
        changed = True
        if cfg.dry_run:
            log(
                f"[dry-run] would TRANSITION {epic.key} → "
                f"{transition.name} ({transition.to_category})"
            )
        else:
            jira.transition(epic.key, transition.id)
            log(f"transitioned {epic.key} → {transition.name} ({transition.to_category})")

    if changed:
        result.updated += 1
    else:
        result.unchanged += 1
        log(f"unchanged {epic.key} (milestone #{milestone.number})")


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


def sync(cfg: Config, gh: GitHubClient, jira: JiraClient, log: Logger) -> SyncResult:
    """Run the full upsert pass and return counts (§7)."""
    result = SyncResult()
    milestones = gh.fetch_milestones()
    if cfg.only is not None:
        milestones = [m for m in milestones if m.number == cfg.only]
        if not milestones:
            log(f"no milestone with number {cfg.only}; nothing to do")

    for milestone in milestones:
        try:
            _sync_one(milestone, cfg, gh, jira, result, log)
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
