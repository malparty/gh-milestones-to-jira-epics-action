"""CLI entry point: parse inputs/flags, run the sync, emit outputs and exit code."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

from .config import Config, ConfigError, load_config
from .fetch import GitHubClient
from .jira import JiraClient, JiraError
from .sync import SyncResult, sync


def _make_logger(verbose: bool) -> Callable[[str], None]:
    def log(message: str) -> None:
        if message.startswith("ERROR "):
            print(f"::error::{message[len('ERROR '):]}", file=sys.stderr)
        elif message.startswith("[dry-run]") or verbose or not message.startswith("unchanged"):
            print(message)

    return log


def _write_outputs(result: SyncResult) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"created={result.created}\n")
        fh.write(f"updated={result.updated}\n")
        fh.write(f"unchanged={result.unchanged}\n")
        fh.write(f"skipped={result.skipped}\n")


def run(cfg: Config) -> SyncResult:
    log = _make_logger(cfg.verbose)
    if cfg.dry_run:
        log("[dry-run] no writes will be performed")
    with (
        GitHubClient(cfg.github_token, cfg.github_repository) as gh,
        JiraClient(cfg.jira_base_url, cfg.jira_email, cfg.jira_api_token) as jira,
    ):
        result = sync(cfg, gh, jira, log)
    _write_outputs(result)
    return result


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        cfg = load_config(argv)
    except ConfigError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2
    try:
        result = run(cfg)
    except JiraError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
