"""Sync orchestration: change detection, status planning, upsert loop."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from conftest import make_issue, make_milestone

from gh_jira_sync import render
from gh_jira_sync.config import Config
from gh_jira_sync.jira import Epic, Transition
from gh_jira_sync.models import Milestone
from gh_jira_sync.sync import compute_field_updates, plan_status_transition, sync


def _cfg(**kw: object) -> Config:
    defaults: dict[str, object] = {
        "jira_base_url": "https://x.atlassian.net",
        "jira_email": "a@b.co",
        "jira_api_token": "tok",
        "jira_project_key": "RD",
        "jira_epic_issue_type_id": "11087",
        "jira_extra_labels": ["mc-assistant"],
        "default_due_in_days": None,
        "github_token": "gh",
        "github_repository": "malparty/demo",
        "only": None,
        "dry_run": False,
        "verbose": False,
    }
    defaults.update(kw)
    return Config(**defaults)  # type: ignore[arg-type]


def _epic_for(milestone: Milestone, cfg: Config, **overrides: object) -> Epic:
    """An epic whose fields already match the rendered target (a no-op baseline)."""
    labels = render.render_labels(milestone.number, cfg.jira_extra_labels)
    desc = render.render_description(milestone, [], cfg.owner, cfg.repo)
    base = Epic(
        key="RD-1",
        summary=render.render_summary(milestone),
        description=desc,
        duedate=render.render_due_date(milestone),
        labels=labels,
        status_category="new",
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


# --- pure helpers -------------------------------------------------------------


def test_compute_updates_empty_when_identical() -> None:
    cfg = _cfg()
    m = make_milestone(description=None)
    epic = _epic_for(m, cfg)
    updates = compute_field_updates(
        epic,
        summary=render.render_summary(m),
        description=render.render_description(m, [], cfg.owner, cfg.repo),
        duedate=render.render_due_date(m),
        labels=render.render_labels(m.number, cfg.jira_extra_labels),
    )
    assert updates == {}


def test_compute_updates_never_clears_duedate() -> None:
    cfg = _cfg()
    m = make_milestone(description=None, due_on=None)
    epic = _epic_for(m, cfg, duedate="2026-08-01")  # human-set in Jira
    updates = compute_field_updates(
        epic,
        summary=epic.summary,
        description=epic.description or {},
        duedate=None,
        labels=epic.labels,
    )
    assert "duedate" not in updates


def test_compute_updates_labels_superset_never_prunes() -> None:
    cfg = _cfg()
    m = make_milestone(description=None)
    epic = _epic_for(m, cfg, labels=["gh-ms-1", "human-added"])  # missing mc-assistant
    updates = compute_field_updates(
        epic,
        summary=epic.summary,
        description=epic.description or {},
        duedate=None,
        labels=["gh-ms-1", "mc-assistant"],
    )
    assert updates["labels"] == ["gh-ms-1", "human-added", "mc-assistant"]


def _transitions() -> list[Transition]:
    return [
        Transition(id="31", name="Done", to_category="done"),
        Transition(id="11", name="To Do", to_category="new"),
    ]


def test_status_closed_moves_to_done() -> None:
    t = plan_status_transition("closed", "new", _transitions())
    assert t is not None and t.to_category == "done"


def test_status_closed_already_done_noop() -> None:
    assert plan_status_transition("closed", "done", _transitions()) is None


def test_status_open_but_done_reopens() -> None:
    t = plan_status_transition("open", "done", _transitions())
    assert t is not None and t.to_category == "new"


def test_status_open_in_progress_left_alone() -> None:
    assert plan_status_transition("open", "indeterminate", _transitions()) is None


# --- fakes + end-to-end -------------------------------------------------------


class FakeGitHub:
    def __init__(self, milestones: list[Milestone], issues: dict[int, list]) -> None:
        self._milestones = milestones
        self._issues = issues

    def fetch_milestones(self, state: str = "all") -> list[Milestone]:
        return self._milestones

    def fetch_issues(self, number: int, state: str = "all") -> list:
        return self._issues.get(number, [])


class FakeJira:
    def __init__(self, epics: dict[str, list[Epic]], transitions: list[Transition] | None = None) -> None:
        self._epics = epics
        self._transitions = transitions or _transitions()
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []
        self.transitioned: list[tuple[str, str]] = []

    def verify_auth(self) -> str:
        return "test@example.com"

    def find_epics_by_label(self, project_key: str, label: str) -> list[Epic]:
        return self._epics.get(label, [])

    def get_transitions(self, key: str) -> list[Transition]:
        return self._transitions

    def create_epic(self, project_key, epic_issue_type_id, **fields) -> str:
        self.created.append(fields)
        return "RD-NEW"

    def update_fields(self, key: str, fields: dict) -> None:
        self.updated.append((key, fields))

    def transition(self, key: str, transition_id: str) -> None:
        self.transitioned.append((key, transition_id))


_TODAY = date(2026, 7, 29)


def _run(cfg: Config, gh: FakeGitHub, jira: FakeJira):
    logs: list[str] = []
    result = sync(cfg, gh, jira, logs.append, today=_TODAY)  # type: ignore[arg-type]
    return result, logs


def test_creates_new_epic() -> None:
    cfg = _cfg()
    m = make_milestone(number=2, state="open", description=None)
    gh = FakeGitHub([m], {2: []})
    jira = FakeJira({})
    result, _ = _run(cfg, gh, jira)
    assert result.created == 1
    assert jira.created[0]["labels"] == ["gh-ms-2", "mc-assistant"]


def test_new_closed_milestone_transitions_to_done() -> None:
    cfg = _cfg()
    m = make_milestone(number=2, state="closed", description=None)
    gh = FakeGitHub([m], {2: []})
    jira = FakeJira({})
    _run(cfg, gh, jira)
    assert jira.transitioned == [("RD-NEW", "31")]


def test_unchanged_is_noop() -> None:
    cfg = _cfg()
    m = make_milestone(number=1, state="open", description=None)
    epic = _epic_for(m, cfg)
    gh = FakeGitHub([m], {1: []})
    jira = FakeJira({"gh-ms-1": [epic]})
    result, _ = _run(cfg, gh, jira)
    assert (result.unchanged, result.updated) == (1, 0)
    assert jira.updated == []


def test_updates_changed_description() -> None:
    cfg = _cfg()
    m = make_milestone(number=1, state="open", description="new text")
    epic = _epic_for(make_milestone(number=1, description="old text"), cfg)
    gh = FakeGitHub([m], {1: [make_issue(number=1, state="open")]})
    jira = FakeJira({"gh-ms-1": [epic]})
    result, _ = _run(cfg, gh, jira)
    assert result.updated == 1
    assert "description" in jira.updated[0][1]


def test_duplicate_label_skips() -> None:
    cfg = _cfg()
    m = make_milestone(number=1, description=None)
    e1 = _epic_for(m, cfg)
    e2 = replace(e1, key="RD-2")
    gh = FakeGitHub([m], {1: []})
    jira = FakeJira({"gh-ms-1": [e1, e2]})
    result, _ = _run(cfg, gh, jira)
    assert result.skipped == 1
    assert result.exit_code == 1


def test_dry_run_writes_nothing() -> None:
    cfg = _cfg(dry_run=True)
    m = make_milestone(number=2, state="open", description=None)
    gh = FakeGitHub([m], {2: []})
    jira = FakeJira({})
    result, logs = _run(cfg, gh, jira)
    assert result.created == 1
    assert jira.created == []
    assert any("would CREATE" in line for line in logs)


# --- default due date (create-only fallback) ----------------------------------


def test_create_uses_default_due_when_milestone_has_none() -> None:
    cfg = _cfg(default_due_in_days=30)
    m = make_milestone(number=2, description=None, due_on=None)
    gh = FakeGitHub([m], {2: []})
    jira = FakeJira({})
    _run(cfg, gh, jira)
    assert jira.created[0]["duedate"] == "2026-08-28"  # 2026-07-29 + 30d


def test_create_prefers_github_due_over_default() -> None:
    cfg = _cfg(default_due_in_days=30)
    m = make_milestone(number=2, description=None, due_on="2026-09-01T00:00:00Z")
    gh = FakeGitHub([m], {2: []})
    jira = FakeJira({})
    _run(cfg, gh, jira)
    assert jira.created[0]["duedate"] == "2026-09-01"


def test_create_omits_due_when_default_disabled() -> None:
    cfg = _cfg(default_due_in_days=None)
    m = make_milestone(number=2, description=None, due_on=None)
    gh = FakeGitHub([m], {2: []})
    jira = FakeJira({})
    _run(cfg, gh, jira)
    assert jira.created[0]["duedate"] is None


def test_default_due_not_applied_on_update() -> None:
    """An existing epic is never given (or re-dated with) the fallback."""
    cfg = _cfg(default_due_in_days=30)
    m = make_milestone(number=1, description=None, due_on=None)
    epic = _epic_for(m, cfg, duedate=None)
    gh = FakeGitHub([m], {1: []})
    jira = FakeJira({"gh-ms-1": [epic]})
    result, _ = _run(cfg, gh, jira)
    assert (result.unchanged, jira.updated) == (1, [])


def test_dry_run_reports_default_due_origin() -> None:
    cfg = _cfg(default_due_in_days=30, dry_run=True)
    m = make_milestone(number=2, description=None, due_on=None)
    gh = FakeGitHub([m], {2: []})
    jira = FakeJira({})
    _, logs = _run(cfg, gh, jira)
    assert any("duedate=2026-08-28 (default +30d)" in line for line in logs)


def test_only_filters_milestones() -> None:
    cfg = _cfg(only=2)
    m1 = make_milestone(number=1, description=None)
    m2 = make_milestone(number=2, description=None)
    gh = FakeGitHub([m1, m2], {1: [], 2: []})
    jira = FakeJira({})
    result, _ = _run(cfg, gh, jira)
    assert result.created == 1
    assert jira.created[0]["labels"][0] == "gh-ms-2"
