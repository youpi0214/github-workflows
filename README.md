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
