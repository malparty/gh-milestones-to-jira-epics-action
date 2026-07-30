"""Jira client: JQL find parsing, create/update payloads, transitions."""

from __future__ import annotations

import httpx
import pytest

from gh_jira_sync.jira import JiraClient, JiraError


def _client(handler: httpx.MockTransport, recorder: list[httpx.Request] | None = None) -> JiraClient:
    http = httpx.Client(base_url="https://x.atlassian.net", transport=handler)
    return JiraClient("https://x.atlassian.net", "a@b.co", "tok", client=http)


def test_find_epics_parses_status_category() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "key": "RD-1",
                        "fields": {
                            "summary": "M1",
                            "description": {"type": "doc"},
                            "duedate": "2026-08-01",
                            "labels": ["gh-ms-1", "mc-assistant"],
                            "status": {"statusCategory": {"key": "done"}},
                        },
                    }
                ]
            },
        )

    epics = _client(httpx.MockTransport(handle)).find_issues_by_label("RD", "gh-ms-1", "11087")
    assert len(epics) == 1
    assert epics[0].key == "RD-1"
    assert epics[0].status_category == "done"
    assert epics[0].labels == ["gh-ms-1", "mc-assistant"]


def test_find_issues_scopes_jql_to_issue_type() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"issues": []})

    _client(httpx.MockTransport(handle)).find_issues_by_label("RD", "gh-ms-1", "11089")
    assert captured["jql"] == 'project = "RD" AND labels = "gh-ms-1" AND issuetype = 11089'


def test_create_issue_payload() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(201, json={"key": "RD-9"})

    key = _client(httpx.MockTransport(handle)).create_issue(
        "RD",
        "11087",
        summary="M1",
        description={"type": "doc"},
        labels=["gh-ms-1"],
        duedate=None,
    )
    assert key == "RD-9"
    fields = captured["fields"]
    assert fields["issuetype"] == {"id": "11087"}
    assert "duedate" not in fields  # never send null
    assert "parent" not in fields  # epic mode sends no parent


def test_create_issue_includes_duedate_when_set() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(201, json={"key": "RD-9"})

    _client(httpx.MockTransport(handle)).create_issue(
        "RD", "11087", summary="M", description={}, labels=["gh-ms-1"], duedate="2026-08-01"
    )
    assert captured["fields"]["duedate"] == "2026-08-01"


def test_create_issue_sends_parent_in_stories_mode() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(201, json={"key": "RD-42"})

    _client(httpx.MockTransport(handle)).create_issue(
        "RD",
        "11089",
        summary="M",
        description={},
        labels=["gh-ms-1"],
        duedate=None,
        parent_key="RD-16",
    )
    assert captured["fields"]["parent"] == {"key": "RD-16"}
    assert captured["fields"]["issuetype"] == {"id": "11089"}


_PROJECT_TYPES = {
    "issueTypes": [
        {"id": "11086", "name": "Tâche", "untranslatedName": "Task", "subtask": False},
        {"id": "11087", "name": "Epic", "untranslatedName": "Epic", "subtask": False},
        {"id": "11088", "name": "Subtask", "subtask": True},
        {"id": "11089", "name": "Story", "untranslatedName": "Story", "subtask": False},
    ]
}


def test_resolve_issue_type_id_finds_story() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/api/3/project/RD"
        return httpx.Response(200, json=_PROJECT_TYPES)

    assert _client(httpx.MockTransport(handle)).resolve_issue_type_id("RD", "Story") == "11089"


def test_resolve_issue_type_id_matches_untranslated_name() -> None:
    """A localised project still resolves the canonical English type name."""

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_PROJECT_TYPES)

    assert _client(httpx.MockTransport(handle)).resolve_issue_type_id("RD", "task") == "11086"


def test_resolve_issue_type_id_missing_lists_available() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"issueTypes": [_PROJECT_TYPES["issueTypes"][1]]})

    with pytest.raises(JiraError, match=r"No 'Story' issue type.*Epic \(11087\)"):
        _client(httpx.MockTransport(handle)).resolve_issue_type_id("RD", "Story")


def test_describe_issue_returns_summary_and_type() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"key": "RD-16", "fields": {"summary": "mc-assistant", "issuetype": {"name": "Epic"}}},
        )

    assert _client(httpx.MockTransport(handle)).describe_issue("RD-16") == (
        "RD-16 'mc-assistant' (Epic)"
    )


def test_describe_issue_404_is_actionable() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"errorMessages": ["Issue does not exist"]})

    with pytest.raises(JiraError, match="stories-inside-epic-id"):
        _client(httpx.MockTransport(handle)).describe_issue("RD-999")


def test_verify_auth_ok_returns_account() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"emailAddress": "me@rivrs.io", "accountId": "abc"})

    assert _client(httpx.MockTransport(handle)).verify_auth() == "me@rivrs.io"


def test_verify_auth_401_flags_scoped_token() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Client must be authenticated to access this resource.")

    with pytest.raises(JiraError, match="scoped API tokens"):
        _client(httpx.MockTransport(handle)).verify_auth()


def test_error_surfaces_jira_detail() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "errorMessages": [],
                "errors": {"labels": "Field 'labels' cannot be set. It is not on the appropriate screen, or unknown."},
            },
        )

    with pytest.raises(JiraError, match="labels: Field 'labels' cannot be set"):
        _client(httpx.MockTransport(handle)).create_issue(
            "RD", "11087", summary="M", description={}, labels=["gh-ms-1"], duedate=None
        )


def test_get_transitions_extracts_category() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "transitions": [
                    {"id": "31", "name": "Done", "to": {"statusCategory": {"key": "done"}}},
                    {"id": "11", "name": "To Do", "to": {"statusCategory": {"key": "new"}}},
                ]
            },
        )

    ts = _client(httpx.MockTransport(handle)).get_transitions("RD-1")
    assert {t.to_category for t in ts} == {"done", "new"}
