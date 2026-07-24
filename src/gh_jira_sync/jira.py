"""Jira Cloud REST v3 client: JQL find, create, update, transitions, labels."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from .http import build_client

Json = dict[str, Any]


class JiraError(Exception):
    """A Jira API call failed; carries the status and Jira's own error detail."""


def _raise_for_jira(resp: httpx.Response) -> None:
    """Like ``raise_for_status`` but includes Jira's response body in the message.

    Jira returns validation detail in ``errorMessages``/``errors``; a bare
    ``raise_for_status`` discards it and leaves you with an opaque ``400``.
    """
    if not resp.is_error:
        return
    detail = resp.text.strip()
    try:
        body = resp.json()
        parts = list(body.get("errorMessages", []))
        parts += [f"{field}: {msg}" for field, msg in body.get("errors", {}).items()]
        if parts:
            detail = "; ".join(parts)
    except Exception:  # noqa: BLE001 — fall back to raw text
        pass
    raise JiraError(
        f"{resp.status_code} {resp.request.method} {resp.request.url}: {detail}"
    )


@dataclass(frozen=True)
class Epic:
    """The slice of an epic we read back for diffing/reconciliation."""

    key: str
    summary: str
    description: Json | None
    duedate: str | None
    labels: list[str]
    status_category: str  # "new" | "indeterminate" | "done" | ""


@dataclass(frozen=True)
class Transition:
    id: str
    name: str
    to_category: str  # to.statusCategory.key


class JiraClient:
    """Thin Jira Cloud REST v3 client (mocked in tests)."""

    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._owns_client = client is None
        token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        self._client = client or build_client(
            base_url,
            {
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    def __enter__(self) -> JiraClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # --- reads ----------------------------------------------------------------

    def verify_auth(self) -> str:
        """Fail fast with an actionable message if the credentials don't authenticate.

        ``search/jql`` returns an empty list for an unauthenticated caller rather
        than 401, which otherwise surfaces later as a confusing "cannot create"
        error. Checking ``/myself`` up front turns that into a clear auth error.
        """
        resp = self._client.get("/rest/api/3/myself")
        if resp.status_code in (401, 403):
            raise JiraError(
                f"Jira authentication failed ({resp.status_code}). Check jira-email "
                "and jira-api-token. Note: scoped API tokens (prefix 'ATATT', created "
                "'with scopes') do NOT work here - create a classic API token at "
                "https://id.atlassian.com/manage-profile/security/api-tokens."
            )
        _raise_for_jira(resp)
        data = resp.json()
        who = data.get("emailAddress") or data.get("displayName") or data.get("accountId")
        return str(who or "?")

    def find_epics_by_label(self, project_key: str, label: str) -> list[Epic]:
        """Return every epic in the project carrying ``label`` (0, 1, or >1)."""
        jql = f'project = "{project_key}" AND labels = "{label}"'
        resp = self._client.post(
            "/rest/api/3/search/jql",
            json={
                "jql": jql,
                "maxResults": 50,
                "fields": ["summary", "description", "duedate", "labels", "status"],
            },
        )
        _raise_for_jira(resp)
        return [_parse_epic(issue) for issue in resp.json().get("issues", [])]

    def get_transitions(self, key: str) -> list[Transition]:
        resp = self._client.get(f"/rest/api/3/issue/{key}/transitions")
        _raise_for_jira(resp)
        out: list[Transition] = []
        for t in resp.json().get("transitions", []):
            to = t.get("to") or {}
            category = (to.get("statusCategory") or {}).get("key", "")
            out.append(Transition(id=t["id"], name=t.get("name", ""), to_category=category))
        return out

    # --- writes ---------------------------------------------------------------

    def create_epic(
        self,
        project_key: str,
        epic_issue_type_id: str,
        *,
        summary: str,
        description: Json,
        labels: list[str],
        duedate: str | None,
    ) -> str:
        fields: Json = {
            "project": {"key": project_key},
            "issuetype": {"id": epic_issue_type_id},
            "summary": summary,
            "description": description,
            "labels": labels,
        }
        if duedate is not None:
            fields["duedate"] = duedate
        resp = self._client.post("/rest/api/3/issue", json={"fields": fields})
        _raise_for_jira(resp)
        return str(resp.json()["key"])

    def update_fields(self, key: str, fields: Json) -> None:
        resp = self._client.put(f"/rest/api/3/issue/{key}", json={"fields": fields})
        _raise_for_jira(resp)

    def transition(self, key: str, transition_id: str) -> None:
        resp = self._client.post(
            f"/rest/api/3/issue/{key}/transitions",
            json={"transition": {"id": transition_id}},
        )
        _raise_for_jira(resp)


def _parse_epic(issue: Json) -> Epic:
    fields = issue.get("fields", {})
    status = fields.get("status") or {}
    category = (status.get("statusCategory") or {}).get("key", "")
    return Epic(
        key=issue["key"],
        summary=fields.get("summary", ""),
        description=fields.get("description"),
        duedate=fields.get("duedate"),
        labels=list(fields.get("labels", [])),
        status_category=category,
    )
