# Reusable security analysis

## Architecture and trust

`security-scan.yml` separates planning, matrix scans, report aggregation, optional comments/publication, and final enforcement. `plan.py` validates target paths and configuration, then records every expected scanner/scope. Up to four matrix jobs run concurrently, with a maximum of 256 scan jobs per invocation. Each scope runs on a fresh hosted runner. Matrix failure does not cancel other scans.

The internal composite Action `actions/security-scan/action.yml` executes Semgrep CE using the documented `semgrep scan` container command and runs Trivy through [aquasecurity/trivy-action](https://github.com/aquasecurity/trivy-action), including its built-in database caching. Semgrep has a read-only source mount, dropped container capabilities, and no injected GitHub token. Trivy runs natively with the scan job's read-only GitHub permissions. Both scanners use a 20-minute scan timeout. Neither scanner executes repository build scripts, Maven, or npm lifecycle hooks; installing scanner tools is independent of consumer dependencies.

Raw JSON and per-job status files are uploaded as `security-raw-ID` artifacts; the expected manifest and component plan are in `security-raw-plan`. Semgrep stderr is captured in a numbered log; Trivy diagnostics are in the scanner job log. `report.py` joins these artifacts, marks absent or unsuccessful scan jobs incomplete, and generates HTML, JSON, and Markdown. Overlapping identical findings within a component are deduplicated. Shared findings assigned to different components remain visible in each component's count.

Privileged reporting jobs never check out consumer code. Comments use [marocchino/sticky-pull-request-comment](https://github.com/marocchino/sticky-pull-request-comment) with PR write permission. Release uploads use [softprops/action-gh-release](https://github.com/softprops/action-gh-release) with contents write permission, after an inline full-scan completeness check. Custom comment and Release API scripts are unnecessary. The final job enforces policy after reporting, even when other jobs fail. All jobs use GitHub-hosted Ubuntu 24.04. Use one invocation per caller run (artifact name `security-report`). Do not pass secrets with `secrets: inherit`.

Calls from `pull_request_target` are rejected. Fork PRs and Dependabot PRs do not get comments; reports remain available as artifacts and summaries. No privileged follow-up workflow executes PR code. Protect caller workflows and library revision inputs with normal code review. Never allow an untrusted dispatch input to choose `library-ref`. Public caller artifacts and Releases are public: disable persistent publication when findings must remain private. Reports always stay in the **calling repository**, never in this library repository.

## Reporting code organization

`report.py` reads workflow configuration, assembles the report, and writes GitHub runner outputs. The `scripts/security/reporting/` package contains the supporting modules:

| File | Responsibility |
|---|---|
| `findings.py` | Normalize Semgrep and Trivy data into the common finding structure |
| `results.py` | Load artifacts, track incomplete scans, deduplicate, and sort findings |
| `policy.py` | Evaluate severity thresholds and scanner error enforcement |
| `rendering.py` | Prepare safe links and generate HTML, JSON, and Markdown files |
| `dashboard.html` | Standalone dashboard template |

Scanner normalization and policy evaluation do not read workflow environment variables or write files. Runtime configuration stays in `report.py`. Tests import the responsible modules directly and exercise the unchanged command-line entry point for complete reports.

## Inputs and outputs

| Input | Default | Meaning |
|---|---|---|
| `library-ref` | required | Published version tag matching the workflow reference, for example `v1.0.0` |
| `mode` | `selective` | `selective` or `full` |
| `targets` | `[{"name":"application","paths":["."]}]` | Component array; optional `dependency-paths` array extends Trivy scopes |
| `scanners` | `["semgrep","trivy"]` | Enabled scanners as JSON array, at least one |
| `semgrep-rules` | `["p/default"]` | JSON array of registry rulesets or source-relative local rule paths |
| `trivy-ignore-unfixed` | `false` | Exclude vulnerabilities without a known fix |
| `trivy-skip-dirs` | `[]` | JSON string array of Trivy directory exclusions |
| `fail-severity` | `HIGH` | Fail on this severity or higher; CRITICAL, HIGH, MEDIUM, LOW, INFO, UNKNOWN, NONE |
| `enforce` | `true` | Enforce findings threshold |
| `fail-on-error` | `true` | Independently fail on failed/incomplete scans |
| `pr-comment` | `false` | Update one bot-owned PR comment for same-repository PRs |
| `publish` | `false` | Publish complete trusted full scans |
| `retention-days` | `30` | Actions artifact lifetime, subject to repository policy |

Outputs: `status` is CLEAN, FINDINGS, or INCOMPLETE; `failed` is the policy decision as a boolean string; `artifact-id` is the uploaded artifact ID. A job infrastructure failure may prevent outputs; final enforcement fails closed in that case. Disabling findings enforcement does not disable error enforcement. UNKNOWN is below INFO; choose UNKNOWN to include every finding. Semgrep ERROR → HIGH, WARNING → MEDIUM, INFO → INFO. These are prioritization mappings, not CVSS claims.

## Selective and full scanning

The caller owns change detection, schedules, and branch choices. Selective targets must exist within the checked-out repository; absolute paths, option-like paths, and symlink escapes are rejected. Each component needs a unique name and at least one source path. `dependency-paths` can contain additional files or directories, including root lockfiles. A changed shared lockfile should cause the caller to select **all affected consumers**. Root-level dependency findings cannot always be attributed to a single package; label a separate shared scope when useful.

Full mode replaces the target list with one `repository` component at `.`. Both scanners scan all supported, non-ignored files under their selected scopes; this is not a changed-line scan. The caller decides how often to run it. A skipped change-detection job is not a clean scan.

## Scanner configuration

Semgrep uses `semgrep scan --oss-only`, not account-based `semgrep ci`. Registry rules require network access but no subscription; local rule files can make rules reproducible. Metrics and version checks are disabled. Ruleset coverage determines which Java, JS/TS, Python, and other supported source constructs are examined. Repository `.semgrepignore` and Git ignore behavior apply. Errors returned in Semgrep JSON mark the scan incomplete, while normal language/file exclusions do not.

Trivy runs `fs --scanners vuln,misconfig`; secret and license scanners are disabled. All severities are collected before enforcement. Repository auto-loaded config/ignore files are disabled so policy is explicit in caller inputs. The Trivy Action manages daily database caches and restores previous entries when needed; Trivy handles database freshness. Tool and database caching are maintained by the upstream Action. No builds are run. Supported lockfiles such as pnpm/npm and Poetry are analyzed directly; Maven source scanning has limits and can depend on resolvable dependency metadata. It is not equivalent to scanning a fully resolved Java artifact or container image.

Dockerfiles and supported IaC are inspected by Trivy's built-in checks. GitHub Actions YAML is included in repository scopes, but **Trivy does not guarantee dedicated GitHub Actions policy coverage**; include Semgrep rules for workflow YAML (for example an appropriate reviewed registry ruleset). Neither scanner promises complete coverage of every language/configuration. No third scanner is added. Consult [Trivy supported misconfiguration formats](https://trivy.dev/docs/latest/scanner/misconfiguration/) and [Semgrep CLI behavior](https://docs.semgrep.dev/cli-reference) when configuring coverage.

## Reports and enforcement

The Summary contains scan coverage, counts by severity, scanner/component breakdown, priority findings, failures, and a run link. Download `security-report` from that run to obtain `index.html`, normalized `report.json`, raw numbered JSON, per-job `*.status.json` files, Semgrep logs, `manifest.json`, `plan.json`, and `summary.md`. The manifest records planned scans with a default failing exit code; status files record actual outcomes. Trivy diagnostics remain in the Actions job logs. Intermediate artifacts use the same configured retention as the final report. HTML opens locally with no external assets or network requirement. Search spans finding fields; filters select severity/scanner/component; the sort button reverses priority. Expand findings for descriptions, fixes, packages, and advisory links. Source links use the exact checkout commit (PR merge commit for PR runs).

Untrusted fields are serialized with script-closing characters escaped, rendered through DOM textContent, and only HTTP(S) advisory links are allowed. HTML is never executed by publishing/comment jobs. Raw scanner data may contain sensitive source snippets; choose artifact access and retention accordingly. Scanner errors and missing/malformed files mark INCOMPLETE. Reports are generated before policy enforcement, so findings do not suppress downloads.

## PR comments and permissions

Enable `pr-comment` and grant `pull-requests: write` in the caller. The sticky-comment Action creates or updates one comment identified by its `reusable-security-report` header and skips unchanged content. Existing comments created by the earlier custom script use a different marker; remove that legacy comment once when migrating to avoid retaining both. A per-PR concurrency group prevents duplicate creation. Fork and Dependabot runs skip commenting; do not switch to pull_request_target to circumvent this. Concurrent runs update on completion; an older run may finish last. Required GitHub checks should use the current run's enforcement result.

## Persistent reports

Enable `publish` and grant `contents: write` only in a trusted caller workflow. Publication requires full mode, complete scans, the repository's configured default branch, and a push, schedule, or workflow_dispatch event. Complete reports with findings can be published even when enforcement will fail. A separate fresh runner downloads the current run's artifact, validates report data with an inline Python step, and uploads fixed report filenames through the Release Action. No consumer checkout or artifact-provided code runs with write permission.

Historical Release tags are `security-report-RUN_ID-RUN_ATTEMPT`. `security-report-latest` contains replaceable latest assets without changing the repository's normal latest Release. Assets include HTML and normalized JSON; historical tags/assets remain. GitHub Release HTML assets generally require **downloading before opening interactively**. Release assets inherit the caller's visibility. There is no automatic history cleanup. `security-publish.yml` can be called separately using a current-run artifact ID and library-ref, but is intended to be reached through the full-scan orchestrator; it revalidates full-scan coverage and completeness. The publisher retains the `library-ref` input for caller compatibility, but no longer needs a library checkout. Only trusted workflows should receive contents write. Repositories enforcing immutable Releases cannot replace assets on `security-report-latest`; disable persistent publication unless replaceable report Releases are allowed.

## Troubleshooting and limits

- Inspect per-job status files, Semgrep logs, and Trivy Actions job logs for network, image pull, DB, ruleset, timeout, and scanner failures. Invalid targets/configuration fail closed with an incomplete report.
- Missing artifacts, failed report generation, or cancellation cannot guarantee a report; re-run the workflow. Logs are the fallback.
- GitHub Actions permissions can only be reduced by nested workflows. A read-only caller cannot publish or comment; use the separate scheduled example for write permissions.
- Artifact retention limits, disabled Actions, unavailable registry/network access, and API rate limits are repository operational constraints.
- Actions and scanner tools use explicit release versions; the Semgrep container uses a version tag rather than an immutable digest. Review scanner supply chain updates; registry rules and vulnerability databases evolve independently.
- This implementation targets GitHub.com and hosted Linux runners. Artifact v7/v8 and checkout v7 require modern runner support; GHES is not covered.
- Container execution could not be exercised in the development workspace because its user lacks Docker daemon access. Before rollout, run a real GitHub-hosted caller against representative language fixtures and review coverage and rule licenses.

## Versioning and validation

Select reusable workflows using version tags, never commit SHAs. Keep workflow `uses` and `library-ref` at the same published release version, for example `v1.0.0`. Published release tags must not be moved; publish a new version for updates. Review scanner releases, Action release versions, rule licenses, normalizer schema changes, and tests before upgrades. Backward-incompatible inputs/outputs require a major version; keep category-specific documentation with the implementation. CI tests normalization, malformed/empty/partial results, injection escaping, path containment, and workflow syntax. No account or paid service is required.
