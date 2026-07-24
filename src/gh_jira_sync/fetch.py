"""GitHub read layer: milestones + issues, paginated, PR-filtered, sorted."""

from __future__ import annotations

from typing import Any

import httpx

from .http import build_client
from .models import Issue, Milestone

_API = "https://api.github.com"
_PER_PAGE = 100


class GitHubClient:
    """Thin GitHub REST client (mocked in tests)."""

    def __init__(self, token: str, repository: str, *, client: httpx.Client | None = None) -> None:
        self._repository = repository
        self._owns_client = client is None
        self._client = client or build_client(
            _API,
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _paginate(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        page = 1
        while True:
            resp = self._client.get(path, params={**params, "per_page": _PER_PAGE, "page": page})
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            results.extend(batch)
            if len(batch) < _PER_PAGE:
                break
            page += 1
        return results

    def fetch_milestones(self, state: str = "all") -> list[Milestone]:
        """All milestones (open + closed by default), sorted by ``number``."""
        raw = self._paginate(f"/repos/{self._repository}/milestones", {"state": state})
        milestones = [
            Milestone(
                number=m["number"],
                title=m["title"],
                description=m.get("description"),
                state=m["state"],
                due_on=m.get("due_on"),
            )
            for m in raw
        ]
        return sorted(milestones, key=lambda m: m.number)

    def fetch_issues(self, milestone_number: int, state: str = "all") -> list[Issue]:
        """Issues for a milestone, pull requests dropped (§2.4), sorted by ``number``."""
        raw = self._paginate(
            f"/repos/{self._repository}/issues",
            {"milestone": str(milestone_number), "state": state},
        )
        issues = [
            Issue(
                number=i["number"],
                title=i["title"],
                state=i["state"],
                closed_at=i.get("closed_at"),
            )
            for i in raw
            if "pull_request" not in i
        ]
        return sorted(issues, key=lambda i: i.number)
