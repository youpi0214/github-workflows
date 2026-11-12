"""Read component configuration and select scopes from repository changes."""

import json
import re
import subprocess
from pathlib import PurePosixPath


def relative_path(value):
    """Normalize a configured file/directory path without accepting escapes."""
    if not isinstance(value, str) or not value or value.startswith("-"):
        raise ValueError("configuration paths must be nonempty relative paths")

    path = PurePosixPath(value)

    if path.is_absolute() or ".." in path.parts or any(c in value for c in "*?["):
        raise ValueError(
            "configuration paths must be relative files or directories, not globs"
        )

    return path.as_posix()


def load_config(repository_root, filename):
    """Load YAML as data, rejecting duplicate keys and unsupported attributes."""
    import yaml

    class UniqueKeyLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            mapping = {}

            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)

                if not isinstance(key, str) or key in mapping:
                    raise ValueError("configuration keys must be unique strings")

                mapping[key] = self.construct_object(value_node, deep=deep)

            return mapping

    filename = relative_path(filename)
    config_path = repository_root / filename

    if not config_path.resolve().is_relative_to(repository_root):
        raise ValueError("config-file must remain inside the repository")

    config = yaml.load(config_path.read_text(), Loader=UniqueKeyLoader)

    if not isinstance(config, dict) or set(config) - {
        "components",
        "full-scan-on-change",
    }:
        raise ValueError(
            "configuration supports components and full-scan-on-change only"
        )

    definitions = config.get("components")

    if not isinstance(definitions, dict) or not definitions:
        raise ValueError("configuration needs a nonempty components mapping")

    components = []

    for name, definition in definitions.items():
        if not isinstance(definition, dict) or set(definition) - {
            "paths",
            "dependency-paths",
        }:
            raise ValueError(
                f"component {name} supports paths and dependency-paths only"
            )

        component = {"name": name}

        for field in ("paths", "dependency-paths"):
            paths = definition.get(field, [])

            if not isinstance(paths, list) or (field == "paths" and not paths):
                raise ValueError(f"component {name} needs a path list for {field}")

            component[field] = [relative_path(path) for path in paths]

        components.append(component)

    full_scan_paths = config.get("full-scan-on-change", [])

    if not isinstance(full_scan_paths, list):
        raise ValueError("full-scan-on-change must be a path list")

    # Changing the selection policy itself always requires complete coverage.
    full_scan_paths = [filename] + [relative_path(path) for path in full_scan_paths]

    return components, full_scan_paths


def changed_files(repository_root, event_name, base, head):
    """Use the PR merge base or push range; return None if coverage is uncertain."""
    if event_name not in ("pull_request", "push"):
        return None

    for revision in (base, head):
        if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", revision or ""):
            return None

        if set(revision) == {"0"}:
            return None

    comparison = [f"{base}...{head}"] if event_name == "pull_request" else [base, head]
    command = [
        "git",
        "-C",
        str(repository_root),
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--name-only",
        "-z",
        *comparison,
        "--",
    ]

    try:
        result = subprocess.run(command, capture_output=True, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    return result.stdout.decode("utf-8", errors="surrogateescape").split("\0")[:-1]


def matches_path(filename, configured_path):
    """Match an exact file or a descendant directory, respecting boundaries."""
    return (
        configured_path == "."
        or filename == configured_path
        or filename.startswith(configured_path + "/")
    )


def select_components(components, files, full_scan_paths, requested=""):
    """Return selected components, or None to request a full repository scan."""
    if requested:
        names = json.loads(requested)
        definitions = {component["name"]: component for component in components}

        if not isinstance(names, list) or any(
            not isinstance(name, str) for name in names
        ):
            raise ValueError("components must be a JSON array of component names")

        unknown_names = set(names) - definitions.keys()

        if unknown_names:
            raise ValueError("unknown components: " + ", ".join(sorted(unknown_names)))

        return [definitions[name] for name in dict.fromkeys(names)]

    if files is None:
        return None

    if any(matches_path(file, path) for file in files for path in full_scan_paths):
        return None

    selected = []

    for component in components:
        paths = component["paths"] + component.get("dependency-paths", [])

        if any(matches_path(file, path) for file in files for path in paths):
            selected.append(component)

    return selected
