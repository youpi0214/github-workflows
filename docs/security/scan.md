# Security scan

[Workflow source](../../.github/workflows/security-scan.yml) · [Workflow catalog](../../README.md#workflows)

Run Semgrep Community Edition and Trivy, combine their results, and enforce a severity policy after generating reports. Supports full repositories, automatically selected monorepo components, and caller-selected targets. No scanner account or paid subscription is required.

## Usage

```yaml
name: Security

on:
  pull_request:
  push:

permissions:
  contents: write
  pull-requests: write

jobs:
  security:
    uses: youpi0214/github-workflows/.github/workflows/security-scan.yml@v1.3.0
    with:
      library-ref: v1.3.0
      fail-severity: HIGH
      pr-comment: true
```

Use the same published version in `uses` and `library-ref`. Without component configuration or explicit targets, both scanners scan `.` under the component name `application`. The caller owns trigger branches and schedules.

## Inputs

JSON inputs are YAML strings containing JSON arrays.

| Input | Type | Default | Description |
|---|---|---|---|
| `runner` | string | `ubuntu-24.04` | Single Linux runner label used for jobs. |
| `library-ref` | string | **Required** | Library version tag matching the workflow reference. |
| `mode` | string | `selective` | `selective` selects scopes; `full` scans the complete repository. |
| `config-file` | string | `""` | Repository-relative component YAML file. Enables automatic selection in selective mode. |
| `components` | string | `""` | JSON component-name array overriding detection. Requires `config-file`; `[]` selects nothing. |
| `targets` | string | `""` | JSON array of objects with `name`, `paths`, and optional `dependency-paths`. Cannot be combined with `config-file` in selective mode. |
| `scanners` | string | `["semgrep","trivy"]` | Enabled scanners; at least one is required. |
| `semgrep-rules` | string | `["p/default"]` | JSON array of registry rulesets or repository-relative rule files/directories. |
| `maven-cache-key` | string | `""` | Caller-prepared cache key for `~/.m2/repository`; empty disables restoration. |
| `trivy-offline-scan` | boolean | `false` | Disable remote dependency-resolution requests. Requires prepared Maven metadata for complete Java coverage. |
| `trivy-ignore-unfixed` | boolean | `false` | Exclude dependency vulnerabilities without an available fix from results and enforcement. |
| `trivy-skip-dirs` | string | `[]` | JSON array of directory exclusions understood by Trivy. |
| `fail-severity` | string | `HIGH` | Enforcement threshold; see [CI enforcement](#ci-enforcement). |
| `enforce` | boolean | `true` | Fail CI for findings meeting the threshold. |
| `fail-on-error` | boolean | `true` | Independently fail CI for scanner errors or incomplete scans. |
| `pr-comment` | boolean | `false` | Create/update one managed summary comment on eligible PRs. |
| `publish` | boolean | `false` | Publish complete trusted full scans through [security publication](publish.md). |
| `retention-days` | number | `30` | Retention for raw and combined Actions artifacts, subject to repository policy. Does not expire Release assets. |

## Outputs

| Output | Description |
|---|---|
| `status` | `CLEAN`, `FINDINGS`, `INCOMPLETE`, or `SKIPPED`. Status describes coverage/results, independently of enforcement. |
| `failed` | Policy decision as the string `true` or `false`. |
| `artifact-id` | ID of the combined `security-report` artifact from this run. |

Infrastructure failures can prevent outputs or reports from being created. Final enforcement fails when the report job fails or produces no status.

## Runner selection

All jobs default to `ubuntu-24.04`. Set `runner` to another Linux runner label:

```yaml
with:
  library-ref: v1.3.0
  runner: my-linux-runner
```

The same label is used for planning, scanner matrix jobs, reporting, commenting, enforcement, and nested publication. Set the input on the reusable workflow call; a caller job using `uses` does not also declare `runs-on`. The input accepts a single label, not JSON arrays or runner-group objects. The runner must be available to the calling repository.

Custom scan runners need Bash, Git, Python 3 with pip, jq, coreutils (`timeout` and `realpath`), Docker with daemon access, and network access to GitHub and scanner registries/databases/rulesets. The runner agent and archive/cache tools must support the pinned Actions. Windows and macOS are not supported by this implementation.

Use isolated, ephemeral runners for untrusted PRs. Persistent self-hosted machines can retain modified files/processes between build/scan jobs and privileged reporting jobs; job-level token permissions do not isolate the machine itself. Keep preparation and scanner runners compatible when sharing Maven caches; see [Maven runner selection](../maven/prepare.md#runner-selection).

## Permissions

The current reusable workflow declares optional publishing and commenting jobs with write permissions. Its caller must allow `contents: write` and `pull-requests: write`, as shown above, even when those features are disabled. GitHub does not allow called workflows to elevate the caller's permissions.

Planning, scanner, and report-generation jobs explicitly use only `contents: read`. Privileged comment/publication jobs do not check out consumer code. PR comments are skipped for forks and Dependabot; repository/organization policy controls the token permissions actually available to those runs. `pull_request_target` executions are rejected. Do not pass publishing credentials through `secrets: inherit`.

## Component configuration

Copy the [configuration example](../../examples/security/configs/components.yml) to `.github/components.yml` in the caller and adapt its paths:

```yaml
components:
  api:
    paths:
      - apps/api

  web:
    paths:
      - apps/web
    dependency-paths:
      - pnpm-lock.yaml
      - package.json

  mobile:
    paths:
      - apps/mobile
    dependency-paths:
      - pnpm-lock.yaml
      - package.json

full-scan-on-change:
  - pnpm-workspace.yaml
  - .semgrepignore
  - .github/workflows
```

Then set the workflow inputs:

```yaml
with:
  library-ref: v1.3.0
  config-file: .github/components.yml
  mode: selective
```

| Attribute | Meaning |
|---|---|
| `components` | Mapping of user-defined component names to scan paths. |
| `paths` | Required nonempty list of source files/directories. Both scanners inspect these scopes. |
| `dependency-paths` | Optional extra files/directories for Trivy, such as shared lockfiles outside a component. |
| `full-scan-on-change` | Optional paths whose changes request a complete repository scan. |

Paths are repository-relative literal files/directories, not globs. Directory matches include descendants and respect boundaries: `apps/web` does not match `apps/website`. All configured source/dependency targets must exist within the repository. Unknown attributes, duplicate YAML keys, absolute paths, traversal, and symlink escapes are rejected. Remove deleted component paths from the configuration.

### Automatic selection

A change to a component source or dependency path selects that component. A shared lockfile change selects every component declaring it. Identical Trivy targets are scanned once; findings and coverage retain an entry for each associated component. Totals therefore count component-attributed findings, not globally unique advisories. Different nested/overlapping targets and Semgrep scopes remain independent.

PR selection compares the merge base of the PR base/head commits; pushes compare before/after commits. Renames include old/new paths, and deletions are considered. Missing/zero revisions, unavailable Git history, and unsupported events conservatively fall back to a full repository scan.

Changing `config-file` itself always requests a full scan, even if it is not listed under `full-scan-on-change`. Those trigger paths also request full scans. Files outside all configured scopes/triggers select nothing: declare infrastructure and root policy/manifest paths as appropriate.

When nothing is selected, scanner jobs are skipped and reports say `SKIPPED`; that is not a claim that the repository is vulnerability-free. Missing results for expected scans still produce `INCOMPLETE`.

### Caller-controlled selection

If existing CI already identifies affected components, pass their names:

```yaml
with:
  library-ref: v1.3.0
  config-file: .github/components.yml
  components: '["web","mobile"]'
```

This bypasses detection and full-scan triggers. The caller must include all affected consumers of shared files. Unknown names fail validation. Explicit `components: '[]'` selects nothing.

For direct scopes without a configuration file:

```yaml
with:
  library-ref: v1.3.0
  targets: >-
    [{"name":"web","paths":["apps/web"],"dependency-paths":["pnpm-lock.yaml"]}]
```

### Full audits

Set `mode: full` to scan `.` regardless of configuration/selectors. A full scan is labeled `repository`; it does not map findings back to configured components. Automatic full-scan fallbacks use the same label. The caller controls scheduling, as demonstrated in the [combined example](../../examples/security/security-analysis.yml).

There is a maximum of 64 configured components and 256 scan jobs. Up to four scanner jobs run concurrently. Failures do not cancel the other matrix scans.

## Scanner configuration

**Semgrep CE** runs `semgrep scan --oss-only`, with metrics/version checks disabled and JSON output enabled. It supports the languages covered by CE and the selected rules, including Java, JavaScript/TypeScript, and Python. Registry rules require network access; local rule files can improve reproducibility. Repository Semgrep/Git ignore behavior applies. CE analysis is not equivalent to paid interfile analysis. See the [Semgrep CLI reference](https://docs.semgrep.dev/cli-reference).

**Trivy** runs filesystem scanning with `vuln,misconfig`; secret and license scanning are disabled. Supported lockfiles/manifests and IaC formats determine coverage. Dockerfiles are supported; dedicated GitHub Actions YAML policy coverage is not guaranteed. Configure appropriate Semgrep rules if workflow YAML checks are needed. Repository auto-loaded Trivy configuration/ignore files are disabled; use the exposed inputs. See [Trivy coverage](https://trivy.dev/docs/latest/scanner/misconfiguration/).

The scanner does not run Maven or package installation/build hooks. For Java dependency metadata, use [Maven preparation](../maven/prepare.md) or an existing build's Maven repository cache. The Trivy Action separately caches its vulnerability databases.

### Maven and offline resolution

Pass `maven-cache-key` from preparation to restore `~/.m2/repository` before Trivy runs. Online mode can fetch missing Maven metadata; a cold cache may encounter Maven Central HTTP 429. Respect `Retry-After` before retrying.

Offline mode disables remote dependency lookup, not vulnerability database updates. When a Maven cache key is supplied, offline mode requires an exact cache hit. A hit does not prove completeness: uncached transitive POMs can be silently omitted. Keep offline mode disabled until dependency coverage is verified. The scanner restores caches but does not save updates to the caller's entry.

## Reports and PR comments

Open the run's Summary for severity counts, coverage, scanner/component breakdown, priority findings, incomplete scans, and a download link. Download the `security-report` artifact for:

| File | Contents |
|---|---|
| `index.html` | Standalone offline dashboard with search, filters, reversible severity order, descriptions, locations, fixes, and advisory/source links. |
| `report.json` | Combined normalized findings, coverage, failures, counts, status, and policy decision. |
| `summary.md` | Actions/PR summary text. |
| Numbered JSON/status/log files | Raw scanner results, process outcomes, and Semgrep stderr. Trivy diagnostics remain in job logs. |
| `manifest.json`, `plan.json`, `selection.json` | Expected scan scopes and selection decision. |

Intermediate artifacts use the names `security-raw-plan` and `security-raw-ID`. Raw/combined artifacts share `retention-days`. Report HTML embeds assets locally, escapes scanner data, and restricts advisory links to HTTP(S); opening source/advisory links still needs network access. Source links use the scanned commit, including the merge commit on PR runs.

With `pr-comment: true`, the sticky-comment Action updates one managed comment per PR and skips unchanged content. Per-PR concurrency prevents concurrent duplicate creation. Older runs can finish after newer runs, so required checks should rely on the current run. Legacy comments from the earlier custom comment implementation may need one-time manual removal.

For persistent copies, enable `publish` in a trusted full-audit caller; see [publication](publish.md). Reports stay in the calling repository, never the public workflow library. Their contents may expose source snippets or dependency details; access follows the caller's artifact/Release visibility.

## CI enforcement

Severity order is `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`, `UNKNOWN`. The threshold includes its own level and higher levels; `NONE` disables findings-based failure. Semgrep `ERROR` maps to HIGH, `WARNING` to MEDIUM, and informational/inventory/experiment labels to INFO.

`enforce: false` disables finding-based failure; `fail-on-error: false` separately disables failure for incomplete scans. Reports are generated/uploaded before enforcement, so vulnerability findings do not suppress downloads. The final job also fails when report generation, optional commenting, or publication fails.

## Troubleshooting

| Symptom | Check |
|---|---|
| Component is `repository` | Full mode, a full-scan trigger/config change, or uncertain Git history selected a repository-wide scan. |
| INCOMPLETE | Inspect status files and scanner job logs for parsing, ruleset, image pull, network, or timeout errors. Each scan has a 20-minute timeout. |
| Maven HTTP 429 | Prepare/restore dependency metadata and honor the upstream retry delay. |
| Permission error before jobs start | Allow the permissions declared by the called workflow; organization/fork policy may restrict them. |
| No report after cancellation or checkout failure | Infrastructure/cancellation can prevent reporting; job logs are the fallback. |

Use one security-scan invocation per workflow run: artifact names are fixed. The default targets GitHub.com-hosted Ubuntu runners; custom Linux runners must meet the requirements above. GHES is not covered. Scanner/ruleset exclusions and ecosystem limits still apply; a successful scan does not guarantee every file/dependency was analyzed.
