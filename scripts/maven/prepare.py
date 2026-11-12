"""Plan and execute Maven dependency preparation without shell interpolation."""

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

MAX_PROJECTS = 64
GOAL_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]*")
PROFILE_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")


def project_poms(raw, root):
    """Validate explicit entry points and preserve their requested build order."""
    projects = []

    for value in raw.splitlines():
        value = value.strip()

        if not value:
            continue

        path = Path(value)
        resolved = (root / path).resolve()

        if (
            path.is_absolute()
            or value.startswith("-")
            or not resolved.is_relative_to(root)
        ):
            raise ValueError("POM paths must remain inside the caller repository")

        if not resolved.is_file():
            raise ValueError(f"POM file does not exist: {value}")

        relative = resolved.relative_to(root).as_posix()

        if relative not in projects:
            projects.append(relative)

    if not projects or len(projects) > MAX_PROJECTS:
        raise ValueError(f"pom-files must contain 1–{MAX_PROJECTS} explicit POM paths")

    return projects


def maven_goals(raw):
    """Accept lifecycle phases/plugin goals, not arbitrary Maven CLI options."""
    goals = shlex.split(raw)

    if not goals or any(not GOAL_PATTERN.fullmatch(goal) for goal in goals):
        raise ValueError(
            "maven-goals must contain phases or plugin goals, without flags"
        )

    return goals


def maven_profiles(raw):
    """Accept comma/whitespace-separated profile names without CLI injection."""
    profiles = raw.replace(",", " ").split()

    if any(not PROFILE_PATTERN.fullmatch(profile) for profile in profiles):
        raise ValueError("profiles must contain enabled Maven profile names")

    return list(dict.fromkeys(profiles))


def dependency_fingerprint(root, configuration):
    """Hash all POMs and Maven configuration, including child reactor modules."""
    files = set(configuration["pom-files"])

    for path in root.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue

        if path.name == "pom.xml" or ".mvn" in path.relative_to(root).parts:
            if not path.resolve().is_relative_to(root):
                raise ValueError(
                    "Maven configuration must remain inside the repository"
                )

            files.add(path.relative_to(root).as_posix())

    digest = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode())

    for filename in sorted(files):
        # Hash boundaries prevent ambiguous concatenations of filenames/content.
        digest.update(json.dumps(filename).encode())
        digest.update(hashlib.sha256((root / filename).read_bytes()).digest())

    return digest.hexdigest()


def create_plan(root, environment):
    """Create a fresh final cache key while allowing dependency-cache reuse."""
    skip_tests = environment.get("SKIP_TESTS", "false")

    if skip_tests not in ("true", "false"):
        raise ValueError("skip-tests must be true or false")

    configuration = {
        "pom-files": project_poms(environment["POM_FILES"], root),
        "goals": maven_goals(environment.get("MAVEN_GOALS", "install")),
        "profiles": maven_profiles(environment.get("MAVEN_PROFILES", "")),
        "skip-tests": skip_tests == "true",
        "java-version": environment.get("JAVA_VERSION", "21"),
        "java-distribution": environment.get("JAVA_DISTRIBUTION", "temurin"),
    }
    fingerprint = dependency_fingerprint(root, configuration)
    runner_os = environment["RUNNER_OS"]
    revision = environment["GITHUB_SHA"]
    run_id = environment["GITHUB_RUN_ID"]
    attempt = environment["GITHUB_RUN_ATTEMPT"]

    if not re.fullmatch(r"[A-Za-z0-9_-]+", runner_os):
        raise ValueError("invalid runner operating system")

    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", revision):
        raise ValueError("invalid source revision")

    if not run_id.isdigit() or not attempt.isdigit():
        raise ValueError("invalid workflow run identity")

    prefix = f"maven-prepared-v1-{runner_os}-{fingerprint}-"
    cache_key = f"{prefix}{revision}-{run_id}-{attempt}"

    return dict(configuration, **{"cache-key": cache_key, "restore-prefix": prefix})


def maven_command(pom, configuration, repository):
    """Use the standard Maven executable and the shared dependency repository."""
    command = [
        "mvn",
        "--batch-mode",
        "--no-transfer-progress",
        "--file",
        str(pom),
        f"-Dmaven.repo.local={repository}",
        "-DskipTests=" + str(configuration["skip-tests"]).lower(),
    ]

    if configuration["profiles"]:
        command.extend(["--activate-profiles", ",".join(configuration["profiles"])])

    return command + configuration["goals"]


def prepare_projects(root, configuration, repository):
    """Always prepare every entry point; previous caches may contain old modules."""
    for relative in configuration["pom-files"]:
        pom = root / relative
        print(f"Preparing Maven project: {relative}", flush=True)
        command = maven_command(pom, configuration, repository)
        subprocess.run(command, cwd=pom.parent, check=True, timeout=1800)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "run"))
    arguments = parser.parse_args()
    root = Path(os.environ["SOURCE"]).resolve()
    plan_file = Path(os.environ["MAVEN_PLAN"])

    if arguments.operation == "plan":
        configuration = create_plan(root, os.environ)
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text(json.dumps(configuration, indent=2))

        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"cache-key={configuration['cache-key']}\n")
            output.write(f"restore-prefix={configuration['restore-prefix']}\n")

        return

    configuration = json.loads(plan_file.read_text())
    repository = Path.home() / ".m2" / "repository"
    prepare_projects(root, configuration, repository)


if __name__ == "__main__":
    main()
