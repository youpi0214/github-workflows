# Security report publication

[Workflow source](../../.github/workflows/security-publish.yml) · [Workflow catalog](../../README.md#workflows)

Store complete full-audit HTML and JSON reports in the calling repository's GitHub Releases. Each publication preserves history and refreshes a stable latest-report reference.

## Usage

Normally enable publication through [security scanning](scan.md), which supplies the current run's report artifact:

```yaml
name: Full security audit

on:
  schedule:
    - cron: "15 8 * * 1"
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  audit:
    uses: youpi0214/github-workflows/.github/workflows/security-scan.yml@v1.3.0
    with:
      library-ref: v1.3.0
      mode: full
      publish: true
```

The caller owns the schedule. Repository metadata determines the default branch; no consumer branch name is hardcoded in the publisher.

For an advanced caller with an `audit` job that already exposes a full-report artifact ID, the publication job is:

```yaml
publish:
  needs: audit
  uses: youpi0214/github-workflows/.github/workflows/security-publish.yml@v1.3.0
  permissions:
    contents: write
  with:
    library-ref: v1.3.0
    artifact-id: ${{ needs.audit.outputs.artifact-id }}
```

The artifact must belong to the same workflow run and contain `index.html` and normalized `report.json`. Direct callers are responsible for producing the expected report format; the publisher validates completeness and full-repository coverage before uploading.

## Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `library-ref` | string | **Required** | Version tag matching the workflow reference. Retained for interface compatibility; the publisher no longer checks out library scripts. |
| `artifact-id` | string | **Required** | Current-run report artifact ID to download. |

## Outputs

No workflow outputs are exposed. The result is a historical GitHub Release and updated latest-report assets in the caller repository.

## Permissions

The caller must grant `contents: write`. Publication runs only on the default branch for `push`, `schedule`, or `workflow_dispatch` events. PR and `pull_request_target` events cannot publish. No consumer checkout or artifact-provided code is executed; an inline validator reads report JSON as data.

Through `security-scan.yml`, publication additionally requires `publish: true`, explicit `mode: full`, and a complete report with status CLEAN or FINDINGS. Complete reports containing vulnerabilities can be published before the final security enforcement job fails. SKIPPED and INCOMPLETE reports are not published.

## Releases and assets

| Purpose | Release title | Tag |
|---|---|---|
| Historical snapshot | `Security audit — 2026-11-12 08:15:30 UTC` | `security-report-2026-11-12T08-15-30Z` |
| Latest report | `Security audit — latest report` | `security-report-latest` |

The timestamp is generated once at publication time in UTC, with second precision. `Z` means UTC; hyphens replace time colons to make a valid Git tag. Descriptions include publication time, scanned branch/revision, workflow run link, and attempt number. The latest description links to its historical snapshot.

Both releases contain `index.html` and `report.json`. Historical tags are checked for collisions, and their assets are not overwritten. A same-second collision fails explicitly; rerun to generate a fresh timestamp. Existing run-ID-based historical releases remain untouched. Latest assets are replaceable; the latest tag's original commit is not moved to track each scan, so use the description/report metadata to identify the current scanned revision.

Both releases use `make_latest: false` to avoid promoting security reports over normal software releases. GitHub's separate Latest badge is not part of the release title and is controlled by GitHub's release selection.

## Viewing and retention

Download `index.html` before opening the interactive dashboard locally. GitHub Release HTML assets generally do not open as an interactive hosted dashboard in the Release page. The downloaded dashboard needs no external assets.

Release history has no automatic cleanup and is independent of Actions artifact retention. All reports are stored in the calling repository, never the public library repository. Public caller Release assets expose findings publicly; enable publication only where repository visibility is appropriate.

## Troubleshooting

| Symptom | Check |
|---|---|
| Publication skipped | Verify event, default branch, explicit full mode, complete status, and `publish`. |
| Artifact not found | Supply an artifact from the current run, not an ID from an earlier audit. |
| Validation rejected the report | All coverage entries must have component `repository` and target `.`; the scan list must be nonempty with no failures. |
| Timestamp tag exists | Rerun publication to obtain a new UTC timestamp; history is intentionally preserved. |
| Latest assets cannot be replaced | Immutable Release policies can prevent this storage model. Disable publication or allow replaceable report Releases. |
| API/ruleset failure | Check contents permission and repository tag/Release policies. |

Publication is serialized per calling repository. A late-finishing older audit can still publish after a newer audit; the latest-report reference means the most recently published report.
