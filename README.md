# Reusable GitHub workflows

A modular library for CI/CD, testing, security, deployment, and repository automation. Security is the first implemented category; categories have independent workflow names and purpose-specific scripts, documentation, and examples.

| Workflow | Purpose | Documentation |
|---|---|---|
| [security-scan.yml](.github/workflows/security-scan.yml) | Semgrep CE and Trivy, unified reports, optional PR comments, enforcement | [Security guide](docs/security/README.md) |
| [security-publish.yml](.github/workflows/security-publish.yml) | Publish trusted full reports to caller Releases; normally invoked by security-scan | [Publication](docs/security/README.md#persistent-reports) |
| [maven-prepare.yml](.github/workflows/maven-prepare.yml) | Prepare independent Maven projects or multi-module reactors and expose a dependency cache | [Maven guide](docs/maven/README.md) |

Start with [the simple caller](examples/security/simple.yml). Use a published version tag, such as `v1.0.0`, in both `uses` and `library-ref`. Both must select the **same release version**. The basic examples use `v1.0.0`; the configuration-based monorepo example illustrates `v1.1.0`, and the Maven preparation example illustrates `v1.2.0`. Publish a release containing the relevant interface before using it, and select that published version in both references. The consumer needs no scripts or reporting dependencies.

Public interfaces use kebab-case inputs, JSON for structured data, and explicit policy inputs. Future categories should follow these conventions without coupling to security scripts. Version breaking interfaces with a new major release, maintain a changelog, and publish reviewed semantic tags; consumers must select reusable workflows by version number and review update PRs. Never use a commit SHA to select a reusable workflow version. Workflow source and checked-out scripts must always use the same release version. Published release tags must not be moved. YAML Action references also use explicit release version numbers. Scanner versions are fixed in `actions/security-scan/action.yml`; review them and rules/DB changes during upgrades.

Maven preparation uses `scripts/maven/prepare.py` to validate inputs, compute cache identity, and invoke Maven safely. Security-specific custom code is limited to scan planning (`scripts/security/plan.py`) and unified reporting (`scripts/security/report.py` and the `scripts/security/reporting/` package). Scanner execution, PR comments, and Release uploads are composed from workflow steps and established Actions.

Development: `python3 -m unittest discover -s tests/security -v`, `python3 -m unittest discover -s tests/maven -v`, then `actionlint -shellcheck= .github/workflows/*.yml examples/security/*.yml`. Install `scripts/security/requirements.txt` before running the selection tests; YAML configuration uses pinned PyYAML. The reusable workflow installs it automatically when needed. See the guide for limitations and operational checks before adoption.

Library releases use [Release Please](https://github.com/googleapis/release-please-action) to propose semantic versions and changelogs in a reviewable PR, then publish a version tag and GitHub Release after it merges.

## Security configuration

Copy [the component configuration](examples/security/configs/components.yml) to `.github/security.yml` in the caller, then use [the small monorepo caller](examples/security/security-analysis.yml). No inline Python or separate change-detection job is required.

```yaml
jobs:
  security:
    uses: youpi0214/github-workflows/.github/workflows/security-scan.yml@v1.1.0
    with:
      library-ref: v1.1.0
      config-file: .github/security.yml
      mode: selective
```

The library defines the attributes; component names and path values belong to the caller:

```yaml
components:
  web:
    paths:
      - apps/web
    dependency-paths:
      - pnpm-lock.yaml

  mobile:
    paths:
      - apps/mobile
    dependency-paths:
      - pnpm-lock.yaml

full-scan-on-change:
  - .semgrepignore
  - pnpm-workspace.yaml
  - .github/workflows
```

`paths` is a required nonempty list of source files/directories. `dependency-paths` optionally extends Trivy scans to shared manifests, lockfiles, or directories. Paths are repository-relative, literal file/directory names; directory matching includes descendants but respects boundaries (`apps/web` does not match `apps/website`). Globs, absolute paths, traversal, duplicate YAML keys, and unsupported configuration attributes are rejected. All configured source and dependency targets must exist within the repository, including symlink resolution. Remove deleted components from the configuration rather than leaving stale target paths.

| Input | Behavior |
|---|---|
| `config-file` | Read the caller's YAML component definitions |
| `mode: selective` | Automatically select components affected by source or dependency-path changes |
| `components: '["web","mobile"]'` | Override detection and select these configured names; requires `config-file` |
| `components: '[]'` | Explicitly select no components |
| `mode: full` | Scan the entire repository, ignoring component selectors and configuration |
| `targets` | Existing JSON target interface; cannot be combined with `config-file` in selective mode |

When the root lockfile changes, every component declaring it is selected. A change under `full-scan-on-change` selects a **full repository scan**, including files outside configured component paths. Changes to `config-file` itself always trigger a full scan, without requiring it in that list. Files outside declared component and trigger paths do not select a component; declare infrastructure, root manifests, and security policy paths as appropriate for your repository.

For pull requests, detection uses the merge base of the PR base and head commits. Pushes compare the before/after commits. Renames consider both old and new paths, and deletions are included. The planning checkout fetches complete history. A missing/zero comparison revision, unavailable history, or unsupported event conservatively falls back to a full repository scan. Scheduled and manual audit callers should explicitly use `mode: full`.

Existing change detection can supply names without duplicating path definitions:

```yaml
with:
  library-ref: v1.1.0
  config-file: .github/security.yml
  components: ${{ needs.changes.outputs.components }}
```

This is an explicit override: the caller must include every affected component, including consumers of changed shared dependencies. Automatic detection and full-scan triggers are bypassed when names are supplied. Unknown names fail validation.

If nothing is selected, scanner jobs are skipped and reports say **SKIPPED**, rather than claiming a clean scan. The plan, empty manifest, and `selection.json` marker record that decision; missing results from an expected scan still produce INCOMPLETE. Summaries, optional PR comments, and artifacts remain available. SKIPPED reports are not published persistently.

Without `config-file`, existing explicit `targets` callers behave as before. Omitting both still scans `.` with the `application` component. The public `status` output now also supports SKIPPED, alongside CLEAN, FINDINGS, and INCOMPLETE.

These configuration-based inputs require a release containing this implementation; `v1.1.0` above is an example release number, not a tag created by these changes.

## Maven dependency caching and offline scanning

The reusable scan accepts two optional inputs:

| Input | Default | Behavior |
|---|---|---|
| `maven-cache-key` | empty | Restore the caller's cached `~/.m2/repository` before each Trivy scan; no Maven restoration when omitted |
| `trivy-offline-scan` | `false` | Set Trivy's `TRIVY_OFFLINE_SCAN` to disable remote dependency-resolution requests |

Use [the reusable Maven preparation workflow](docs/maven/README.md) to keep the caller small; see [the complete example](examples/security/maven.yml). It sets up Java, restores dependencies, prepares each listed project, and saves a fresh repository cache. The security job waits for preparation and passes its output key:

```yaml
security:
  needs: prepare-maven
  uses: youpi0214/github-workflows/.github/workflows/security-scan.yml@v1.2.0
  with:
    library-ref: v1.2.0
    maven-cache-key: ${{ needs.prepare-maven.outputs.cache-key }}
    trivy-offline-scan: false
```

Use an actual published version containing these inputs in both references. An existing Maven build can also supply a cache instead. With the reusable preparer, supply reactor root POMs through `pom-files`. The default `install` goal builds projects and installs sibling-module artifacts locally. Tests run by default; `skip-tests: true` skips execution while retaining test compilation. Use `maven-goals: dependency:resolve` when locally built artifacts are unnecessary. It computes configuration-aware cache prefixes and fresh per-run keys automatically. Builds and Maven plugins execute only in the caller's build job; the reusable scanner does not execute them. Cache only `~/.m2/repository`, not credential-bearing `settings.xml` files.

Maven caches are scoped by GitHub's cache access rules and must be available to the scanner's branch/PR. Matching the key alone does not transfer files between jobs: the library restores them through `actions/cache/restore`. It does not save or modify the caller's cache entry. The Trivy database cache remains separate and is still managed by the Trivy Action.

With online scanning (the default), a missing Maven cache permits remote resolution and may still encounter Maven Central HTTP 429. Restore a populated cache to reduce remote requests; after a rate limit, respect the server's `Retry-After` delay rather than immediately retrying.

Enable offline scanning only after confirming the Maven cache contains the complete required dependency metadata. When `maven-cache-key` is supplied, offline mode requires an exact cache hit and fails on a miss or prefix-only match. This checks cache availability, not dependency-tree completeness: Trivy can silently skip transitive dependencies whose POMs are absent. An offline scan without a Maven cache key is permitted for other ecosystems, but should not be used for an unprepared Maven project. Offline dependency resolution does not disable vulnerability database updates. See [Trivy's Java documentation](https://www.trivy.dev/docs/latest/guide/coverage/language/java/).

GitHub cache entries are immutable. If an existing entry lacks required metadata, populate dependencies and save under a new key rather than expecting a cache hit to overwrite it.

Identical Trivy targets shared by components are scanned once, including equivalent `./` path spellings. The manifest records all associated `components`, while preserving the first `component` field for compatibility. Findings and coverage retain one entry per affected component, so overall finding totals include component attributions rather than counting unique advisories globally. Failures name all affected components. Semgrep scopes and different nested/overlapping directory targets remain independent; only identical Trivy targets are deduplicated.

The scanner smoke workflow exercises both the default online path and an offline scan with restoration of a controlled Maven cache. It does not prove completeness of a consumer project's Maven dependency tree.

## Protecting release-managed files

The `Release-managed files` PR check rejects changes to `.release-please-manifest.json` and `version.txt` unless the PR belongs to the configured release account, comes from this repository's expected Release Please branch, and its head commit is attributed to that account. Renaming a managed file is also checked. Manual changelog corrections and release configuration updates remain allowed.

The account defaults to `github-actions[bot]`. If `RELEASE_PLEASE_TOKEN` belongs to another account, set the repository Actions variable `RELEASE_PLEASE_ACTOR` to that account's GitHub login. Use a dedicated release account if you want to distinguish automated updates from your own PRs. Commit authorship attribution catches accidental manual commits but is not cryptographic proof of which workflow generated a commit; keep release PRs under normal review.

To enforce this on the default branch:

1. Merge the protection workflow, its script, and the initial release configuration first. The workflow loads policy code from the PR's base commit, so the first setup PR cannot load the new script before it is merged. Enable the required check after this one-time bootstrap.
2. Open **Settings → Rules → Rulesets**, create an active branch ruleset, and target the default branch.
3. Require a pull request before merging. Add `Release-managed files` as a required status check, choosing GitHub Actions as the expected source if offered. The check must run once before it appears in the picker.
4. Require branches to be up to date before merging, disable force pushes/deletions, and restrict bypass privileges. A narrowly controlled maintainer bypass provides a deliberate recovery path.
5. Protect changes to `.github/workflows/` and `scripts/releases/` through maintainer review, for example using CODEOWNERS and required code-owner approval where appropriate. A PR check alone cannot defend against someone authorized to replace the check itself or bypass repository rules.

No path filter is used on the protection workflow, so ordinary PRs also receive a passing required check. Its token is read-only and it never checks out or executes PR head code. Titles and labels are not trusted as authorization.

When Release Please uses `GITHUB_TOKEN`, its PR creation and updates do not automatically trigger PR workflows. Close and reopen the release PR after each bot update to run checks, or supply a repository-scoped `RELEASE_PLEASE_TOKEN` with Contents, Issues, and Pull requests read/write permissions for automatic checks. Enable Actions to create pull requests in repository settings. Keep branch protection enabled when resolving missing checks.

Run the policy tests with `node --test tests/releases/*.test.cjs`.