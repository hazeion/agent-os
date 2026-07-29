from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import data_layout
from data_layout import (
    MAX_PREFLIGHT_JSON_BYTES,
    SEED_FILE_NAMES,
    preflight_data_root,
    resolve_data_root,
    resolve_platform_data_root,
)


class DataRootResolverTests(unittest.TestCase):
    def test_platform_defaults_match_the_approved_contract(self):
        self.assertEqual(
            resolve_platform_data_root(
                platform_name="darwin",
                environ={},
                home=Path("/Users/operator"),
            ),
            Path("/Users/operator/Library/Application Support/Mentat"),
        )
        self.assertEqual(
            str(
                resolve_platform_data_root(
                    platform_name="win32",
                    environ={"LOCALAPPDATA": r"C:\Users\operator\AppData\Local"},
                    home=Path("C:/Users/operator"),
                )
            ),
            r"C:\Users\operator\AppData\Local\Mentat",
        )
        self.assertEqual(
            resolve_platform_data_root(
                platform_name="linux",
                environ={"XDG_DATA_HOME": "/srv/operator-data"},
                home=Path("/home/operator"),
            ),
            Path("/srv/operator-data/Mentat"),
        )
        for xdg_value in (None, "", "relative/data"):
            environ = {} if xdg_value is None else {"XDG_DATA_HOME": xdg_value}
            self.assertEqual(
                resolve_platform_data_root(
                    platform_name="linux",
                    environ=environ,
                    home=Path("/home/operator"),
                ),
                Path("/home/operator/.local/share/Mentat"),
            )

    def test_windows_default_fails_closed_without_absolute_local_app_data(self):
        for environ in ({}, {"LOCALAPPDATA": ""}, {"LOCALAPPDATA": "relative"}):
            with self.assertRaisesRegex(ValueError, "LOCALAPPDATA"):
                resolve_platform_data_root(
                    platform_name="win32",
                    environ=environ,
                    home=Path("C:/Users/operator"),
                )

    def test_resolution_precedence_and_source_are_exact(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            values = {
                "cli": root / "cli",
                "mentat": root / "mentat-env",
                "legacy": root / "legacy-env",
                "toml": root / "toml",
            }
            cases = (
                (str(values["cli"]), {"MENTAT_DATA_DIR": str(values["mentat"]), "AGENT_OS_DATA_DIR": str(values["legacy"])}, str(values["toml"]), "cli", values["cli"]),
                (None, {"MENTAT_DATA_DIR": str(values["mentat"]), "AGENT_OS_DATA_DIR": str(values["legacy"])}, str(values["toml"]), "environment", values["mentat"]),
                (None, {"AGENT_OS_DATA_DIR": str(values["legacy"])}, str(values["toml"]), "legacy_environment", values["legacy"]),
                (None, {}, str(values["toml"]), "toml", values["toml"]),
                (None, {}, None, "platform_default", Path.home() / "Library" / "Application Support" / "Mentat"),
            )
            for cli_value, environ, toml_value, source, expected in cases:
                with self.subTest(source=source):
                    result = resolve_data_root(
                        cli_value=cli_value,
                        environ=environ,
                        toml_value=toml_value,
                        base_dir=root,
                        platform_name="darwin",
                        home=Path.home(),
                    )
                    self.assertEqual(result.source, source)
                    self.assertEqual(
                        result.path,
                        data_layout._absolute_without_following(expected),
                    )

        for key, source in (
            (None, "cli"),
            ("MENTAT_DATA_DIR", "environment"),
            ("AGENT_OS_DATA_DIR", "legacy_environment"),
        ):
            cli_value = "  /tmp/mentat-space  " if key is None else None
            environ = {} if key is None else {key: "  /tmp/mentat-space  "}
            result = resolve_data_root(
                cli_value=cli_value,
                environ=environ,
                toml_value=None,
                base_dir=Path("/unused"),
            )
            self.assertEqual(result.source, source)
            self.assertEqual(
                result.path,
                data_layout._absolute_without_following(Path("/tmp/mentat-space")),
            )


class DataRootPreflightTests(unittest.TestCase):
    def write_seeds(self, root: Path, *, names=SEED_FILE_NAMES) -> None:
        root.mkdir(parents=True, exist_ok=True)
        for name in names:
            payload = {} if name == "dashboard.json" else []
            (root / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")

    def test_clean_preflight_is_bounded_public_and_side_effect_free(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_seeds(seeds)
            (seeds / "dashboard.json").write_text(
                json.dumps({"marker": "seed-payload"}) + "\n",
                encoding="utf-8",
            )
            before = {path.relative_to(root): path.stat().st_mtime_ns for path in root.rglob("*")}

            plan = preflight_data_root(seeds, target, home=root / "home")

            after = {path.relative_to(root): path.stat().st_mtime_ns for path in root.rglob("*")}
            self.assertEqual(plan.status, "ready")
            self.assertEqual({item.status for item in plan.items}, {"initialize"})
            self.assertEqual([item.name for item in plan.items], list(SEED_FILE_NAMES))
            self.assertEqual(before, after)
            self.assertFalse(target.exists())
            summary = plan.public_summary()
            self.assertEqual(set(summary), {"status", "items", "issues"})
            self.assertNotIn(str(root), json.dumps(summary))
            self.assertNotIn("seed-payload", json.dumps(summary))

    def test_existing_and_development_override_states_are_read_only(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_seeds(seeds)
            self.write_seeds(target)

            existing = preflight_data_root(seeds, target, home=root / "home")
            development = preflight_data_root(seeds, seeds, home=root / "home")

            self.assertEqual(existing.status, "existing")
            self.assertEqual({item.status for item in existing.items}, {"existing"})
            self.assertEqual(development.status, "development_override")
            self.assertEqual({item.status for item in development.items}, {"development"})

    def test_any_legacy_state_reserves_the_entire_seed_set(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            target = root / "target"
            self.write_seeds(seeds)
            legacy.mkdir()
            (legacy / "tasks.json").write_text("[]\n", encoding="utf-8")

            plan = preflight_data_root(seeds, target, legacy_root=legacy, home=root / "home")

            self.assertEqual(plan.status, "migration_required")
            self.assertEqual({item.status for item in plan.items}, {"migrate", "reserved"})
            self.assertFalse(target.exists())

    def test_legacy_plus_any_destination_is_a_global_conflict(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            target = root / "target"
            self.write_seeds(seeds)
            legacy.mkdir()
            target.mkdir()
            (legacy / "tasks.json").write_text("[]\n", encoding="utf-8")
            (target / "projects.json").write_text("[]\n", encoding="utf-8")

            plan = preflight_data_root(seeds, target, legacy_root=legacy, home=root / "home")

            self.assertEqual(plan.status, "conflict")
            self.assertEqual({item.status for item in plan.items}, {"conflict"})

    def test_missing_invalid_and_nonregular_seed_inputs_fail_closed(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_seeds(seeds)
            (seeds / "tasks.json").unlink()
            missing = preflight_data_root(seeds, target, home=root / "home")
            self.assertEqual(missing.status, "unsafe")
            self.assertIn("seed_missing:tasks.json", missing.issues)

            (seeds / "tasks.json").write_text("not json\n", encoding="utf-8")
            invalid = preflight_data_root(seeds, target, home=root / "home")
            self.assertEqual(invalid.status, "unsafe")
            self.assertIn("seed_invalid_json:tasks.json", invalid.issues)

            (seeds / "tasks.json").write_text("[" * 10000 + "]" * 10000, encoding="utf-8")
            nested = preflight_data_root(seeds, target, home=root / "home")
            self.assertEqual(nested.status, "unsafe")
            self.assertIn("seed_invalid_json:tasks.json", nested.issues)

            (seeds / "tasks.json").unlink()
            (seeds / "tasks.json").mkdir()
            nonregular = preflight_data_root(seeds, target, home=root / "home")
            self.assertEqual(nonregular.status, "unsafe")
            self.assertIn("seed_not_regular:tasks.json", nonregular.issues)

            if hasattr(os, "mkfifo"):
                (seeds / "tasks.json").rmdir()
                os.mkfifo(seeds / "tasks.json")
                fifo = preflight_data_root(seeds, target, home=root / "home")
                self.assertEqual(fifo.status, "unsafe")
                self.assertIn("seed_not_regular:tasks.json", fifo.issues)

    def test_invalid_target_json_and_dangerously_broad_root_fail_closed(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_seeds(seeds)
            target.mkdir()
            (target / "tasks.json").write_text("not json\n", encoding="utf-8")

            invalid = preflight_data_root(seeds, target, home=root / "home")
            broad = preflight_data_root(seeds, Path(Path.cwd().anchor), home=root / "home")
            home = preflight_data_root(seeds, root / "home", home=root / "home")

            self.assertEqual(invalid.status, "unsafe")
            self.assertIn("target_invalid_json:tasks.json", invalid.issues)
            self.assertEqual(broad.status, "unsafe")
            self.assertIn("data_root_too_broad", broad.issues)
            self.assertEqual(home.status, "unsafe")
            self.assertIn("data_root_too_broad", home.issues)

    def test_symlinked_known_file_fails_closed_without_following_it(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            outside = root / "outside.json"
            self.write_seeds(seeds)
            target.mkdir()
            outside.write_text("[]\n", encoding="utf-8")
            try:
                (target / "tasks.json").symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            plan = preflight_data_root(seeds, target, home=root / "home")

            self.assertEqual(plan.status, "unsafe")
            self.assertIn("target_symlink:tasks.json", plan.issues)

    def test_intermediate_symlinks_fail_closed_for_every_root(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            outside = root / "outside"
            alias = root / "alias"
            self.write_seeds(seeds)
            outside.mkdir()
            try:
                alias.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            target_plan = preflight_data_root(
                seeds,
                alias / "missing-target",
                home=root / "home",
            )
            seed_plan = preflight_data_root(
                alias / "missing-seeds",
                root / "target",
                home=root / "home",
            )
            legacy_plan = preflight_data_root(
                seeds,
                root / "target",
                legacy_root=alias / "missing-legacy",
                home=root / "home",
            )

            self.assertIn("target_root_symlink", target_plan.issues)
            self.assertIn("seed_root_symlink", seed_plan.issues)
            self.assertIn("legacy_root_symlink", legacy_plan.issues)

    def test_windows_reparse_attribute_fails_closed(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "reparse" / "target"
            self.write_seeds(seeds)
            reparse_path = data_layout._absolute_without_following(root / "reparse")
            real_lstat = os.lstat
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)

            def fake_lstat(path):
                metadata = real_lstat(path)
                if Path(path) != reparse_path:
                    return metadata
                return SimpleNamespace(
                    st_mode=metadata.st_mode,
                    st_file_attributes=reparse_flag,
                )

            (root / "reparse").mkdir()
            with patch.object(data_layout.os, "lstat", side_effect=fake_lstat):
                plan = preflight_data_root(seeds, target, home=root / "home")

            self.assertEqual(plan.status, "unsafe")
            self.assertIn("target_root_symlink", plan.issues)

    def test_resolved_explicit_symlink_root_remains_visible_to_preflight(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            actual = root / "actual"
            selected = root / "selected"
            self.write_seeds(seeds)
            actual.mkdir()
            try:
                selected.symlink_to(actual, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            resolved = resolve_data_root(
                cli_value=selected,
                environ={},
                toml_value=None,
                base_dir=root,
            )
            plan = preflight_data_root(seeds, resolved.path, home=root / "home")

            self.assertEqual(
                resolved.path,
                data_layout._absolute_without_following(selected),
            )
            self.assertEqual(plan.status, "unsafe")
            self.assertIn("target_root_symlink", plan.issues)

    def test_wrong_document_shapes_fail_closed(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            legacy = root / "legacy"
            self.write_seeds(seeds)
            self.write_seeds(target)
            self.write_seeds(legacy)

            (seeds / "dashboard.json").write_text("[]\n", encoding="utf-8")
            seed_plan = preflight_data_root(seeds, root / "new", home=root / "home")
            self.assertIn("seed_invalid_shape:dashboard.json", seed_plan.issues)

            (seeds / "dashboard.json").write_text("{}\n", encoding="utf-8")
            (target / "tasks.json").write_text("{}\n", encoding="utf-8")
            target_plan = preflight_data_root(seeds, target, home=root / "home")
            self.assertIn("target_invalid_shape:tasks.json", target_plan.issues)

            (target / "tasks.json").write_text("[]\n", encoding="utf-8")
            (legacy / "projects.json").write_text("null\n", encoding="utf-8")
            legacy_plan = preflight_data_root(
                seeds,
                root / "new",
                legacy_root=legacy,
                home=root / "home",
            )
            self.assertIn("legacy_invalid_shape:projects.json", legacy_plan.issues)

    def test_oversized_known_json_fails_before_parsing(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_seeds(seeds)
            target.mkdir()
            with (target / "tasks.json").open("wb") as handle:
                handle.truncate(MAX_PREFLIGHT_JSON_BYTES + 1)

            plan = preflight_data_root(seeds, target, home=root / "home")

            self.assertEqual(plan.status, "unsafe")
            self.assertIn("target_too_large:tasks.json", plan.issues)

    def test_optional_file_presence_comes_from_the_validation_result(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            outside = root / "outside.json"
            self.write_seeds(seeds)
            target.mkdir()
            outside.write_text("[]\n", encoding="utf-8")
            original = data_layout._json_file_state

            def introduce_after_missing(path, label, name, *, required):
                result = original(path, label, name, required=required)
                if label == "target" and name == "tasks.json" and not result[0]:
                    path.symlink_to(outside)
                return result

            with patch.object(
                data_layout,
                "_json_file_state",
                side_effect=introduce_after_missing,
            ):
                plan = preflight_data_root(seeds, target, home=root / "home")

            tasks = next(item for item in plan.items if item.name == "tasks.json")
            self.assertEqual(tasks.status, "initialize")
            self.assertNotEqual(tasks.status, "existing")


if __name__ == "__main__":
    unittest.main()
