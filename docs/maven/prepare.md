# Maven preparation

[Workflow source](../../.github/workflows/maven-prepare.yml) · [Workflow catalog](../../README.md#workflows)

Prepare Maven dependencies and locally built module artifacts, then expose a verified cache key for downstream jobs. Supports independent projects and multi-module reactors. Use it with [security scanning](../security/scan.md#maven-and-offline-resolution) or other jobs that need a populated Maven repository.

## Usage

```yaml
name: Maven security

on:
  pull_request:
  push:

permissions:
  contents: write
  pull-requests: write

jobs:
  prepare-maven:
    uses: youpi0214/github-workflows/.github/workflows/maven-prepare.yml@v1.3.0
    with:
      library-ref: v1.3.0
      pom-files: |
        apps/api/pom.xml
      java-version: "21"
      skip-tests: true

  security:
    needs: prepare-maven
    uses: youpi0214/github-workflows/.github/workflows/security-scan.yml@v1.3.0
    with:
      library-ref: v1.3.0
      maven-cache-key: ${{ needs.prepare-maven.outputs.cache-key }}
      trivy-offline-scan: false
```

Adapt the POM paths to the caller and use the same published version in workflow references and `library-ref`. The security workflow's permissions are shown above; Maven preparation itself requires only contents read access. An existing build can also provide a compatible dependency cache instead of adding preparation.

## Inputs

| Input | Type | Default | Description |
|---|---|---|---|
| `runner` | string | `ubuntu-24.04` | Single Linux runner label used for jobs. |
| `library-ref` | string | **Required** | Library version tag matching the workflow reference. |
| `pom-files` | string | **Required** | Newline-separated explicit POM entry points, in preparation order. List each reactor root once. |
| `java-version` | string | `21` | Java version accepted by setup-java. |
| `java-distribution` | string | `temurin` | Java distribution accepted by setup-java. |
| `maven-goals` | string | `install` | Whitespace-separated lifecycle phases/plugin goals, such as `clean install` or `dependency:resolve`. CLI flags and shell expressions are rejected. |
| `profiles` | string | `""` | Enabled profile names separated by commas or whitespace. |
| `skip-tests` | boolean | `false` | Skip test execution with `-DskipTests=true`; test sources are still compiled. |

## Outputs

| Output | Description |
|---|---|
| `cache-key` | Exact saved `~/.m2/repository` cache key. Exposed only after every project succeeds and the saved entry is verified available. |

Use `needs` to wait for preparation and pass this key to `maven-cache-key`. Ordering alone does not transfer files between jobs; the scanner explicitly restores the cache. If preparation fails, dependent jobs normally do not run.

## Runner selection

Preparation defaults to `ubuntu-24.04`. Override it with a single Linux runner label:

```yaml
with:
  library-ref: v1.3.0
  pom-files: apps/api/pom.xml
  runner: my-linux-runner
```

The runner must be available to the calling repository and provide Bash, Git, Python 3, the standard `mvn` executable, network access, and archive/cache tooling compatible with the pinned Actions. `setup-java` installs the requested JDK; it does not install Maven. The existing Linux implementation does not support Windows or macOS, and the input does not accept label arrays or runner-group objects.

The security workflow has its own `runner` input; Maven's choice is not automatically inherited by another reusable workflow call. Keep runner OS/architecture and cache compression tooling compatible across preparation and scanning. Cache keys include the preparation runner OS, and GitHub also versions caches according to their paths/compression.

This workflow executes project plugins and extensions. Use isolated, ephemeral runners for untrusted PR builds rather than persistent machines also used by privileged jobs.

## Permissions

The preparation job grants `contents: read` and disables persisted checkout credentials. It does not need Release or PR write permission. GitHub cache storage uses its own Actions cache access rules.

This job executes caller-provided Maven plugins and extensions as part of a real build. Do not pass publishing credentials or `secrets: inherit`. `pull_request_target` executions are rejected. No consumer code executes in a privileged publishing job.

## Project layouts

### One project

```yaml
pom-files: |
  apps/api/pom.xml
```

### Independent projects

```yaml
pom-files: |
  apps/api/pom.xml
  tools/importer/pom.xml
```

Each project runs once using the shared local Maven repository. Supply producers before consumers when separate projects depend on each other's locally installed artifacts. Duplicate entry points are removed while preserving order.

### Multi-module reactor

```text
backend/
├── pom.xml          # Declares library and api in <modules>
├── library/pom.xml
└── api/pom.xml
```

```yaml
pom-files: |
  backend/pom.xml
```

List only the reactor root. Maven discovers declared modules and builds them in dependency order. A parent used only for inheritance does not discover child projects unless it also declares them in `<modules>`.

POM paths must be existing files inside the caller repository. Absolute paths and symlink escapes are rejected. The maximum is 64 entry points. Preparation uses the selected runner's standard `mvn` executable, not project wrappers.

## Goals, profiles, and tests

The default `install` goal compiles, tests, packages, and installs project artifacts locally. This prepares sibling-module dependencies as well as external packages. It is slower than dependency resolution alone but more reliable for interdependent modules.

For projects needing only remote dependency metadata:

```yaml
maven-goals: dependency:resolve
```

`dependency:resolve` does not install sibling artifacts. Listing dependent POMs in order does not make it equivalent to `install`.

To avoid running tests already covered by another CI job:

```yaml
skip-tests: true
```

This sets `-DskipTests=true`, which normally still compiles test sources. It does not set `-Dmaven.test.skip=true`, which would also skip compilation. With the default `skip-tests: false`, tests run when included by the selected lifecycle, as they are with `install`.

To activate profiles:

```yaml
profiles: ci,integration
```

Goals and profiles are validated and passed as argument lists without shell evaluation. Arbitrary Maven flags, shell commands, private repository credentials, custom settings, and wrapper execution are not exposed by this interface. Each POM runs from its own directory. Each command has a 30-minute timeout; the job has a 60-minute timeout. Separate calls are needed for different Java versions, with corresponding downstream scanner scopes/cache keys; multiple prepared caches are not automatically merged.

## Cache behavior

Preparation restores a compatible earlier cache, then **always runs Maven**, including after a hit. Skipping an `install` build on a POM-only cache hit could leave stale sibling-module artifacts after source changes.

The restore prefix fingerprints all repository POMs, Maven `.mvn` configuration, explicit entry points, Java settings, goals, profiles, and test-skipping choice. Final keys additionally include the source revision, run ID, and attempt, producing a fresh saved entry for each preparation. This preserves external dependency reuse while keeping built module artifacts tied to the current run.

Only `~/.m2/repository` is cached, not `settings.xml` or toolchains. Maven receives the repository path explicitly. The workflow saves only after successful preparation and verifies an exact saved cache before exposing its key. Cache scope, eviction, service availability, and storage limits remain controlled by GitHub. Per-run caches increase storage usage; monitor it for large projects.

## Troubleshooting

| Symptom | Check |
|---|---|
| Sibling dependency cannot be resolved | Use the reactor root with `install`, or list independent producers before their consumers. |
| Tests fail during preparation | Fix the tests or set `skip-tests: true` when test execution belongs elsewhere. Test compilation can still fail. |
| Maven Central returns HTTP 429 | Honor `Retry-After`. A cold preparation still needs network access; caching reduces repeat requests rather than bypassing rate limits. |
| Cache save/verification fails | Check Actions cache availability, permissions/policies, and storage limits. No usable key is exposed when verification fails. |
| Scanner cannot restore the key | Pass the exact output and run in a compatible branch/PR cache scope. |
| Project needs custom Maven behavior | Reuse an existing build's cache, or extend the public interface deliberately; arbitrary command injection is not supported. |

Cache availability does not prove complete dependency coverage. Profiles or project-specific resolution may need a normal build or different supported goals. Dynamic versions/snapshots follow Maven's normal update policies; preparation does not force `-U`. Keep Trivy offline resolution disabled until cached coverage is verified; missing transitive POMs can otherwise be silently omitted.
