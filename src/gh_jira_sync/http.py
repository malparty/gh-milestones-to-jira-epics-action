"""Shared HTTP helper: an httpx transport with bounded retry/backoff (§10)."""

from __future__ import annotations

import time

import httpx

_RETRY_STATUSES = {429, 500, 502, 503, 504}


class RetryTransport(httpx.BaseTransport):
    """Retry transient failures (429 + 5xx) with exponential backoff.

    Honours ``Retry-After`` on 429 when present. Connection errors are retried
    by the wrapped transport's own ``retries`` setting.
    """

    def __init__(
        self,
        *,
        max_retries: int = 4,
        backoff: float = 1.0,
        sleep: object = time.sleep,
    ) -> None:
        self._inner = httpx.HTTPTransport(retries=2)
        self._max_retries = max_retries
        self._backoff = backoff
        self._sleep = sleep

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        attempt = 0
        while True:
            response = self._inner.handle_request(request)
            if response.status_code not in _RETRY_STATUSES or attempt >= self._max_retries:
                return response
            response.read()
            response.close()
            delay = self._retry_after(response) or self._backoff * (2**attempt)
            self._sleep(delay)  # type: ignore[operator]
            attempt += 1

    def close(self) -> None:
        self._inner.close()

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if value and value.isdigit():
            return float(value)
        return None


def build_client(base_url: str, headers: dict[str, str]) -> httpx.Client:
    """An httpx client with retry/backoff, used by both API clients."""
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        headers=headers,
        timeout=30.0,
        transport=RetryTransport(),
    )
