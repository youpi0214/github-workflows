# Reusable GitHub workflows

Shared GitHub Actions workflows for software projects and monorepos. The security toolkit combines Semgrep Community Edition and Trivy with an offline HTML dashboard, Actions summaries, and optional PR comments and persistent reports. Maven preparation is available as a companion workflow.

## Workflows

| Workflow | Purpose | Documentation |
|---|---|---|
| [Security scan](.github/workflows/security-scan.yml) | Selective or full scanning, unified reports, and CI enforcement | [Usage and reference](docs/security/scan.md) |
| [Security publication](.github/workflows/security-publish.yml) | Historical and latest reports in the calling repository's Releases | [Usage and reference](docs/security/publish.md) |
| [Maven preparation](.github/workflows/maven-prepare.yml) | Build Maven projects/reactors and share prepared dependencies with scanners | [Usage and reference](docs/maven/prepare.md) |

## Usage

Add a caller workflow to your repository:

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
```

This scans the repository with both scanners and uploads the combined reports. See [component configuration](docs/security/scan.md#component-configuration) for monorepos, [Maven preparation](docs/maven/prepare.md#usage) for Java projects, and [publication](docs/security/publish.md#usage) for scheduled audits.

## Examples

- [Simple application](examples/security/simple.yml)
- [Selective scanning, Maven preparation, and scheduled full audits](examples/security/security-analysis.yml)
- [Component configuration](examples/security/configs/components.yml)

Examples use version tags. Choose a published release containing the features you need and keep the workflow reference and `library-ref` identical. `library-ref` selects the supporting scripts and Actions checked out by the workflow. Review release notes before updating; use a new major version for incompatible interfaces.

## License

[Apache License 2.0](LICENSE).
