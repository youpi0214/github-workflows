"""Evaluate severity thresholds and scanner error enforcement."""

from .findings import SEVERITIES


def policy_failed(findings, failures, *, threshold, enforce, fail_on_error):
    """Evaluate finding thresholds independently from scan error enforcement."""
    if threshold not in SEVERITIES + ["NONE"]:
        raise ValueError("invalid fail severity")

    violates_threshold = False

    if threshold != "NONE":
        threshold_rank = SEVERITIES.index(threshold)
        violates_threshold = any(
            SEVERITIES.index(finding["severity"]) <= threshold_rank
            for finding in findings
        )

    findings_failed = enforce and violates_threshold
    scans_failed = fail_on_error and bool(failures)

    return findings_failed or scans_failed
