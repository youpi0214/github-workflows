"""Prepare safe links and generate HTML, JSON, and Markdown reports."""

import collections
import html
import json
from pathlib import Path
from urllib.parse import quote, urlparse

SUMMARY_FINDING_LIMIT = 10
SUMMARY_FINDING_LENGTH = 500
SUMMARY_MAX_LENGTH = 60000


def safe_url(value):
    """Allow only HTTP(S) advisory links in generated reports."""
    return value if urlparse(value).scheme in ("http", "https") else ""


def markdown(value):
    """Escape scanner text for Markdown tables and summary lists."""
    return (
        html.escape(str(value))
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("|", "&#124;")
        .replace("`", "&#96;")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
    )


def add_finding_links(findings, source_url):
    """Attach source links and discard unsafe advisory URL schemes."""
    for finding in findings:
        location = finding["location"]
        finding["source"] = ""

        if not Path(location).is_absolute() and ".." not in Path(location).parts:
            encoded_location = quote(location, safe="/")
            finding["source"] = f"{source_url}/{encoded_location}#L{finding['line']}"

        finding["advisory"] = safe_url(finding["advisory"])


def render(data):
    """Embed scanner data safely in the standalone dashboard template."""
    payload = (
        json.dumps(data)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )

    template = Path(__file__).with_name("dashboard.html").read_text()

    return template.replace("__SECURITY_REPORT_DATA__", payload)


def summary_markdown(data):
    """Build the shared Actions summary and managed PR comment body."""
    lines = [
        "<!-- reusable-security-report -->",
        "## Security: " + data["status"],
        "",
        f"[Detailed HTML and raw reports]({data['run_url']}) "
        "— download the security-report artifact.",
        "",
        "| Severity | Findings |",
        "|---|---:|",
    ]

    for level, count in data["counts"].items():
        lines.append(f"| {level} | {count} |")

    if data["status"] == "SKIPPED":
        lines.extend(["", "No components selected; no scanners ran.", ""])

    lines.extend(["", "### Coverage", ""])

    for scan in data["scans"]:
        label = f"{scan['scanner']} / {scan['component']}: {scan['target']}"
        lines.append("- " + markdown(label))

    breakdown = collections.Counter(
        (finding["scanner"], finding["component"]) for finding in data["findings"]
    )
    lines.extend(["", "### Findings by scanner and component", ""])

    for (scanner, component), count in breakdown.items():
        lines.append(f"- {markdown(scanner)} / {markdown(component)}: {count}")

    lines.extend(["", "### Highest priority", ""])

    for finding in data["findings"][:SUMMARY_FINDING_LIMIT]:
        label = (
            f"{finding['severity']} {finding['id']} — "
            f"{finding['title']} ({finding['location']})"
        )
        lines.append("- " + markdown(label)[:SUMMARY_FINDING_LENGTH])

    lines.extend(["", "### Incomplete scans", ""])

    for failure in data["failures"]:
        lines.append("- " + markdown(failure))

    # Stay below GitHub's comment size limit, including large coverage lists.
    return "\n".join(lines)[:SUMMARY_MAX_LENGTH]


def write_reports(directory, data):
    """Write downloadable reports and return their shared Markdown summary."""
    summary = summary_markdown(data)

    (directory / "report.json").write_text(json.dumps(data, indent=2))
    (directory / "index.html").write_text(render(data))
    (directory / "summary.md").write_text(summary)

    return summary
