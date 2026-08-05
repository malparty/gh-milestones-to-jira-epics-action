"""Config parsing and validation."""

from __future__ import annotations

import pytest

from gh_jira_sync.config import (
    ConfigError,
    load_config,
    parse_default_due_in_days,
    parse_extra_labels,
    parse_stories_inside_epic_id,
)

_REQUIRED = {
    "INPUT_JIRA_BASE_URL": "https://x.atlassian.net/",
    "INPUT_JIRA_EMAIL": "a@b.co",
    "INPUT_JIRA_API_TOKEN": "tok",
    "INPUT_JIRA_PROJECT_KEY": "RD",
    "INPUT_JIRA_EPIC_ISSUE_TYPE_ID": "11087",
    "INPUT_GITHUB_TOKEN": "ghtok",
    "GITHUB_REPOSITORY": "malparty/demo",
}


_OPTIONAL = [
    "INPUT_JIRA_EXTRA_LABELS",
    "INPUT_DEFAULT_DUE_IN_DAYS",
    "INPUT_STORIES_INSIDE_EPIC_ID",
    "INPUT_JIRA_STORY_ISSUE_TYPE_ID",
    "INPUT_GITHUB_REPOSITORY",
    "INPUT_ONLY",
    "INPUT_DRY_RUN",
    "INPUT_VERBOSE",
]


def _set_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    # Optional inputs are cleared too, so an ambient INPUT_* in the dev's shell
    # (or a .env-driven run) can't change what a test is asserting.
    for key in list(overrides) + list(_REQUIRED) + _OPTIONAL:
        monkeypatch.delenv(key, raising=False)
    for key, value in {**_REQUIRED, **overrides}.items():
        monkeypatch.setenv(key, value)


def test_parse_extra_labels_trims_and_dedupes() -> None:
    assert parse_extra_labels(" a, b ,a,, c ") == ["a", "b", "c"]


def test_parse_extra_labels_rejects_spaces() -> None:
    with pytest.raises(ConfigError):
        parse_extra_labels("has space")


def test_parse_default_due_in_days() -> None:
    assert parse_default_due_in_days("") is None
    assert parse_default_due_in_days("30") == 30
    assert parse_default_due_in_days("0") == 0


@pytest.mark.parametrize("raw", ["-1", "abc", "30.5"])
def test_parse_default_due_in_days_rejects_invalid(raw: str) -> None:
    with pytest.raises(ConfigError, match="default-due-in-days"):
        parse_default_due_in_days(raw)


def test_default_due_in_days_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, INPUT_DEFAULT_DUE_IN_DAYS="30")
    assert load_config([]).default_due_in_days == 30


def test_default_due_in_days_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, INPUT_DEFAULT_DUE_IN_DAYS="30")
    assert load_config(["--default-due-in-days", "7"]).default_due_in_days == 7
    assert load_config(["--default-due-in-days=14"]).default_due_in_days == 14
    assert load_config(["--default-due-in-days="]).default_due_in_days is None


def test_load_config_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, INPUT_JIRA_EXTRA_LABELS="mc-assistant,github-auto-sync")
    cfg = load_config([])
    assert cfg.jira_base_url == "https://x.atlassian.net"  # trailing slash stripped
    assert cfg.owner == "malparty"
    assert cfg.repo == "demo"
    assert cfg.jira_extra_labels == ["mc-assistant", "github-auto-sync"]
    assert cfg.dry_run is False


def test_missing_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    monkeypatch.delenv("INPUT_JIRA_API_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="jira-api-token"):
        load_config([])


def test_cli_flags_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, INPUT_DRY_RUN="false")
    cfg = load_config(["--dry-run", "--verbose", "--only", "5"])
    assert cfg.dry_run is True
    assert cfg.verbose is True
    assert cfg.only == 5


def test_no_dry_run_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, INPUT_DRY_RUN="true")
    assert load_config([]).dry_run is True
    assert load_config(["--no-dry-run"]).dry_run is False
    assert load_config(["--write"]).dry_run is False


def test_only_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, INPUT_ONLY="3")
    assert load_config([]).only == 3


def test_parse_stories_inside_epic_id_accepts_key_number_and_url() -> None:
    assert parse_stories_inside_epic_id("", "RD") is None
    assert parse_stories_inside_epic_id("RD-16", "RD") == "RD-16"
    assert parse_stories_inside_epic_id(" rd-16 ", "rd") == "RD-16"
    assert parse_stories_inside_epic_id("16", "RD") == "RD-16"
    assert (
        parse_stories_inside_epic_id(
            "https://rivrs.atlassian.net/jira/software/projects/RD/boards/847/"
            "timeline?selectedIssue=RD-16",
            "RD",
        )
        == "RD-16"
    )


def test_parse_stories_inside_epic_id_rejects_other_project() -> None:
    with pytest.raises(ConfigError, match="same project"):
        parse_stories_inside_epic_id("XY-16", "RD")


def test_parse_stories_inside_epic_id_rejects_garbage() -> None:
    with pytest.raises(ConfigError, match="stories-inside-epic-id"):
        parse_stories_inside_epic_id("epic sixteen", "RD")


def test_stories_mode_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, INPUT_STORIES_INSIDE_EPIC_ID="16")
    cfg = load_config([])
    assert (cfg.stories_inside_epic, cfg.stories_mode) == ("RD-16", True)
    assert cfg.jira_story_issue_type_id == ""  # resolved at run time


def test_stories_mode_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, INPUT_STORIES_INSIDE_EPIC_ID="16")
    assert load_config(["--stories-inside-epic-id", "RD-20"]).stories_inside_epic == "RD-20"
    assert load_config(["--stories-inside-epic-id=RD-21"]).stories_inside_epic == "RD-21"
    assert load_config(["--stories-inside-epic-id="]).stories_inside_epic is None


def test_epic_type_id_required_only_in_epic_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    monkeypatch.delenv("INPUT_JIRA_EPIC_ISSUE_TYPE_ID", raising=False)
    with pytest.raises(ConfigError, match="jira-epic-issue-type-id"):
        load_config([])
    monkeypatch.setenv("INPUT_STORIES_INSIDE_EPIC_ID", "RD-16")
    assert load_config([]).stories_mode is True


def test_default_epic_mode_has_no_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    cfg = load_config([])
    assert (cfg.stories_inside_epic, cfg.stories_mode) == (None, False)


def test_bad_repo_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, GITHUB_REPOSITORY="noslash")
    with pytest.raises(ConfigError, match="GITHUB_REPOSITORY"):
        load_config([])


def test_github_repository_input_overrides_ambient_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, INPUT_GITHUB_REPOSITORY="other-org/other-repo")
    cfg = load_config([])
    assert (cfg.owner, cfg.repo) == ("other-org", "other-repo")
