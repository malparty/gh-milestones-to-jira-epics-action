"""Read and validate configuration from ``INPUT_*`` env vars (GitHub Action convention)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid.

    Carries an actionable message; a published action must not emit a raw traceback.
    """


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_default_due_in_days(raw: str) -> int | None:
    """Parse the ``default-due-in-days`` input; empty means "no fallback"."""
    if not raw:
        return None
    try:
        days = int(raw)
    except ValueError as exc:
        raise ConfigError(
            "default-due-in-days must be a whole number of days "
            f"(or empty to disable), got {raw!r}"
        ) from exc
    if days < 0:
        raise ConfigError(f"default-due-in-days must not be negative, got {days}")
    return days


_ISSUE_KEY_RE = re.compile(r"([A-Za-z][A-Za-z0-9_]*)-(\d+)")


def parse_stories_inside_epic_id(raw: str, project_key: str) -> str | None:
    """Parse ``stories-inside-epic-id`` into a canonical Jira issue key, or ``None``.

    Accepts an issue key (``RD-16``), a bare number in the target project (``16``),
    or anything containing the key — a pasted Jira URL such as
    ``.../timeline?selectedIssue=RD-16`` works. Empty means "epic mode" (the
    pre-1.1 behaviour: one epic per milestone, no parent).
    """
    value = raw.strip()
    if not value:
        return None

    if value.isdigit():
        return f"{project_key.upper()}-{int(value)}"

    match = _ISSUE_KEY_RE.search(value)
    if match is None:
        raise ConfigError(
            "stories-inside-epic-id must be a Jira issue key (e.g. RD-16), a bare "
            "number in the target project (e.g. 16), or a Jira issue URL; "
            f"got {raw!r}"
        )
    key_prefix, number = match.group(1).upper(), int(match.group(2))
    if key_prefix != project_key.upper():
        raise ConfigError(
            f"stories-inside-epic-id {key_prefix}-{number} is not in project "
            f"{project_key}; a story and its parent epic must live in the same project."
        )
    return f"{key_prefix}-{number}"


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
    jira_story_issue_type_id: str  # empty ⇒ resolved from the project's "Story" type
    stories_inside_epic: str | None  # parent epic key ⇒ create stories, not epics
    jira_extra_labels: list[str]
    default_due_in_days: int | None  # fallback due date on create; None disables it
    github_token: str
    github_repository: str  # "owner/repo"
    only: int | None
    dry_run: bool
    verbose: bool

    @property
    def stories_mode(self) -> bool:
        """True when milestones become stories parented to ``stories_inside_epic``."""
        return self.stories_inside_epic is not None

    @property
    def owner(self) -> str:
        return self.github_repository.split("/", 1)[0]

    @property
    def repo(self) -> str:
        return self.github_repository.split("/", 1)[1]


def load_config(argv: list[str] | None = None) -> Config:
    """Build a :class:`Config` from ``INPUT_*`` env vars, with CLI flag overrides.

    Flags mirror the action inputs so the same code path runs in CI, in the
    action, and locally: ``--only N``, ``--dry-run``, ``--verbose``,
    ``--default-due-in-days N``, ``--stories-inside-epic-id KEY``.
    """
    argv = argv if argv is not None else []

    base_url = _env("INPUT_JIRA_BASE_URL").rstrip("/")
    email = _env("INPUT_JIRA_EMAIL")
    api_token = _env("INPUT_JIRA_API_TOKEN")
    project_key = _env("INPUT_JIRA_PROJECT_KEY")
    epic_type_id = _env("INPUT_JIRA_EPIC_ISSUE_TYPE_ID")
    story_type_id = _env("INPUT_JIRA_STORY_ISSUE_TYPE_ID")
    stories_inside_epic_raw = _env("INPUT_STORIES_INSIDE_EPIC_ID")
    extra_labels = parse_extra_labels(_env("INPUT_JIRA_EXTRA_LABELS"))
    default_due_in_days = parse_default_due_in_days(_env("INPUT_DEFAULT_DUE_IN_DAYS"))

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
        elif arg in ("--no-dry-run", "--write"):
            dry_run = False
        elif arg == "--verbose":
            verbose = True
        elif arg == "--only":
            i += 1
            if i >= len(argv):
                raise ConfigError("--only requires a milestone number")
            only_cli = argv[i]
        elif arg.startswith("--only="):
            only_cli = arg.split("=", 1)[1]
        elif arg == "--default-due-in-days":
            i += 1
            if i >= len(argv):
                raise ConfigError("--default-due-in-days requires a number of days")
            default_due_in_days = parse_default_due_in_days(argv[i].strip())
        elif arg.startswith("--default-due-in-days="):
            default_due_in_days = parse_default_due_in_days(arg.split("=", 1)[1].strip())
        elif arg == "--stories-inside-epic-id":
            i += 1
            if i >= len(argv):
                raise ConfigError("--stories-inside-epic-id requires an epic key or number")
            stories_inside_epic_raw = argv[i]
        elif arg.startswith("--stories-inside-epic-id="):
            stories_inside_epic_raw = arg.split("=", 1)[1]
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

    required = [
        ("jira-base-url", base_url),
        ("jira-email", email),
        ("jira-api-token", api_token),
        ("jira-project-key", project_key),
        ("github-token", github_token),
    ]
    # In stories mode nothing is created at epic level, so the epic type id is moot;
    # the story type id is optional either way (resolved from the project on demand).
    if not stories_inside_epic_raw:
        required.append(("jira-epic-issue-type-id", epic_type_id))

    missing = [name for name, value in required if not value]
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

    stories_inside_epic = parse_stories_inside_epic_id(stories_inside_epic_raw, project_key)

    return Config(
        jira_base_url=base_url,
        jira_email=email,
        jira_api_token=api_token,
        jira_project_key=project_key,
        jira_epic_issue_type_id=epic_type_id,
        jira_story_issue_type_id=story_type_id,
        stories_inside_epic=stories_inside_epic,
        jira_extra_labels=extra_labels,
        default_due_in_days=default_due_in_days,
        github_token=github_token,
        github_repository=github_repository,
        only=only,
        dry_run=dry_run,
        verbose=verbose,
    )
