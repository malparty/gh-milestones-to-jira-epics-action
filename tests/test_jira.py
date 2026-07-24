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

    epics = _client(httpx.MockTransport(handle)).find_epics_by_label("RD", "gh-ms-1")
    assert len(epics) == 1
    assert epics[0].key == "RD-1"
    assert epics[0].status_category == "done"
    assert epics[0].labels == ["gh-ms-1", "mc-assistant"]


def test_create_epic_payload() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(201, json={"key": "RD-9"})

    key = _client(httpx.MockTransport(handle)).create_epic(
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


def test_create_epic_includes_duedate_when_set() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(201, json={"key": "RD-9"})

    _client(httpx.MockTransport(handle)).create_epic(
        "RD", "11087", summary="M", description={}, labels=["gh-ms-1"], duedate="2026-08-01"
    )
    assert captured["fields"]["duedate"] == "2026-08-01"


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
        _client(httpx.MockTransport(handle)).create_epic(
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
