# GitHub Milestones → Jira Epics

Mirror a repository's **GitHub milestones** into **Jira Cloud epics** — one-way,
idempotent, and safe to run on a schedule. Each milestone becomes one epic; the
epic's summary, description (a rendered issue rollup), due date, labels and
open/closed status are kept in sync. Jira is treated as a read-only mirror:
the action never clobbers manual edits it isn't responsible for.

- **Direction:** GitHub → Jira only.
- **Matching:** each issue is tagged with a structural label `gh-ms-<number>`
  (the milestone number). Lookups use an exact JQL match on that label, so the
  link survives title edits.
- **Idempotent:** a run with no GitHub change performs no writes.
- **Two shapes:** one **epic** per milestone (default), or — with
  [`stories-inside-epic-id`](#stories-under-one-epic) — one **story** per
  milestone, all parented to a single epic you already have.

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
          default-due-in-days: "30"                    # fallback due date, on create only
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
| `jira-epic-issue-type-id` | ✓ᵈ | — | Epic issue-type id for the project (instance-specific — see below). Not needed in stories mode. |
| `stories-inside-epic-id` | — | `""` (off) | Create a **story per milestone** parented to this epic instead of an epic per milestone. Accepts `RD-16`, a bare `16`, or a Jira issue URL. |
| `jira-story-issue-type-id` | — | `""` (auto) | Story issue-type id, stories mode only. Empty ⇒ resolved from the project's `Story` type at run time. |
| `jira-extra-labels` | — | `""` | Comma-separated labels merged onto every issue (trimmed, deduped). No spaces. |
| `default-due-in-days` | — | `""` (off) | Fallback due date for a milestone with no due date: run date + N days, **on create only**. A GitHub due date always wins. |
| `github-repository` | — | `""` (current repo) | Source repo to read milestones/issues from, as `owner/repo`. See [Reading from a different repo](#reading-from-a-different-repo). |
| `github-token` | — | `${{ github.token }}` | Token used to read milestones/issues. |
| `only` | — | — | Sync a single milestone by `number` (used on the milestone-event path). |
| `dry-run` | — | `false` | Print intended create/update/transition actions without writing. |
| `verbose` | — | `false` | Log unchanged milestones too. |

ᵈ Required unless `stories-inside-epic-id` is set.

## Outputs

| Output | Description |
|---|---|
| `created` | Count of issues created (epics, or stories in stories mode). |
| `updated` | Count of issues updated. |
| `unchanged` | Count of no-op milestones. |
| `skipped` | Count skipped (e.g. more than one issue per label). |

## Stories under one epic

Sometimes a repo isn't worth an epic per milestone — you want one epic for the
whole effort and a story per milestone underneath it. Point
`stories-inside-epic-id` at that epic:

```yaml
with:
  jira-project-key: RD
  stories-inside-epic-id: RD-16          # or "16", or the Jira URL you copied
  default-due-in-days: "30"
  # jira-epic-issue-type-id not needed here
  # jira-story-issue-type-id: "11089"    # optional; auto-resolved from the project
```

- The **parent epic must already exist** in `jira-project-key` — the action never
  creates it. Its key and type are read (and reported) before the first
  milestone, so a typo fails immediately, even in `--dry-run`.
- Everything else is identical to epic mode: same `gh-ms-<number>` label, same
  description rollup, due dates, label merge and status transitions.
- The label lookup is **scoped to the issue type**, so the two modes stay
  independently idempotent: switching a repo from epic mode to stories mode
  creates the stories and leaves the epics an earlier run made untouched (delete
  those yourself if you don't want both).
- **Parent is set at creation only.** Re-parenting an existing story, or moving a
  repo back and forth between modes, is a manual Jira operation on purpose.

## Reading from a different repo

By default the action reads milestones from the repo the workflow runs in. To
mirror milestones from a *different* repo instead — say you can't add a
workflow to that repo, or you want one central sync job — set
`github-repository` and give `github-token` read access there:

```yaml
with:
  github-repository: your-org/other-repo
  github-token: ${{ secrets.MILESTONES_PAT }}   # see note below
  jira-base-url: https://your-org.atlassian.net
  jira-email: ${{ secrets.JIRA_EMAIL }}
  jira-api-token: ${{ secrets.JIRA_API_TOKEN }}
  jira-project-key: RD
  jira-epic-issue-type-id: "11087"
```

**A PAT is required here.** The default `github-token` (`${{ github.token }}`)
is the auto-generated token scoped only to the repo the workflow runs in — it
cannot read another repo's milestones or issues, even a public one. Create a
classic or fine-grained PAT with read access to the *target* repo's issues and
contents (a fine-grained token scoped to just that repo, with `Issues: read`
and `Contents: read`, is enough), store it as a secret (e.g.
`MILESTONES_PAT`) in the repo running the workflow, and pass it as
`github-token`.

## What gets written

- **Summary** — the milestone title verbatim (the id lives in the label, not the title).
- **Labels** — `gh-ms-<number>` plus any `jira-extra-labels`. On update the label
  set is treated as a **superset**: missing labels are added, existing ones are
  never pruned (so labels a human added in Jira survive).
- **Due date** — the milestone's due date when it has one; never cleared afterwards.
  With `default-due-in-days: 30`, a milestone with **no** due date gets
  `run date + 30 days` **at creation time only** — so the epic starts with a
  plausible date you can then adjust in Jira, and later runs never touch it. Add
  a due date on the milestone afterwards and it overwrites the fallback (GitHub
  always wins). Leave the input empty to omit the field entirely, as before.
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

- **Jira:** create a **classic** [API token](https://id.atlassian.com/manage-profile/security/api-tokens)
  — use **"Create API token"**, *not* "Create API token with scopes". Scoped
  tokens (prefix `ATATT`) only authenticate against Atlassian's `api.atlassian.com`
  gateway, not the site URL this action uses, so they fail with a `401`. Use an
  account that can create/edit/transition issues in the target project. Store
  `jira-email` and `jira-api-token` as repository (or org) secrets. Auth is Jira
  Cloud REST v3 Basic auth (`base64(email:api_token)`).
- **GitHub:** the default `github-token` needs `issues: read` and
  `contents: read` — set them in the workflow `permissions:` block.

## Finding instance-specific ids

Standard field keys (`summary`, `description`, `duedate`, `labels`, `reporter`)
are identical across Cloud instances. Only the **issue-type ids** are
instance-specific. Discover them with:

```bash
curl -su "$EMAIL:$TOKEN" \
  "https://your-org.atlassian.net/rest/api/3/project/RD" | jq '.issueTypes[]|{id,name}'
```

Pick the id whose `name` is `Epic`. In stories mode the `Story` id is looked up
from this same endpoint automatically — set `jira-story-issue-type-id` only if
your project's story-level type is named something else.

## Local testing

Run the exact same code path locally for quick iteration:

```bash
cp .env.example .env          # then fill in your Jira + GitHub values
uv run --env-file .env python -m gh_jira_sync --dry-run --verbose   # preview
uv run --env-file .env python -m gh_jira_sync --only 3 --write      # one live create
```

`.env` is gitignored. Inputs are read from `INPUT_*` env vars (the GitHub
Action convention). Flags override the env either way: `--dry-run` /
`--no-dry-run` (alias `--write`), `--only N`, `--verbose`,
`--default-due-in-days N`, `--stories-inside-epic-id KEY` (empty value forces
epic mode). Scope a first live
run with `--only <existing-milestone-number>` to keep the blast radius to one
epic.

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
