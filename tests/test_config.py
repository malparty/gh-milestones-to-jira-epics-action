"""Config parsing and validation."""

from __future__ import annotations

import pytest

from gh_jira_sync.config import ConfigError, load_config, parse_extra_labels

_REQUIRED = {
    "INPUT_JIRA_BASE_URL": "https://x.atlassian.net/",
    "INPUT_JIRA_EMAIL": "a@b.co",
    "INPUT_JIRA_API_TOKEN": "tok",
    "INPUT_JIRA_PROJECT_KEY": "RD",
    "INPUT_JIRA_EPIC_ISSUE_TYPE_ID": "11087",
    "INPUT_GITHUB_TOKEN": "ghtok",
    "GITHUB_REPOSITORY": "malparty/demo",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    for key in list(overrides) + list(_REQUIRED):
        monkeypatch.delenv(key, raising=False)
    for key, value in {**_REQUIRED, **overrides}.items():
        monkeypatch.setenv(key, value)


def test_parse_extra_labels_trims_and_dedupes() -> None:
    assert parse_extra_labels(" a, b ,a,, c ") == ["a", "b", "c"]


def test_parse_extra_labels_rejects_spaces() -> None:
    with pytest.raises(ConfigError):
        parse_extra_labels("has space")


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


def test_bad_repo_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, GITHUB_REPOSITORY="noslash")
    with pytest.raises(ConfigError, match="GITHUB_REPOSITORY"):
        load_config([])
