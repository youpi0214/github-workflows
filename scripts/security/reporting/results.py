"""Load scan artifacts, retain failures, and deduplicate findings."""

import json

from .findings import SEVERITIES, normalize


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

    findings, errors = normalize(
        record["scanner"],
        json.loads(result_file.read_text()),
        record["component"],
        record["target"],
    )

    prefix = record.get("path-prefix", "")

    if prefix:
        for finding in findings:
            finding["location"] = finding["location"].removeprefix(prefix)

    return findings, errors


def aggregate(directory):
    """Collect every scan while isolating malformed or unsuccessful results."""
    findings = []
    failures = []
    scans = []

    try:
        records = json.loads((directory / "manifest.json").read_text())

        if not isinstance(records, list) or not records:
            raise ValueError("no completed scan records")

    except (OSError, ValueError) as exc:
        return [], [str(exc)], []

    for record in records:
        if not isinstance(record, dict):
            failures.append("Malformed scan manifest entry")
            continue

        scans.append(
            {field: record.get(field) for field in ("scanner", "component", "target")}
        )

        try:
            scan_findings, errors = load_scan(directory, record)
            findings.extend(scan_findings)

            if errors:
                failures.append(
                    f"{record['scanner']}/{record['component']}: "
                    f"{len(errors)} scanner errors (see raw JSON)"
                )

        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            failures.append(f"{record.get('scanner')}/{record.get('component')}: {exc}")

    unique_findings = {json.dumps(finding, sort_keys=True): finding for finding in findings}
    sorted_findings = sorted(
        unique_findings.values(),
        key=lambda finding: SEVERITIES.index(finding["severity"]),
    )

    return sorted_findings, failures, scans
