"""Domain models shared across fetch/render/sync.

Kept free of I/O so ``render`` can import them without pulling in httpx.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Issue:
    """A GitHub issue attached to a milestone (pull requests are excluded upstream)."""

    number: int
    title: str
    state: str  # "open" | "closed"
    closed_at: str | None  # ISO8601 timestamp, present when closed

    @property
    def closed_date(self) -> str | None:
        """The ``YYYY-MM-DD`` portion of ``closed_at``, if any."""
        return self.closed_at[:10] if self.closed_at else None


@dataclass(frozen=True)
class Milestone:
    """A GitHub milestone."""

    number: int
    title: str
    description: str | None
    state: str  # "open" | "closed"
    due_on: str | None  # ISO8601 timestamp, present when a due date is set

    @property
    def due_date(self) -> str | None:
        """The ``YYYY-MM-DD`` portion of ``due_on`` (UTC date as-is), if any."""
        return self.due_on[:10] if self.due_on else None
