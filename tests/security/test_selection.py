"""Exercise declarative configuration and real Git-based component selection."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.security import plan, selection

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS = [
    {"name": "api", "paths": ["services/api"], "dependency-paths": []},
    {"name": "web", "paths": ["apps/web"], "dependency-paths": ["pnpm-lock.yaml"]},
    {
        "name": "mobile",
        "paths": ["apps/mobile"],
        "dependency-paths": ["pnpm-lock.yaml"],
    },
]
CONFIG = {
    "components": {
        component["name"]: {
            key: value for key, value in component.items() if key != "name"
        }
        for component in COMPONENTS
    },
    "full-scan-on-change": ["pnpm-workspace.yaml", ".semgrepignore"],
}


class SelectionTests(unittest.TestCase):
    def select(self, files, requested=""):
        return selection.select_components(
            COMPONENTS, files, [".github/security.yml"], requested
        )

    def test_source_changes_respect_directory_boundaries(self):
        self.assertEqual(
            [c["name"] for c in self.select(["apps/web/main.ts"])], ["web"]
        )
        self.assertEqual(self.select(["apps/website/main.ts"]), [])
        self.assertEqual(self.select(["README.md"]), [])

    def test_shared_lockfile_selects_every_consumer(self):
        self.assertEqual(
            [c["name"] for c in self.select(["pnpm-lock.yaml"])], ["web", "mobile"]
        )

    def test_global_changes_and_uncertain_history_request_full_scan(self):
        self.assertIsNone(self.select([".github/security.yml"]))
        self.assertIsNone(self.select(None))

    def test_explicit_component_names_override_detection(self):
        self.assertEqual(
            [c["name"] for c in self.select(None, '["web","web"]')], ["web"]
        )
        self.assertEqual(self.select(None, "[]"), [])

        for requested in ('["unknown"]', "{}", "[null]"):
            with self.subTest(requested=requested), self.assertRaises(ValueError):
                self.select([], requested)

    def test_safe_yaml_schema_and_automatic_config_trigger(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "security.yml"
            config.write_text(yaml.safe_dump(CONFIG, sort_keys=False))
            components, triggers = selection.load_config(root, "./security.yml")

            self.assertEqual({c["name"] for c in components}, {"api", "web", "mobile"})
            self.assertIn("security.yml", triggers)
            self.assertIn("pnpm-workspace.yaml", triggers)

            invalid = [
                "components: {}",
                "components: {web: {paths: [apps/web], typo: true}}",
                "components: {web: {paths: [../outside]}}",
                "components: {web: {paths: [apps/*]}}",
                "components: {web: {paths: [apps/web]}}\ntypo: true",
                "components: {}\ncomponents: {}",
                '!!python/object/apply:os.system ["echo unsafe"]',
            ]

            for content in invalid:
                config.write_text(content)

                with (
                    self.subTest(content=content),
                    self.assertRaises((ValueError, yaml.YAMLError)),
                ):
                    selection.load_config(root, "security.yml")

    def test_config_file_cannot_escape_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "escape.yml").symlink_to("/etc/passwd")

            for filename in ("../outside.yml", "/etc/passwd", "escape.yml"):
                with self.subTest(filename=filename), self.assertRaises(ValueError):
                    selection.load_config(root, filename)

    def git(self, root, *arguments):
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout.strip()

    def test_pull_request_uses_merge_base_and_push_uses_endpoint_diff(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.git(root, "init", "-b", "main")
            self.git(root, "config", "user.name", "Test")
            self.git(root, "config", "user.email", "test@example.invalid")
            (root / "api.txt").write_text("old")
            self.git(root, "add", ".")
            self.git(root, "commit", "-m", "initial")
            initial = self.git(root, "rev-parse", "HEAD")

            self.git(root, "checkout", "-b", "feature")
            (root / "web.txt").write_text("web")
            self.git(root, "add", ".")
            self.git(root, "commit", "-m", "feature")
            head = self.git(root, "rev-parse", "HEAD")

            self.git(root, "checkout", "main")
            (root / "api.txt").write_text("new")
            self.git(root, "add", ".")
            self.git(root, "commit", "-m", "advance main")
            base = self.git(root, "rev-parse", "HEAD")

            self.assertEqual(
                selection.changed_files(root, "pull_request", base, head), ["web.txt"]
            )
            self.assertEqual(
                set(selection.changed_files(root, "push", base, head)),
                {"api.txt", "web.txt"},
            )

            self.git(root, "mv", "api.txt", "renamed.txt")
            self.git(root, "commit", "-m", "rename")
            renamed = self.git(root, "rev-parse", "HEAD")
            self.assertEqual(
                set(selection.changed_files(root, "push", base, renamed)),
                {"api.txt", "renamed.txt"},
            )

            self.assertIsNone(selection.changed_files(root, "push", "0" * 40, head))
            self.assertIsNone(selection.changed_files(root, "push", "f" * 40, head))
            self.assertIsNone(selection.changed_files(root, "schedule", initial, head))
            self.assertIsNone(selection.changed_files(root, "push", "--unsafe", head))

    def test_automatic_planner_end_to_end(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.git(root, "init", "-b", "main")
            self.git(root, "config", "user.name", "Test")
            self.git(root, "config", "user.email", "test@example.invalid")

            for component in COMPONENTS:
                directory = root / component["paths"][0]
                directory.mkdir(parents=True)
                (directory / "app.txt").write_text("initial")

            (root / "pnpm-lock.yaml").write_text("lockfileVersion: 9")
            (root / "security.yml").write_text(yaml.safe_dump(CONFIG, sort_keys=False))
            self.git(root, "add", ".")
            self.git(root, "commit", "-m", "initial")

            cases = [
                ("apps/web/app.txt", "changed", ["web"]),
                ("pnpm-lock.yaml", "updated lockfile", ["web", "mobile"]),
                ("README.md", "documentation", []),
                (
                    "security.yml",
                    yaml.safe_dump(CONFIG, sort_keys=False) + "\n# policy updated\n",
                    ["repository"],
                ),
            ]

            for filename, content, expected_names in cases:
                with self.subTest(filename=filename):
                    base = self.git(root, "rev-parse", "HEAD")
                    (root / filename).write_text(content)
                    self.git(root, "add", filename)
                    self.git(root, "commit", "-m", "change " + filename)
                    head = self.git(root, "rev-parse", "HEAD")
                    reports = root / "reports"
                    environment = dict(
                        os.environ,
                        SOURCE=str(root),
                        REPORTS=str(reports),
                        MODE="selective",
                        CONFIG_FILE="security.yml",
                        COMPONENTS="",
                        TARGETS="",
                        SCANNERS='["semgrep","trivy"]',
                        SEMGREP_RULES='["p/default"]',
                        SCAN_EVENT="push",
                        SCAN_BASE=base,
                        SCAN_HEAD=head,
                        GITHUB_OUTPUT=str(root / "outputs"),
                    )
                    subprocess.run(
                        ["python3", str(ROOT / "scripts/security/plan.py")],
                        env=environment,
                        check=True,
                    )
                    components = json.loads((reports / "plan.json").read_text())
                    self.assertEqual(
                        [component["name"] for component in components], expected_names
                    )
                    manifest = json.loads((reports / "manifest.json").read_text())
                    self.assertEqual(bool(manifest), bool(expected_names))

    def test_planner_and_report_handle_intentional_empty_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            for component in COMPONENTS:
                (root / component["paths"][0]).mkdir(parents=True)

            (root / "pnpm-lock.yaml").write_text("lockfileVersion: 9")
            (root / "security.yml").write_text(yaml.safe_dump(CONFIG, sort_keys=False))
            reports = root / "reports"
            output = root / "outputs"
            environment = dict(
                os.environ,
                SOURCE=str(root),
                REPORTS=str(reports),
                MODE="selective",
                CONFIG_FILE="security.yml",
                COMPONENTS="[]",
                TARGETS="",
                SCANNERS='["semgrep","trivy"]',
                SEMGREP_RULES='["p/default"]',
                GITHUB_OUTPUT=str(output),
                SCAN_OUTCOME="success",
                FAIL_SEVERITY="HIGH",
                ENFORCE="true",
                FAIL_ON_ERROR="true",
            )
            subprocess.run(
                ["python3", str(ROOT / "scripts/security/plan.py")],
                env=environment,
                check=True,
            )
            subprocess.run(
                ["python3", str(ROOT / "scripts/security/report.py"), str(reports)],
                env=environment,
                check=True,
            )
            report = json.loads((reports / "report.json").read_text())

            self.assertEqual(report["status"], "SKIPPED")
            self.assertFalse(report["failed"])
            self.assertEqual(report["scans"], [])
            self.assertIn("scan-required=false", output.read_text())
            self.assertIn(
                "No components selected", (reports / "summary.md").read_text()
            )

            # Full mode always scans the repository, even with an empty selector.
            with patch.dict(os.environ, environment | {"MODE": "full"}):
                self.assertEqual(plan.resolve_components(root)[0]["paths"], ["."])

            # A missing comparison conservatively scans everything.
            with patch.dict(
                os.environ,
                environment
                | {
                    "COMPONENTS": "",
                    "SCAN_EVENT": "push",
                    "SCAN_BASE": "",
                    "SCAN_HEAD": "",
                },
            ):
                self.assertEqual(plan.resolve_components(root)[0]["name"], "repository")

            with patch.dict(
                os.environ,
                environment | {"TARGETS": '[{"name":"other","paths":["."]}]'},
            ):
                with self.assertRaises(ValueError):
                    plan.resolve_components(root)


if __name__ == "__main__":
    unittest.main()
