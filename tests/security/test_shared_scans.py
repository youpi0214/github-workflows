"""Shared targets run once while retaining per-component report attribution."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.security import plan
from scripts.security.reporting import results


class SharedScanTests(unittest.TestCase):
    def shared_plan(self):
        return plan.build_plan(
            [
                {
                    "name": "web",
                    "paths": ["apps/web"],
                    "dependency-paths": ["pnpm-lock.yaml"],
                },
                {
                    "name": "mobile",
                    "paths": ["apps/mobile"],
                    "dependency-paths": ["./pnpm-lock.yaml"],
                },
            ],
            ["semgrep", "trivy"],
        )

    def test_shared_trivy_target_runs_once(self):
        records = self.shared_plan()
        self.assertEqual(len(records), 5)
        self.assertEqual([r["id"] for r in records], list(range(5)))
        shared = next(r for r in records if r["target"] == "pnpm-lock.yaml")
        self.assertEqual(shared["components"], ["web", "mobile"])

    def test_semgrep_components_remain_independent(self):
        records = plan.build_plan(
            [{"name": "first", "paths": ["."]}, {"name": "second", "paths": ["."]}],
            ["semgrep", "trivy"],
        )
        self.assertEqual(sum(r["scanner"] == "semgrep" for r in records), 2)
        self.assertEqual(sum(r["scanner"] == "trivy" for r in records), 1)
        self.assertEqual(
            next(r for r in records if r["scanner"] == "trivy")["components"],
            ["first", "second"],
        )

    def test_shared_results_and_failures_cover_all_components(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            record = next(
                r for r in self.shared_plan() if r["target"] == "pnpm-lock.yaml"
            )
            (directory / "manifest.json").write_text(json.dumps([record]))
            (directory / record["file"]).write_text(
                json.dumps(
                    {
                        "SchemaVersion": 2,
                        "Results": [
                            {
                                "Target": "source/pnpm-lock.yaml",
                                "Vulnerabilities": [
                                    {
                                        "VulnerabilityID": "CVE-shared",
                                        "Severity": "HIGH",
                                    },
                                ],
                            }
                        ],
                    }
                )
            )
            status = directory / (record["file"] + ".status.json")
            status.write_text('{"exit_code": 0}')
            findings, failures, scans = results.aggregate(directory)

            self.assertEqual(failures, [])
            self.assertEqual([f["component"] for f in findings], ["web", "mobile"])
            self.assertEqual([s["component"] for s in scans], ["web", "mobile"])
            self.assertTrue(all(f["location"] == "pnpm-lock.yaml" for f in findings))

            status.write_text('{"exit_code": -1}')
            findings, failures, scans = results.aggregate(directory)
            self.assertEqual(findings, [])
            self.assertEqual(len(failures), 1)
            self.assertIn("web, mobile", failures[0])
            self.assertEqual(len(scans), 2)

    def test_invalid_component_associations_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for components in ([], "web", [None]):
                record = dict(self.shared_plan()[0], components=components)
                (directory / "manifest.json").write_text(json.dumps([record]))
                with self.subTest(components=components):
                    self.assertTrue(results.aggregate(directory)[1])


if __name__ == "__main__":
    unittest.main()
