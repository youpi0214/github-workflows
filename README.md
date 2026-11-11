# Reusable GitHub workflows

A modular library for CI/CD, testing, security, deployment, and repository automation. Security is the first implemented category; categories have independent workflow names and purpose-specific scripts, documentation, and examples.

| Workflow | Purpose | Documentation |
|---|---|---|
| [security-scan.yml](.github/workflows/security-scan.yml) | Semgrep CE and Trivy, unified reports, optional PR comments, enforcement | [Security guide](docs/security/README.md) |
| [security-publish.yml](.github/workflows/security-publish.yml) | Publish trusted full reports to caller Releases; normally invoked by security-scan | [Publication](docs/security/README.md#persistent-reports) |

Start with [the simple caller](examples/security/simple.yml). Use a published version tag, such as `v1.0.0`, in both `uses` and `library-ref`. Both must select the **same release version**. The examples use `v1.0.0`; publish that release tag before using them, or select another published version. The consumer needs no scripts or reporting dependencies.

Public interfaces use kebab-case inputs, JSON for structured data, and explicit policy inputs. Future categories should follow these conventions without coupling to security scripts. Version breaking interfaces with a new major release, maintain a changelog, and publish reviewed semantic tags; consumers must select reusable workflows by version number and review update PRs. Never use a commit SHA to select a reusable workflow version. Workflow source and checked-out scripts must always use the same release version. Published release tags must not be moved. YAML Action references also use explicit release version numbers. Scanner versions are fixed in `actions/security-scan/action.yml`; review them and rules/DB changes during upgrades.

Custom code is limited to scan planning (`scripts/security/plan.py`) and unified reporting (`scripts/security/report.py` and the `scripts/security/reporting/` package). Scanner execution, PR comments, and Release uploads are composed from workflow steps and established Actions.

Development: `python3 -m unittest discover -s tests/security -v`, then `actionlint -shellcheck= .github/workflows/*.yml examples/security/*.yml`. No Python packages are required. See the guide for limitations and operational checks before adoption.

Library releases use [Release Please](https://github.com/googleapis/release-please-action) to propose semantic versions and changelogs in a reviewable PR, then publish a version tag and GitHub Release after it merges.

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
