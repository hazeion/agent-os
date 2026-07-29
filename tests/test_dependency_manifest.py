from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.py"
REQUIREMENTS = ROOT / "requirements.txt"

MODULE_TO_PACKAGE = {
    "google.auth": "google-auth",
    "google.oauth2": "google-auth",
    "googleapiclient": "google-api-python-client",
    "requests": "requests",
}


def requirement_names() -> set[str]:
    names = set()
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.add(line.split("==", 1)[0].strip())
    return names


class DependencyManifestTests(unittest.TestCase):
    def test_runtime_manifest_exists_and_pins_versions(self):
        self.assertTrue(REQUIREMENTS.exists())
        lines = [line.strip() for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines() if line.strip() and not line.strip().startswith("#")]
        self.assertGreaterEqual(len(lines), 3)
        for line in lines:
            self.assertIn("==", line, f"Dependency line should be pinned for reproducibility: {line}")

    def test_manifest_covers_non_stdlib_server_imports(self):
        tree = ast.parse(SERVER.read_text(encoding="utf-8"))
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        required_packages = set()
        for module_name in imported_modules:
            for module_prefix, package_name in MODULE_TO_PACKAGE.items():
                if module_name == module_prefix or module_name.startswith(module_prefix + "."):
                    required_packages.add(package_name)

        if any(module_name == "google.auth.transport.requests" or module_name.startswith("google.auth.transport.requests.") for module_name in imported_modules):
            required_packages.add("requests")

        self.assertSetEqual(required_packages, {"google-api-python-client", "google-auth", "requests"})
        self.assertTrue(required_packages.issubset(requirement_names()))

    def test_manifest_includes_pinned_iana_timezone_data(self):
        self.assertIn("tzdata", requirement_names())


if __name__ == "__main__":
    unittest.main()
