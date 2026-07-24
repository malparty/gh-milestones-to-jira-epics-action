# GitHub Milestones → Jira Epics

Mirror a repository's **GitHub milestones** into **Jira Cloud epics** — one-way,
idempotent, and safe to run on a schedule. Each milestone becomes one epic; the
epic's summary, description (a rendered issue rollup), due date, labels and
open/closed status are kept in sync. Jira is treated as a read-only mirror:
the action never clobbers manual edits it isn't responsible for.

- **Direction:** GitHub → Jira only.
- **Matching:** each epic is tagged with a structural label `gh-ms-<number>`
  (the milestone number). Lookups use an exact JQL match on that label, so the
  link survives title edits.
- **Idempotent:** a run with no GitHub change performs no writes.

## Quick start

Add a workflow to the repository whose milestones you want mirrored:

```yaml
# .github/workflows/jira-roadmap-sync.yml
name: Jira roadmap sync
on:
  schedule: [{ cron: "0 * * * *" }]   # hourly safety net
  workflow_dispatch:                   # manual, supports dry-run
  milestone:                           # near-real-time
    types: [created, edited, closed, opened, deleted]
concurrency: gh-jira-sync              # no double-writes
permissions:
  issues: read
  contents: read
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: malparty/gh-milestones-to-jira-epics-action@v1
        with:
          jira-base-url: https://your-org.atlassian.net
          jira-email: ${{ secrets.JIRA_EMAIL }}
          jira-api-token: ${{ secrets.JIRA_API_TOKEN }}
          jira-project-key: RD
          jira-epic-issue-type-id: "11087"
          jira-extra-labels: my-project,github-auto-sync
          only: ${{ github.event.milestone.number }}   # empty on cron ⇒ full pass
```

On a `milestone` event `only:` scopes the run to the one changed milestone; on
`schedule`/`workflow_dispatch` it is empty, so the action does a full pass.

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `jira-base-url` | ✓ | — | Jira Cloud base URL, e.g. `https://your-org.atlassian.net`. |
| `jira-email` | ✓ | — | Account email for the API token (**store as a secret**). |
| `jira-api-token` | ✓ | — | Jira Cloud API token (**store as a secret**). |
| `jira-project-key` | ✓ | — | Target project key, e.g. `RD`. |
| `jira-epic-issue-type-id` | ✓ | — | Epic issue-type id for the project (instance-specific — see below). |
| `jira-extra-labels` | — | `""` | Comma-separated labels merged onto every epic (trimmed, deduped). No spaces. |
| `github-token` | — | `${{ github.token }}` | Token used to read milestones/issues. |
| `only` | — | — | Sync a single milestone by `number` (used on the milestone-event path). |
| `dry-run` | — | `false` | Print intended create/update/transition actions without writing. |
| `verbose` | — | `false` | Log unchanged milestones too. |

## Outputs

| Output | Description |
|---|---|
| `created` | Count of epics created. |
| `updated` | Count of epics updated. |
| `unchanged` | Count of no-op milestones. |
| `skipped` | Count skipped (e.g. more than one epic per label). |

## What gets written

- **Summary** — the milestone title verbatim (the id lives in the label, not the title).
- **Labels** — `gh-ms-<number>` plus any `jira-extra-labels`. On update the label
  set is treated as a **superset**: missing labels are added, existing ones are
  never pruned (so labels a human added in Jira survive).
- **Due date** — set only when the milestone has one; never cleared afterwards.
- **Start date** — never written (set it manually in Jira; it always survives).
- **Description** — an [ADF](https://developer.atlassian.com/cloud/jira/platform/apis/document/structure/)
  document: an italic "do not edit" notice, a `closed/total issues closed`
  heading, the milestone description, and Open/Closed issue lists. Pull requests
  are excluded from both the counts and the lists. Written only when it changes.
- **Status** — a closed milestone transitions its epic to *Done*; reopening moves
  a *Done* epic back to *To&nbsp;Do*. An open milestone whose epic is manually
  *In Progress* is left alone. Transitions are matched by status **category**
  (`done`/`new`), so status renames and non-English projects still work.

## Required secrets & permissions

- **Jira:** create an [API token](https://id.atlassian.com/manage-profile/security/api-tokens)
  for an account that can create/edit/transition issues in the target project.
  Store `jira-email` and `jira-api-token` as repository (or org) secrets. Auth is
  Jira Cloud REST v3 Basic auth (`base64(email:api_token)`).
- **GitHub:** the default `github-token` needs `issues: read` and
  `contents: read` — set them in the workflow `permissions:` block.

## Finding instance-specific ids

Standard field keys (`summary`, `description`, `duedate`, `labels`, `reporter`)
are identical across Cloud instances. Only the **epic issue-type id** is
instance-specific. Discover it with:

```bash
curl -su "$EMAIL:$TOKEN" \
  "https://your-org.atlassian.net/rest/api/3/project/RD" | jq '.issueTypes[]|{id,name}'
```

Pick the id whose `name` is `Epic`.

## Local testing

Run the exact same code path locally for quick iteration:

```bash
cp .env.example .env          # then fill in your Jira + GitHub values
uv run --env-file .env python -m gh_jira_sync --dry-run --verbose
```

`.env` is gitignored. Inputs are read from `INPUT_*` env vars (the GitHub
Action convention); `--only N`, `--dry-run` and `--verbose` mirror the action
inputs and override the env values.

## Dry run

The safest first test — `--dry-run` (locally) or `dry-run: true` on a
`workflow_dispatch` trigger prints every intended create/update/transition/label
action without writing to Jira. When a Jira call fails, the error includes
Jira's own `errorMessages`/`errors` detail (not just the HTTP status), so a
rejected create tells you exactly which field it disliked.

## Versioning

Releases are semver-tagged (`v1.0.0`) with a moving major tag (`v1`). Pin `@v1`
to get compatible updates automatically, or pin an exact tag for full control.

## Development

```bash
uv run --extra dev pytest      # tests (golden-file ADF contract in tests/golden)
uv run --extra dev ruff check .
uv run --extra dev mypy
```

## License

[MIT](LICENSE)
