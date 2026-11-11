"""Convert Semgrep and Trivy output into the common finding structure."""

SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "UNKNOWN"]

SEMGREP_SEVERITIES = {
    "ERROR": "HIGH",
    "WARNING": "MEDIUM",
    "INVENTORY": "INFO",
    "EXPERIMENT": "INFO",
}


def severity(value):
    """Map scanner severity labels to the common reporting scale."""
    level = str(value).upper()

    if level in SEMGREP_SEVERITIES:
        return SEMGREP_SEVERITIES[level]

    if level in SEVERITIES:
        return level

    return "UNKNOWN"


def make_finding(scanner, component, *, identity, level, title, description, location, line=0, fix="", advisory="",):
    """Create the shared finding structure without mutating a result list."""
    return {
        "scanner": scanner,
        "component": component,
        "id": str(identity),
        "severity": severity(level),
        "title": str(title),
        "description": str(description),
        "location": str(location),
        "line": line,
        "fix": str(fix),
        "advisory": str(advisory),
    }


def normalize_semgrep(data, component):
    """Convert Semgrep findings and retain its partial-scan errors."""
    results = data.get("results")
    errors = data.get("errors", [])

    if not isinstance(results, list) or not isinstance(errors, list):
        raise ValueError("invalid Semgrep results")

    findings = []

    for result in results:
        extra = result["extra"]
        message = extra.get("message", "")

        finding = make_finding(
            "semgrep",
            component,
            identity=result["check_id"],
            level=extra.get("severity"),
            title=message,
            description=message,
            location=result["path"],
            line=result.get("start", {}).get("line", 0),
            fix=extra.get("fix", ""),
            advisory=extra.get("metadata", {}).get("source", ""),
        )
        findings.append(finding)

    return findings, errors


def normalize_trivy(data, component, target):
    """Convert dependency vulnerabilities and infrastructure misconfigurations."""
    results = data.get("Results", [])

    if data.get("SchemaVersion") != 2 or not isinstance(results, list):
        raise ValueError("invalid Trivy results")

    findings = []

    for result in results:
        location = result.get("Target", target)

        for vulnerability in result.get("Vulnerabilities", []) or []:
            finding = make_finding(
                "trivy",
                component,
                identity=vulnerability["VulnerabilityID"],
                level=vulnerability.get("Severity"),
                title=vulnerability.get("Title", vulnerability["VulnerabilityID"]),
                description=vulnerability.get("Description", ""),
                location=location,
                fix=vulnerability.get("FixedVersion", ""),
                advisory=vulnerability.get("PrimaryURL", ""),
            )
            finding["package"] = (
                vulnerability.get("PkgName", "")
                + "@"
                + vulnerability.get("InstalledVersion", "")
            )
            findings.append(finding)

        for misconfiguration in result.get("Misconfigurations", []) or []:
            if misconfiguration.get("Status") == "PASS":
                continue

            finding = make_finding(
                "trivy",
                component,
                identity=misconfiguration["ID"],
                level=misconfiguration.get("Severity"),
                title=misconfiguration.get("Title", ""),
                description=misconfiguration.get("Description", ""),
                location=location,
                line=misconfiguration.get("CauseMetadata", {}).get("StartLine", 0),
                fix=misconfiguration.get("Resolution", ""),
                advisory=misconfiguration.get("PrimaryURL", ""),
            )
            findings.append(finding)

    return findings, []


def normalize(scanner, data, component, target):
    """Dispatch raw scanner output to its format-specific normalizer."""
    if scanner == "semgrep":
        return normalize_semgrep(data, component)

    return normalize_trivy(data, component, target)
