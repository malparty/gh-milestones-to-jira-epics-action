"""GitHub fetch layer: pagination, PR filtering, sorting."""

from __future__ import annotations

import httpx

from gh_jira_sync.fetch import GitHubClient


def _client(handler: httpx.MockTransport) -> GitHubClient:
    http = httpx.Client(base_url="https://api.github.com", transport=handler)
    return GitHubClient("tok", "malparty/demo", client=http)


def test_fetch_milestones_sorted() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "1":
            return httpx.Response(
                200,
                json=[
                    {"number": 3, "title": "C", "description": None, "state": "open", "due_on": None},
                    {"number": 1, "title": "A", "description": "d", "state": "closed", "due_on": None},
                ],
            )
        return httpx.Response(200, json=[])

    ms = _client(httpx.MockTransport(handle)).fetch_milestones()
    assert [m.number for m in ms] == [1, 3]


def test_fetch_issues_drops_prs_and_sorts() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "1":
            return httpx.Response(
                200,
                json=[
                    {"number": 5, "title": "issue b", "state": "open", "closed_at": None},
                    {"number": 9, "title": "a PR", "state": "open", "pull_request": {"url": "x"}},
                    {"number": 2, "title": "issue a", "state": "closed", "closed_at": "2026-01-02T00:00:00Z"},
                ],
            )
        return httpx.Response(200, json=[])

    issues = _client(httpx.MockTransport(handle)).fetch_issues(4)
    assert [i.number for i in issues] == [2, 5]
    assert issues[0].closed_date == "2026-01-02"
