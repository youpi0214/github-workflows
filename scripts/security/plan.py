"""Validate caller configuration and prepare the scanner job matrix."""

import json
import os
from pathlib import Path

if __package__:
    from . import selection
else:
    import selection

SUPPORTED_SCANNERS = ("semgrep", "trivy")
MAX_COMPONENTS = 64
MAX_SCAN_JOBS = 256


def validate_target_path(path, repository_root):
    """Reject option-like paths, missing targets, and repository escapes."""
    error_message = "target must exist inside repository: " + str(path)

    if not isinstance(path, str) or path.startswith("-"):
        raise ValueError(error_message)

    if Path(path).is_absolute():
        raise ValueError(error_message)

    target = repository_root / path

    # Resolve symlinks before checking that the target stays in the repository.
    if not target.resolve().is_relative_to(repository_root):
        raise ValueError(error_message)

    if not target.exists():
        raise ValueError(error_message)


def validate_component_paths(component, repository_root):
    """Require source paths and validate optional shared dependency scopes."""
    source_paths = component.get("paths")

    if not isinstance(source_paths, list) or not source_paths:
        raise ValueError("each component needs paths")

    for field in ("paths", "dependency-paths"):
        paths = component.get(field, [])

        if not isinstance(paths, list):
            raise ValueError("paths must be lists")

        for path in paths:
            validate_target_path(path, repository_root)


def targets(raw, mode, root):
    """Resolve full or selective targets and validate each component."""
    if mode not in ("full", "selective"):
        raise ValueError("mode must be full or selective")

    if mode == "full":
        components = [{"name": "repository", "paths": ["."], "dependency-paths": []}]
    else:
        components = json.loads(raw)

    if not isinstance(components, list) or not components:
        raise ValueError("targets must contain a nonempty component list")

    if len(components) > MAX_COMPONENTS:
        raise ValueError(f"targets must contain at most {MAX_COMPONENTS} components")

    component_names = set()
    for component in components:
        if not isinstance(component, dict):
            raise ValueError("each component must be an object")

        name = component.get("name")
        if not isinstance(name, str) or not name or name in component_names:
            raise ValueError("component names must be nonempty and unique")

        component_names.add(name)
        validate_component_paths(component, root)

    return components


def parse_scanners(raw):
    """Read the enabled scanner list without changing its configured order."""
    scanners = json.loads(raw)

    if not isinstance(scanners, list) or not scanners:
        raise ValueError("scanners must contain semgrep and/or trivy")

    if any(scanner not in SUPPORTED_SCANNERS for scanner in scanners):
        raise ValueError("scanners must contain semgrep and/or trivy")

    return scanners


def validate_semgrep_rules(rules):
    """Require at least one ruleset and reject option-like rule values."""
    if not isinstance(rules, list) or not rules:
        raise ValueError("rules must be a nonempty JSON string list")

    for rule in rules:
        if not isinstance(rule, str) or not rule or rule.startswith("-"):
            raise ValueError("rules must be a nonempty JSON string list")


def validate_trivy_skip_dirs(skip_dirs):
    """Allow an empty exclusion list while requiring string entries."""
    if not isinstance(skip_dirs, list):
        raise ValueError("trivy-skip-dirs must be a JSON string array")

    if any(not isinstance(path, str) for path in skip_dirs):
        raise ValueError("trivy-skip-dirs must be a JSON string array")


def build_plan(components, scanners):
    """Record every expected scan so missing matrix artifacts fail closed."""
    records = []
    unique_scanners = dict.fromkeys(scanners)

    for component in components:
        for scanner in unique_scanners:
            paths = component["paths"]

            if scanner == "trivy":
                paths = paths + component.get("dependency-paths", [])

            for target in dict.fromkeys(paths):
                scan_id = len(records)
                record = {
                    "id": scan_id,
                    "scanner": scanner,
                    "component": component["name"],
                    "target": target,
                    "file": f"{scan_id}.json",
                    "path-prefix": "source/" if scanner == "trivy" else "",
                    "exit_code": -1,
                }
                records.append(record)

    if len(records) > MAX_SCAN_JOBS:
        raise ValueError(f"scan plan exceeds GitHub's {MAX_SCAN_JOBS}-job matrix limit")

    return records


def resolve_components(repository_root):
    """Keep explicit targets compatible and resolve configuration-based selection."""
    mode = os.environ["MODE"]
    config_file = os.environ.get("CONFIG_FILE", "")
    requested = os.environ.get("COMPONENTS", "")
    raw_targets = os.environ.get("TARGETS", "")

    if mode == "full":
        return targets("[]", mode, repository_root)

    if mode != "selective":
        raise ValueError("mode must be full or selective")

    if config_file and raw_targets:
        raise ValueError("config-file and targets cannot be combined")

    if requested and not config_file:
        raise ValueError("components requires config-file")

    if not config_file:
        default_targets = '[{"name":"application","paths":["."]}]'
        return targets(raw_targets or default_targets, mode, repository_root)

    components, full_scan_paths = selection.load_config(repository_root, config_file)
    components = targets(json.dumps(components), mode, repository_root)

    files = None

    if not requested:
        files = selection.changed_files(
            repository_root,
            os.environ.get("SCAN_EVENT", ""),
            os.environ.get("SCAN_BASE", ""),
            os.environ.get("SCAN_HEAD", ""),
        )

    selected = selection.select_components(
        components, files, full_scan_paths, requested
    )

    if selected is None:
        return targets("[]", "full", repository_root)

    return selected


def main():
    repository_root = Path(os.environ["SOURCE"]).resolve()
    reports_directory = Path(os.environ["REPORTS"])
    reports_directory.mkdir(parents=True, exist_ok=True)

    scanners = parse_scanners(os.environ["SCANNERS"])
    rules = json.loads(os.environ["SEMGREP_RULES"])
    skip_dirs = json.loads(os.environ.get("TRIVY_SKIP_DIRS", "[]"))

    validate_semgrep_rules(rules)
    validate_trivy_skip_dirs(skip_dirs)

    components = resolve_components(repository_root)
    records = build_plan(components, scanners)

    (reports_directory / "manifest.json").write_text(json.dumps(records))
    (reports_directory / "plan.json").write_text(json.dumps(components))

    scan_required = bool(records)
    selection_status = {"scan-required": scan_required}
    (reports_directory / "selection.json").write_text(json.dumps(selection_status))

    matrix = json.dumps({"include": records})

    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"matrix={matrix}\n")
        output.write(f"scan-required={str(scan_required).lower()}\n")


if __name__ == "__main__":
    main()
