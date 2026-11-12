import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.security import plan
from scripts.security.reporting import findings, rendering, results

ROOT = Path(__file__).resolve().parents[2]


class Reports(unittest.TestCase):
    def test_empty_and_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            self.assertTrue(results.aggregate(p)[1])
            (p / "manifest.json").write_text("broken")
            self.assertTrue(results.aggregate(p)[1])
            (p / "manifest.json").write_text("[]")
            self.assertTrue(results.aggregate(p)[1])
            (p / "manifest.json").write_text("[null, 1, {}]")
            self.assertEqual(len(results.aggregate(p)[1]), 3)

    def test_multi_scanner_partial_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            semgrep = {
                "results": [
                    {
                        "check_id": "test",
                        "path": "a.py",
                        "extra": {
                            "severity": "ERROR",
                            "message": "</script><img onerror=alert(1)>",
                        },
                    }
                ],
                "errors": [],
            }
            trivy = {
                "SchemaVersion": 2,
                "Results": [
                    {
                        "Target": "pnpm-lock.yaml",
                        "Vulnerabilities": [
                            {
                                "VulnerabilityID": "CVE-1",
                                "Severity": "CRITICAL",
                                "PkgName": "x",
                                "InstalledVersion": "1",
                                "FixedVersion": "2",
                            }
                        ],
                        "Misconfigurations": [
                            {
                                "ID": "docker",
                                "Severity": "LOW",
                                "Resolution": "Use USER",
                            }
                        ],
                    }
                ],
            }
            records = []
            for i, (scanner, data) in enumerate(
                [("semgrep", semgrep), ("trivy", trivy), ("semgrep", semgrep)]
            ):
                (p / f"{i}.json").write_text(json.dumps(data))
                records.append(
                    {
                        "scanner": scanner,
                        "component": "app",
                        "target": ".",
                        "file": f"{i}.json",
                        "exit_code": 0,
                    }
                )
            records.append(
                {
                    "scanner": "trivy",
                    "component": "broken",
                    "target": ".",
                    "file": "missing",
                    "exit_code": 2,
                }
            )
            (p / "manifest.json").write_text(json.dumps(records))
            rows, errors, scans = results.aggregate(p)
            self.assertEqual(len(scans), 4)
            self.assertEqual(len(rows), 3)
            self.assertEqual(len(errors), 1)
            self.assertEqual(rows[0]["severity"], "CRITICAL")

            env = dict(
                os.environ,
                ENFORCE="false",
                FAIL_ON_ERROR="true",
                GITHUB_STEP_SUMMARY=str(p / "step-summary.md"),
                GITHUB_OUTPUT=str(p / "github-output"),
            )
            subprocess.run(
                ["python3", str(ROOT / "scripts/security/report.py"), tmp],
                env=env,
                check=True,
            )
            data = json.loads((p / "report.json").read_text())

            self.assertTrue(data["failed"])
            self.assertEqual(data["status"], "INCOMPLETE")
            self.assertNotIn("</script><img", (p / "index.html").read_text())
            self.assertIn("\\u003c/script", (p / "index.html").read_text())

    def test_clean_and_error_results(self):
        self.assertEqual(findings.normalize("semgrep", {"results": []}, "a", ".")[0], [])
        self.assertEqual(
            findings.normalize("trivy", {"SchemaVersion": 2}, "a", ".")[0], []
        )
        with self.assertRaises(ValueError):
            findings.normalize("semgrep", {}, "a", ".")
        self.assertTrue(
            findings.normalize("semgrep", {"results": [], "errors": ["parse"]}, "a", ".")[
                1
            ]
        )
        self.assertEqual(rendering.safe_url("javascript:alert(1)"), "")

    def test_policy_and_clean_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "manifest.json").write_text(
                json.dumps(
                    [
                        {
                            "scanner": "semgrep",
                            "component": "a",
                            "target": ".",
                            "file": "0.json",
                            "exit_code": 0,
                        }
                    ]
                )
            )
            raw = {"results": []}
            for findings, enforce, fail_error, outcome, expected in [
                (False, "true", "true", "success", False),
                (True, "true", "true", "success", True),
                (True, "false", "true", "success", False),
                (False, "false", "true", "failure", True),
                (False, "false", "false", "failure", False),
            ]:
                raw["results"] = (
                    [{"check_id": "x", "path": "a", "extra": {"severity": "ERROR"}}]
                    if findings
                    else []
                )
                (p / "0.json").write_text(json.dumps(raw))
                env = dict(
                    os.environ,
                    ENFORCE=enforce,
                    FAIL_ON_ERROR=fail_error,
                    SCAN_OUTCOME=outcome,
                    FAIL_SEVERITY="HIGH",
                    GITHUB_STEP_SUMMARY=str(p / "step-summary.md"),
                    GITHUB_OUTPUT=str(p / "github-output"),
                )
                subprocess.run(
                    ["python3", str(ROOT / "scripts/security/report.py"), tmp],
                    env=env,
                    check=True,
                )
                self.assertEqual(
                    json.loads((p / "report.json").read_text())["failed"], expected
                )

    def test_missing_and_failed_matrix_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            records = plan.build_plan(
                [{"name": "application", "paths": ["."]}], ["semgrep"]
            )
            (directory / "manifest.json").write_text(json.dumps(records))
            (directory / "0.json").write_text('{"results": []}')

            # Even valid empty JSON is incomplete without a successful job status.
            self.assertTrue(results.aggregate(directory)[1])
            status = directory / "0.json.status.json"
            status.write_text('{"exit_code": -1, "outcome": "failure"}')
            self.assertTrue(results.aggregate(directory)[1])
            status.write_text('{"exit_code": 0, "outcome": "success"}')
            self.assertEqual(results.aggregate(directory)[1], [])
            status.write_text("malformed")
            self.assertTrue(results.aggregate(directory)[1])

    def test_shared_dependency_matrix(self):
        records = plan.build_plan(
            [
                {
                    "name": "web",
                    "paths": ["apps/web", "apps/web"],
                    "dependency-paths": ["pnpm-lock.yaml"],
                }
            ],
            ["semgrep", "trivy", "trivy"],
        )
        self.assertEqual(len(records), 3)
        self.assertEqual(
            [record["file"] for record in records], ["0.json", "1.json", "2.json"]
        )
        self.assertEqual(records[2]["target"], "pnpm-lock.yaml")
        self.assertTrue(all(record["exit_code"] == -1 for record in records))
        with self.assertRaises(ValueError):
            plan.build_plan(
                [{"name": "large", "paths": [str(i) for i in range(257)]}], ["semgrep"]
            )

    def test_trivy_workspace_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            record = dict(
                scanner="trivy",
                component="web",
                target="apps/web",
                file="0.json",
                exit_code=0,
                **{"path-prefix": "source/"},
            )
            (directory / "manifest.json").write_text(json.dumps([record]))
            (directory / "0.json").write_text(
                json.dumps(
                    {
                        "SchemaVersion": 2,
                        "Results": [
                            {
                                "Target": "source/apps/web/package-lock.json",
                                "Vulnerabilities": [
                                    {"VulnerabilityID": "CVE-test", "Severity": "HIGH"}
                                ],
                            }
                        ],
                    }
                )
            )
            findings, failures, _ = results.aggregate(directory)
            self.assertEqual(failures, [])
            self.assertEqual(findings[0]["location"], "apps/web/package-lock.json")

    def test_scope_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(plan.targets("[]", "full", root)[0]["paths"], ["."])
            for paths in [["../"], ["/etc"], ["-danger"], ["missing"]]:
                with self.assertRaises(ValueError):
                    plan.targets(
                        json.dumps([{"name": "a", "paths": paths}]), "selective", root
                    )
            (root / "escape").symlink_to("/etc")
            with self.assertRaises(ValueError):
                plan.targets('[{"name":"a","paths":["escape"]}]', "selective", root)


if __name__ == "__main__":
    unittest.main()
