"""Validate Maven entry points, safe invocation, and fresh cache identities."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.maven import prepare


class MavenPreparationTests(unittest.TestCase):
    def environment(self):
        return {
            "POM_FILES": "reactor/pom.xml\nindependent/pom.xml",
            "JAVA_VERSION": "21",
            "JAVA_DISTRIBUTION": "temurin",
            "MAVEN_GOALS": "install",
            "MAVEN_PROFILES": "ci, integration",
            "SKIP_TESTS": "true",
            "RUNNER_OS": "Linux",
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
        }

    def projects(self, root):
        for name in ("reactor", "reactor/child", "independent"):
            directory = root / name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "pom.xml").write_text("<project/>")

    def test_default_build_installs_modules_without_skipping_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.projects(root)
            environment = self.environment()
            environment.pop("MAVEN_GOALS")
            environment.pop("SKIP_TESTS")

            configuration = prepare.create_plan(root, environment)
            command = prepare.maven_command(root / "reactor/pom.xml", configuration, root / "cache")

            self.assertEqual(configuration["goals"], ["install"])
            self.assertFalse(configuration["skip-tests"])
            self.assertEqual(command[-1], "install")
            self.assertIn("-DskipTests=false", command)

    def test_explicit_roots_are_ordered_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.projects(root)
            projects = prepare.project_poms(
                "reactor/pom.xml\n./reactor/pom.xml\nindependent/pom.xml", root
            )
            self.assertEqual(projects, ["reactor/pom.xml", "independent/pom.xml"])

    def test_paths_cannot_escape_and_missing_files_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.projects(root)
            (root / "escape.xml").symlink_to("/etc/passwd")

            for path in (
                "",
                "../outside.xml",
                "/etc/passwd",
                "missing/pom.xml",
                "escape.xml",
            ):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    prepare.project_poms(path, root)

    def test_goals_and_profiles_reject_flags_and_shell_syntax(self):
        self.assertEqual(prepare.maven_goals("clean install"), ["clean", "install"])
        self.assertEqual(
            prepare.maven_profiles("ci, integration ci"), ["ci", "integration"]
        )

        for goals in (
            "",
            "install -Dmaven.repo.local=/other",
            "install && id",
            "$(id)",
            "install; echo unsafe",
        ):
            with self.subTest(goals=goals), self.assertRaises(ValueError):
                prepare.maven_goals(goals)

        with self.assertRaises(ValueError):
            prepare.maven_profiles("ci --file=other.xml")

    def test_child_poms_and_maven_config_invalidate_restore_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.projects(root)
            environment = self.environment()
            original = prepare.create_plan(root, environment)
            (root / "reactor/child/pom.xml").write_text("<project>changed</project>")
            child_change = prepare.create_plan(root, environment)
            self.assertNotEqual(
                original["restore-prefix"], child_change["restore-prefix"]
            )

            (root / "reactor/.mvn").mkdir()
            (root / "reactor/.mvn/maven.config").write_text("-Dexample=true")
            config_change = prepare.create_plan(root, environment)
            self.assertNotEqual(
                child_change["restore-prefix"], config_change["restore-prefix"]
            )

    def test_source_changes_and_reruns_get_fresh_final_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.projects(root)
            environment = self.environment()
            original = prepare.create_plan(root, environment)
            source_change = prepare.create_plan(
                root, environment | {"GITHUB_SHA": "b" * 40}
            )
            rerun = prepare.create_plan(root, environment | {"GITHUB_RUN_ATTEMPT": "2"})

            self.assertEqual(
                original["restore-prefix"], source_change["restore-prefix"]
            )
            self.assertNotEqual(original["cache-key"], source_change["cache-key"])
            self.assertNotEqual(original["cache-key"], rerun["cache-key"])

            for overrides in (
                {"JAVA_VERSION": "17"},
                {"MAVEN_PROFILES": "other"},
                {"MAVEN_GOALS": "dependency:resolve"},
            ):
                self.assertNotEqual(
                    original["restore-prefix"],
                    prepare.create_plan(root, environment | overrides)[
                        "restore-prefix"
                    ],
                )

    def test_prepare_runs_each_entry_once_and_stops_on_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.projects(root)
            configuration = prepare.create_plan(root, self.environment())
            repository = root / "cache with spaces"

            with patch.object(prepare.subprocess, "run") as run:
                prepare.prepare_projects(root, configuration, repository)

            self.assertEqual(run.call_count, 2)
            first = run.call_args_list[0]
            self.assertEqual(first.kwargs["cwd"], root / "reactor")
            self.assertTrue(first.kwargs["check"])
            self.assertNotIn("shell", first.kwargs)
            self.assertIn(f"-Dmaven.repo.local={repository}", first.args[0])
            self.assertIn("-DskipTests=true", first.args[0])
            self.assertIn("ci,integration", first.args[0])
            self.assertEqual(first.args[0][-1], "install")

            with patch.object(
                prepare.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, "mvn"),
            ) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    prepare.prepare_projects(root, configuration, repository)
                self.assertEqual(run.call_count, 1)

    def test_external_configuration_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.projects(root)
            (root / "reactor/.mvn").mkdir()
            (root / "reactor/.mvn/maven.config").symlink_to("/etc/passwd")

            with self.assertRaises(ValueError):
                prepare.create_plan(root, self.environment())


if __name__ == "__main__":
    unittest.main()
