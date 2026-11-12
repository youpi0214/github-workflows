"""Load scan artifacts, retain failures, and deduplicate findings."""

import json

from .findings import SEVERITIES, normalize


def scan_components(record):
    """Read shared scope owners while accepting legacy single-component records."""
    if "components" not in record:
        return [record["component"]]

    components = record["components"]

    if (
        not isinstance(components, list)
        or not components
        or any(not isinstance(name, str) or not name for name in components)
    ):
        raise ValueError("scan components must be a nonempty string list")

    return list(dict.fromkeys(components))


def load_scan(directory, record):
    """Load one successful scan, rejecting missing results and unsafe filenames."""
    result_file = directory / record["file"]

    if result_file.name != record["file"]:
        raise ValueError("invalid result filename")

    # Planned scans default to failure until their job uploads a status.
    # Missing artifacts must never look like clean scanner results.
    exit_code = record.get("exit_code")
    status_file = directory / (record["file"] + ".status.json")

    if status_file.exists():
        exit_code = json.loads(status_file.read_text())["exit_code"]

    if exit_code != 0:
        raise ValueError("scanner process failed or result missing: " + str(exit_code))

    components = scan_components(record)

    findings, errors = normalize(
        record["scanner"],
        json.loads(result_file.read_text()),
        components[0],
        record["target"],
    )

    prefix = record.get("path-prefix", "")

    if prefix:
        for finding in findings:
            finding["location"] = finding["location"].removeprefix(prefix)

    # Preserve the existing one-component-per-finding report format. The raw
    # scanner runs once; each declared consumer receives its own attribution.
    attributed_findings = [
        dict(finding, component=component)
        for component in components
        for finding in findings
    ]

    return attributed_findings, errors


def aggregate(directory):
    """Collect every scan while isolating malformed or unsuccessful results."""
    findings = []
    failures = []
    scans = []

    try:
        records = json.loads((directory / "manifest.json").read_text())

        if not isinstance(records, list):
            raise ValueError("invalid scan manifest")

        if not records:
            selection = json.loads((directory / "selection.json").read_text())
            components = json.loads((directory / "plan.json").read_text())

            if selection.get("scan-required") is not False or components != []:
                raise ValueError("no completed scan records")

            return [], [], []

    except (OSError, ValueError, AttributeError) as exc:
        return [], [str(exc)], []

    for record in records:
        if not isinstance(record, dict):
            failures.append("Malformed scan manifest entry")
            continue

        component_label = str(record.get("component"))

        try:
            components = scan_components(record)
            component_label = ", ".join(str(name) for name in components)

            scans.extend(
                {
                    "scanner": record.get("scanner"),
                    "component": component,
                    "target": record.get("target"),
                }
                for component in components
            )

            scan_findings, errors = load_scan(directory, record)
            findings.extend(scan_findings)

            if errors:
                failures.append(
                    f"{record['scanner']}/{component_label}: "
                    f"{len(errors)} scanner errors (see raw JSON)"
                )

        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            failures.append(f"{record.get('scanner')}/{component_label}: {exc}")

    unique_findings = {
        json.dumps(finding, sort_keys=True): finding for finding in findings
    }
    sorted_findings = sorted(
        unique_findings.values(),
        key=lambda finding: SEVERITIES.index(finding["severity"]),
    )

    return sorted_findings, failures, scans
