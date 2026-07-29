import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts import mentat_setup


class MentatSetupConnectionTests(unittest.TestCase):
    def test_setup_parser_exposes_sources_but_no_api_key_value(self):
        parser = mentat_setup.parse_args(
            [
                "--non-interactive",
                "--hermes-mode",
                "remote",
                "--hermes-endpoint",
                "https://hermes.example",
                "--hermes-api-key-env",
                "MENTAT_REMOTE_HERMES_API_KEY",
            ]
        )
        self.assertEqual(parser.hermes_mode, "remote")
        self.assertEqual(
            parser.hermes_api_key_env,
            "MENTAT_REMOTE_HERMES_API_KEY",
        )
        self.assertFalse(hasattr(parser, "api_key"))

    def test_noninteractive_local_setup_is_idempotent_and_secret_free(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            argv = [
                "--repo-root",
                str(root),
                "--non-interactive",
                "--skip-hermes-check",
                "--hermes-mode",
                "local",
                "--force",
                "--write-env",
                "never",
            ]
            first_output = io.StringIO()
            with patch.object(
                mentat_setup,
                "connection_server_active",
                return_value=False,
            ):
                with redirect_stdout(first_output):
                    self.assertEqual(mentat_setup.main(argv), 0)
            first_toml = (root / "mentat.local.toml").read_bytes()
            second_output = io.StringIO()
            with patch.object(
                mentat_setup,
                "connection_server_active",
                return_value=False,
            ):
                with redirect_stdout(second_output):
                    self.assertEqual(mentat_setup.main(argv), 0)
            self.assertEqual(
                (root / "mentat.local.toml").read_bytes(),
                first_toml,
            )
            combined = first_output.getvalue() + second_output.getvalue()
            self.assertIn("Hermes connection selected: Local Hermes (local)", combined)
            self.assertNotIn("api_key", combined.casefold())

    def test_remote_setup_passes_only_a_credential_source_to_connection_operation(self):
        secret = "setup-secret-NEVER-PRINT-12345"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            captured = []
            argv = [
                "--repo-root",
                str(root),
                "--non-interactive",
                "--skip-hermes-check",
                "--hermes-mode",
                "remote",
                "--hermes-endpoint",
                "https://hermes.example",
                "--hermes-label",
                "Workshop remote",
                "--hermes-api-key-env",
                "MENTAT_REMOTE_HERMES_API_KEY",
                "--force",
                "--write-env",
                "never",
            ]

            def fake_apply(_data_root, values, **_kwargs):
                captured.append(values)
                return {
                    "selection": {
                        "mode": "remote",
                        "label": values.label,
                    }
                }

            output = io.StringIO()
            with patch.dict(
                os.environ,
                {"MENTAT_REMOTE_HERMES_API_KEY": secret},
            ):
                with patch.object(
                    mentat_setup,
                    "apply_connection_values",
                    side_effect=fake_apply,
                ):
                    with redirect_stdout(output):
                        self.assertEqual(mentat_setup.main(argv), 0)
            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0].credential_kind, "environment")
            self.assertEqual(
                captured[0].credential_name,
                "MENTAT_REMOTE_HERMES_API_KEY",
            )
            serialized = output.getvalue()
            self.assertNotIn(secret, serialized)
            self.assertNotIn("https://hermes.example", serialized)

    def test_noninteractive_remote_change_requires_force(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "operator-data"
            root.mkdir(mode=0o700)
            with patch.dict(
                os.environ,
                {
                    "MENTAT_REMOTE_HERMES_API_KEY":
                    "setup-force-secret-NEVER-PRINT-12345"
                },
            ):
                values = mentat_setup.HermesConnectionValues(
                    mode="remote",
                    label="Remote",
                    endpoint="https://hermes.example",
                    credential_kind="environment",
                    credential_name="MENTAT_REMOTE_HERMES_API_KEY",
                )
                output = io.StringIO()
                with redirect_stdout(output):
                    with self.assertRaisesRegex(ValueError, "--force"):
                        mentat_setup.apply_connection_values(
                            root,
                            values,
                            require_force=True,
                            force=False,
                        )
            plan = output.getvalue()
            self.assertNotIn("setup-force-secret", plan)
            self.assertNotIn("https://hermes.example", plan)

    def test_setup_connection_change_refuses_running_dashboard(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "operator-data"
            root.mkdir(mode=0o700)
            values = mentat_setup.HermesConnectionValues(
                mode="local",
                reuse_remembered=True,
            )
            with patch.object(
                mentat_setup,
                "connection_server_active",
                return_value=True,
            ):
                with self.assertRaisesRegex(ValueError, "Stop Mentat"):
                    mentat_setup.apply_connection_values(
                        root,
                        values,
                        require_force=False,
                        force=False,
                    )

    def test_interactive_connection_preview_requires_acceptance_before_apply(self):
        import remote_hermes

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "operator-data"
            root.mkdir(mode=0o700)
            values = mentat_setup.HermesConnectionValues(
                mode="remote",
                label="Workshop remote",
                endpoint="https://hermes.example",
                credential_kind="environment",
                credential_name="MENTAT_REMOTE_HERMES_API_KEY",
            )
            applied = {
                "selection": {
                    "mode": "remote",
                    "label": "Workshop remote",
                }
            }
            with patch.dict(
                os.environ,
                {"MENTAT_REMOTE_HERMES_API_KEY": "accept-secret-NEVER-PRINT"},
            ):
                with patch.object(
                    mentat_setup,
                    "connection_server_active",
                    return_value=False,
                ):
                    with patch.object(
                        mentat_setup,
                        "prompt_bool",
                        return_value=True,
                    ) as prompt:
                        with patch.object(
                            remote_hermes,
                            "confirm_connection_from_source",
                            return_value=applied,
                        ) as confirm:
                            result = mentat_setup.apply_connection_values(
                                root,
                                values,
                                require_force=False,
                                force=False,
                                interactive=True,
                            )
            self.assertEqual(result, applied)
            prompt.assert_called_once_with(
                "Apply this Hermes connection change",
                True,
            )
            confirm.assert_called_once()

    def test_interactive_connection_preview_rejection_does_not_apply(self):
        import remote_hermes

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "operator-data"
            root.mkdir(mode=0o700)
            values = mentat_setup.HermesConnectionValues(
                mode="remote",
                label="Workshop remote",
                endpoint="https://hermes.example",
                credential_kind="environment",
                credential_name="MENTAT_REMOTE_HERMES_API_KEY",
            )
            with patch.dict(
                os.environ,
                {"MENTAT_REMOTE_HERMES_API_KEY": "reject-secret-NEVER-PRINT"},
            ):
                with patch.object(
                    mentat_setup,
                    "connection_server_active",
                    return_value=False,
                ):
                    with patch.object(
                        mentat_setup,
                        "prompt_bool",
                        return_value=False,
                    ):
                        with patch.object(
                            remote_hermes,
                            "confirm_connection_from_source",
                        ) as confirm:
                            result = mentat_setup.apply_connection_values(
                                root,
                                values,
                                require_force=False,
                                force=False,
                                interactive=True,
                            )
            self.assertIsNone(result)
            confirm.assert_not_called()
            self.assertFalse(remote_hermes.connection_path(root).exists())

    def test_interactive_force_does_not_bypass_connection_confirmation(self):
        import remote_hermes

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "operator-data"
            root.mkdir(mode=0o700)
            values = mentat_setup.HermesConnectionValues(
                mode="remote",
                label="Workshop remote",
                endpoint="https://hermes.example",
                credential_kind="environment",
                credential_name="MENTAT_REMOTE_HERMES_API_KEY",
            )
            with patch.dict(
                os.environ,
                {"MENTAT_REMOTE_HERMES_API_KEY": "force-secret-NEVER-PRINT"},
            ):
                with patch.object(
                    mentat_setup,
                    "connection_server_active",
                    return_value=False,
                ):
                    with patch.object(
                        mentat_setup,
                        "prompt_bool",
                        return_value=False,
                    ) as prompt:
                        with patch.object(
                            remote_hermes,
                            "confirm_connection_from_source",
                        ) as confirm:
                            result = mentat_setup.apply_connection_values(
                                root,
                                values,
                                require_force=False,
                                force=True,
                                interactive=True,
                            )
            self.assertIsNone(result)
            prompt.assert_called_once_with(
                "Apply this Hermes connection change",
                True,
            )
            confirm.assert_not_called()
            self.assertFalse(remote_hermes.connection_path(root).exists())


if __name__ == "__main__":
    unittest.main()
