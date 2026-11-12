# Maven dependency preparation

[`maven-prepare.yml`](../../.github/workflows/maven-prepare.yml) prepares one or more Maven projects and exposes a saved dependency cache to downstream jobs. It is an independent reusable workflow built from checkout, setup-java, cache Actions, and a small validation/execution helper. No security scanner is run by this workflow.

## Caller

```yaml
jobs:
  prepare-maven:
    uses: youpi0214/github-workflows/.github/workflows/maven-prepare.yml@v1.2.0
    with:
      library-ref: v1.2.0
      pom-files: |
        backend/pom.xml
        tools/importer/pom.xml
      java-version: "21"
      maven-goals: install
      skip-tests: true

  security:
    needs: prepare-maven
    uses: youpi0214/github-workflows/.github/workflows/security-scan.yml@v1.2.0
    with:
      library-ref: v1.2.0
      config-file: .github/security.yml
      maven-cache-key: ${{ needs.prepare-maven.outputs.cache-key }}
      trivy-offline-scan: false
```

Use a published version containing this workflow in all references; `v1.2.0` is illustrative, not a release created by this implementation. For scheduled audits, use `mode: full` in the security call. See the [complete Maven caller example](../../examples/security/maven.yml).

## Inputs and output

| Input | Default | Meaning |
|---|---|---|
| `library-ref` | required | Version tag matching the reusable workflow reference |
| `pom-files` | required | Newline-separated repository-relative POM entry points |
| `java-version` | `21` | Java version understood by setup-java |
| `java-distribution` | `temurin` | Java distribution understood by setup-java |
| `maven-goals` | `install` | Build projects and install artifacts locally; override with `dependency:resolve` when locally built artifacts are unnecessary |
| `profiles` | empty | Enabled profile names separated by commas or whitespace |
| `skip-tests` | `false` | Skip test execution with `-DskipTests=true`; test sources are still compiled |

The `cache-key` output identifies the freshly saved `~/.m2/repository`. It is published only after all projects succeed and the cache is verified available. A failed preparation does not return a usable cache key. The caller needs `contents: read`; the called job has no publishing permissions.

## Independent projects and reactors

List the root POM for each independent project in the desired preparation order. Duplicate entry points are removed. Paths must point to existing files inside the caller repository; absolute paths and symlink escapes are rejected. There is a maximum of 64 entry points.

For a multi-module reactor, list its root POM once. Maven discovers modules declared by `<modules>`; do not separately list those child POMs. A parent used only for inheritance does not automatically discover child projects.

`install` is the default so Maven builds projects and installs their artifacts locally, including reactor modules needed by their siblings. Preparation therefore takes longer than dependency resolution alone. Override with `dependency:resolve` when no locally built artifacts are required. This is an actual project build, not just a scan. Use `skip-tests: true` if tests already run elsewhere, understanding that `-DskipTests` normally still compiles test sources. If one independent entry point consumes another's installed artifacts, list the producer first and use `install`.

Tests run by default when the selected lifecycle includes them, as `install` does. `skip-tests: true` passes `-DskipTests=true`, which skips test execution but retains test compilation. This differs from `-Dmaven.test.skip=true`, which also skips test compilation and is not what this input sets.

Each entry runs once from its own POM directory with the standard hosted-runner `mvn` executable. Goals and profile names are validated and passed as argument lists without shell evaluation. Shell expressions, arbitrary Maven flags, wrapper execution, custom settings, and arbitrary command strings are not supported. Each Maven command has a 30-minute timeout; the entire job has a 60-minute timeout. Projects requiring different JDKs need separate calls and corresponding scanner scopes/cache keys; the workflow does not merge outputs from multiple preparation calls automatically.

## Cache behavior

Preparation restores compatible earlier caches as a performance aid, then **always runs Maven**, even after a cache hit. Skipping builds on a POM-only cache hit could reuse stale sibling-module artifacts after source changes.

The restore prefix includes the runner OS and a SHA-256 fingerprint of all repository `pom.xml` files, Maven `.mvn` configuration, explicit POM entry points, Java settings, goals, profiles, and test-skipping choice. The final key also includes the source revision, workflow run ID, and attempt number. Each run saves a fresh result, while source-only changes can reuse downloaded external dependencies. The source revision is cache identity metadata; reusable workflows are still selected by version tags.

Only `~/.m2/repository` is cached. Credential-bearing `settings.xml` files and toolchains are not cached. The prepared repository location is explicitly supplied to Maven so scanners can restore it at their normal local repository path. No cache is saved by this workflow after a Maven failure. GitHub's cache scope/visibility rules apply: the preparation and scanner jobs must run in a compatible branch/PR context. GitHub can evict caches later; downstream scanners retain their own cache-miss handling.

Run IDs make final cache entries fresh but increase cache storage usage; rely on normal GitHub cache expiration/eviction and monitor usage on larger projects. Dynamic dependency versions and snapshots can still need project-specific update policies; preparation does not force Maven's `-U` behavior.

## Trust and limits

This workflow checks out and executes the caller's Maven project, including its plugins and extensions. It uses read-only repository permissions, disables persisted checkout credentials, and rejects `pull_request_target` executions. Do not grant it publishing credentials or use `secrets: inherit`. It does not access other consumer repositories.

Preparation itself may encounter Maven Central rate limits on a cold cache. It reduces repeated remote work; it does not bypass HTTP 429 restrictions. Respect `Retry-After`, and use an existing prepared cache/build where possible.

A cache hit does not prove the complete dependency graph is present. Keep `trivy-offline-scan: false` until coverage is verified. Maven profiles and project-specific dependencies may require a different preparation goal or a normal build. Offline Trivy can omit uncached transitive metadata without failing.

## Development

Run `python3 -m unittest discover -s tests/maven -v`. Tests cover safe arguments, project selection, cache invalidation, preparation order, and failure propagation. The validation workflow additionally builds a controlled reactor with a sibling dependency and an independent project, then checks the installed artifacts. That integration test requires Maven, Java, and repository network access.
