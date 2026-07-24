"""Read and validate configuration from ``INPUT_*`` env vars (GitHub Action convention)."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid.

    Carries an actionable message; a published action must not emit a raw traceback.
    """


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_extra_labels(raw: str) -> list[str]:
    """Parse the comma-separated ``jira-extra-labels`` input.

    Entries are trimmed and de-duplicated while preserving first-seen order.
    Labels may not contain whitespace (Jira rejects them).
    """
    labels: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        label = part.strip()
        if not label:
            continue
        if any(ch.isspace() for ch in label):
            raise ConfigError(
                f"jira-extra-labels entry {label!r} contains whitespace; "
                "Jira labels may not contain spaces."
            )
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


@dataclass(frozen=True)
class Config:
    """Validated runtime configuration."""

    jira_base_url: str
    jira_email: str
    jira_api_token: str
    jira_project_key: str
    jira_epic_issue_type_id: str
    jira_extra_labels: list[str]
    github_token: str
    github_repository: str  # "owner/repo"
    only: int | None
    dry_run: bool
    verbose: bool

    @property
    def owner(self) -> str:
        return self.github_repository.split("/", 1)[0]

    @property
    def repo(self) -> str:
        return self.github_repository.split("/", 1)[1]


def load_config(argv: list[str] | None = None) -> Config:
    """Build a :class:`Config` from ``INPUT_*`` env vars, with CLI flag overrides.

    Flags mirror the action inputs so the same code path runs in CI, in the
    action, and locally: ``--only N``, ``--dry-run``, ``--verbose``.
    """
    argv = argv if argv is not None else []

    base_url = _env("INPUT_JIRA_BASE_URL").rstrip("/")
    email = _env("INPUT_JIRA_EMAIL")
    api_token = _env("INPUT_JIRA_API_TOKEN")
    project_key = _env("INPUT_JIRA_PROJECT_KEY")
    epic_type_id = _env("INPUT_JIRA_EPIC_ISSUE_TYPE_ID")
    extra_labels = parse_extra_labels(_env("INPUT_JIRA_EXTRA_LABELS"))

    github_token = _env("INPUT_GITHUB_TOKEN") or _env("GITHUB_TOKEN")
    github_repository = _env("INPUT_GITHUB_REPOSITORY") or _env("GITHUB_REPOSITORY")

    only_raw = _env("INPUT_ONLY")
    dry_run = _bool(_env("INPUT_DRY_RUN"))
    verbose = _bool(_env("INPUT_VERBOSE"))

    # CLI flags override env.
    only_cli: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--dry-run":
            dry_run = True
        elif arg == "--verbose":
            verbose = True
        elif arg == "--only":
            i += 1
            if i >= len(argv):
                raise ConfigError("--only requires a milestone number")
            only_cli = argv[i]
        elif arg.startswith("--only="):
            only_cli = arg.split("=", 1)[1]
        else:
            raise ConfigError(f"Unknown flag: {arg}")
        i += 1

    only_value = only_cli if only_cli is not None else only_raw
    only: int | None = None
    if only_value:
        try:
            only = int(only_value)
        except ValueError as exc:
            raise ConfigError(
                f"only must be an integer milestone number, got {only_value!r}"
            ) from exc

    missing = [
        name
        for name, value in [
            ("jira-base-url", base_url),
            ("jira-email", email),
            ("jira-api-token", api_token),
            ("jira-project-key", project_key),
            ("jira-epic-issue-type-id", epic_type_id),
            ("github-token", github_token),
        ]
        if not value
    ]
    if missing:
        raise ConfigError(
            "Missing required input(s): "
            + ", ".join(missing)
            + ". Set them via the action `with:` block or corresponding secrets."
        )
    if not github_repository or "/" not in github_repository:
        raise ConfigError(
            "GITHUB_REPOSITORY must be set to 'owner/repo' "
            f"(got {github_repository!r}); it is provided automatically in Actions."
        )

    return Config(
        jira_base_url=base_url,
        jira_email=email,
        jira_api_token=api_token,
        jira_project_key=project_key,
        jira_epic_issue_type_id=epic_type_id,
        jira_extra_labels=extra_labels,
        github_token=github_token,
        github_repository=github_repository,
        only=only,
        dry_run=dry_run,
        verbose=verbose,
    )
