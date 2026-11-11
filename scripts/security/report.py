"""Coordinate reporting using configuration supplied by GitHub Actions."""

import os
import sys
from pathlib import Path

from reporting.findings import SEVERITIES
from reporting.policy import policy_failed
from reporting.rendering import add_finding_links, write_reports
from reporting.results import aggregate


def build_report(directory):
    """Combine scan results with the policy and run metadata from the workflow."""
    findings, failures, scans = aggregate(directory)

    if os.environ.get("SCAN_OUTCOME", "success") != "success":
        failures.append("Scan orchestration failed; coverage may be incomplete")

    failed = policy_failed(
        findings,
        failures,
        threshold=os.environ.get("FAIL_SEVERITY", "HIGH").upper(),
        enforce=os.environ.get("ENFORCE", "true") == "true",
        fail_on_error=os.environ.get("FAIL_ON_ERROR", "true") == "true",
    )

    add_finding_links(findings, os.environ.get("SOURCE_URL", ""))

    if failures:
        status = "INCOMPLETE"
    elif findings:
        status = "FINDINGS"
    else:
        status = "CLEAN"

    counts = {
        level: sum(finding["severity"] == level for finding in findings)
        for level in SEVERITIES
    }

    return {
        "schema_version": 1,
        "status": status,
        "failed": failed,
        "findings": findings,
        "failures": failures,
        "scans": scans,
        "counts": counts,
        "run_url": os.environ.get("RUN_URL", ""),
    }


def write_github_outputs(data, summary):
    """Append to GitHub runner files when running inside Actions."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")

    if summary_file:
        with open(summary_file, "a") as stream:
            stream.write(summary)

    output_file = os.environ.get("GITHUB_OUTPUT")

    if output_file:
        failed = str(data["failed"]).lower()

        with open(output_file, "a") as stream:
            stream.write(f"failed={failed}\nstatus={data['status']}\n")


def main():
    directory = Path(sys.argv[1])
    directory.mkdir(parents=True, exist_ok=True)

    data = build_report(directory)
    summary = write_reports(directory, data)

    write_github_outputs(data, summary)


if __name__ == "__main__":
    main()
