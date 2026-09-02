from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
NODE_VERSION = "24.19.0"


class NodeRuntimeFoundationContractTests(unittest.TestCase):
    def test_source_package_and_lock_agree_on_exact_node_24_contract(self):
        package = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
        lock = json.loads(
            (ROOT / "web" / "package-lock.json").read_text(encoding="utf-8")
        )

        self.assertEqual((ROOT / ".node-version").read_text(encoding="utf-8"), NODE_VERSION + "\n")
        self.assertEqual(
            (ROOT / ".chrome-for-testing-version").read_text(encoding="utf-8"),
            "152.0.7923.0\n",
        )
        self.assertEqual(package["engines"]["node"], ">=24.19.0 <25")
        self.assertEqual(package["packageManager"], "npm@11.17.0")
        self.assertEqual(lock["lockfileVersion"], 3)
        self.assertEqual(lock["packages"][""]["engines"]["node"], ">=24.19.0 <25")
        self.assertEqual(lock["packages"][""]["dependencies"], package["dependencies"])
        self.assertEqual(lock["packages"][""]["devDependencies"], package["devDependencies"])
        self.assertEqual(package["dependencies"]["next"], "16.3.2")
        self.assertEqual(package["devDependencies"]["@types/node"], "24.13.3")
        self.assertEqual(package["devDependencies"]["@puppeteer/browsers"], "3.2.1")
        self.assertEqual(package["devDependencies"]["chrome-launcher"], "1.2.1")
        self.assertEqual(package["devDependencies"]["lighthouse"], "13.4.1")
        self.assertNotIn("tsx", package["devDependencies"])
        self.assertNotIn("start", package["scripts"])

    def test_every_setup_node_action_pins_the_approved_patch(self):
        setup_count = 0
        pin_count = 0
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            workflow = path.read_text(encoding="utf-8")
            setup_count += workflow.count("uses: actions/setup-node@")
            pin_count += workflow.count(f"node-version: {NODE_VERSION}")
            self.assertNotIn("node-version: 24.18.0", workflow, path.name)
        self.assertGreater(setup_count, 0)
        self.assertEqual(pin_count, setup_count)

    def test_production_build_and_preview_commands_are_fixed(self):
        package = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
        next_runner = (ROOT / "web" / "scripts" / "run-next.mjs").read_text(
            encoding="utf-8"
        )
        standalone = (
            ROOT / "web" / "scripts" / "prepare-standalone.mjs"
        ).read_text(encoding="utf-8")
        shell_runtime = (ROOT / "web" / "public" / "shell-runtime.js").read_text(
            encoding="utf-8"
        )
        lighthouse_gate = (
            ROOT / "web" / "scripts" / "lighthouse-gate.mjs"
        ).read_text(encoding="utf-8")
        foundation_smoke = (
            ROOT / "scripts" / "web_foundation_smoke.mjs"
        ).read_text(encoding="utf-8")
        proxy = (ROOT / "web" / "src" / "proxy.ts").read_text(encoding="utf-8")
        next_config = (ROOT / "web" / "next.config.ts").read_text(encoding="utf-8")
        quality = (ROOT / ".github" / "workflows" / "quality-gates.yml").read_text(
            encoding="utf-8"
        )

        self.assertEqual(
            package["scripts"]["build"],
            "node scripts/run-next.mjs build && node scripts/prepare-standalone.mjs",
        )
        self.assertEqual(
            package["scripts"]["dev"],
            "node scripts/run-next.mjs dev --hostname 127.0.0.1",
        )
        self.assertIn('new Set(["build", "dev"])', next_runner)
        self.assertIn('NEXT_TELEMETRY_DISABLED: "1"', next_runner)
        self.assertIn('MENTAT_STATIC_FOUNDATION: "1"', next_runner)
        self.assertIn("shell: false", next_runner)
        self.assertIn('output: "standalone"', next_config)
        self.assertIn("unoptimized: true", next_config)
        eslint_config = (ROOT / "web" / "eslint.config.mjs").read_text(encoding="utf-8")
        self.assertIn('"package-runtime/**"', eslint_config)
        for destination in (
            "/shell/agents.html",
            "/shell/runs.html",
        ):
            self.assertIn(f'destination: "{destination}"', next_config)
        self.assertNotIn('destination: "/shell/tasks.html"', next_config)
        self.assertIn('route.path !== "/" && route.path !== "/tasks"', foundation_smoke)
        self.assertIn(
            '{ path: "/tasks", heading: "Projects & Tasks", navLabel: "Projects & Tasks", title: "Projects & Tasks · Mentat" }',
            foundation_smoke,
        )
        self.assertIn("document.querySelector('h1')?.textContent === 'Projects & Tasks'", foundation_smoke)
        self.assertIn('afterTransition.active !== "Projects & Tasks"', foundation_smoke)
        self.assertIn("document.querySelector('h1')?.textContent === 'What can Mentat help with?'", foundation_smoke)
        self.assertNotIn('source: "tasks.html"', standalone)
        self.assertIn(
            "data-mentat-shell-runtime", standalone
        )
        self.assertIn(
            '["/shell-runtime.js"]', standalone
        )
        self.assertIn("static Emerald shell", standalone)
        self.assertIn("no-hydration contract", standalone)
        self.assertIn('"node_modules", "@img"', standalone)
        self.assertIn('"node_modules", "sharp"', standalone)
        self.assertIn('fetch("/api/bridge/health"', shell_runtime)
        self.assertIn("AbortSignal.timeout(3500)", shell_runtime)
        self.assertNotIn("MENTAT_BRIDGE_TOKEN", shell_runtime)
        self.assertFalse((ROOT / "web" / "public" / "preference-preload.js").exists())
        self.assertFalse((ROOT / "web" / "public" / "foundation-status.js").exists())
        self.assertIn('matcher: ["/:path*"]', proxy)
        self.assertIn("contentSecurityPolicy(nonce)", proxy)
        self.assertIn("nonce-${nonce}", proxy)
        self.assertNotIn("unsafe-eval", proxy)
        self.assertNotIn("Content-Security-Policy", next_config)
        self.assertNotIn("?!_next/static", proxy)
        self.assertIn("const RUNS_PER_MODE = 3", lighthouse_gate)
        self.assertIn("const minimumPerformanceScore = Number(configuredMinimumPerformance)", lighthouse_gate)
        self.assertIn("minimumPerformanceScore < 95 || minimumPerformanceScore > 100", lighthouse_gate)
        self.assertIn("function medianScore(scores)", lighthouse_gate)
        self.assertIn("function validateModeResults(mode, results)", lighthouse_gate)
        self.assertIn("categoryId !== \"performance\" && score < 100", lighthouse_gate)
        self.assertIn("const performanceMedian = medianScore(performanceScores)", lighthouse_gate)
        self.assertIn("performance_medians: performanceMedians", lighthouse_gate)
        self.assertIn("runBoundedProcess", lighthouse_gate)
        self.assertIn("ownedChrome?.kill()", lighthouse_gate)
        self.assertIn("killAll()", lighthouse_gate)
        self.assertIn('process.once("SIGTERM"', lighthouse_gate)
        self.assertIn("writeFailureEvidence(runtimeState", lighthouse_gate)
        self.assertIn("MENTAT_LIGHTHOUSE_FAILURE_PATH", lighthouse_gate)
        self.assertNotIn("spawnSync(\n", lighthouse_gate)
        self.assertIn("const AUDIT_ATTEMPTS = 2;", lighthouse_gate)
        self.assertIn("isTransientTraceFailure", lighthouse_gate)
        self.assertIn("NO_NAVSTART", lighthouse_gate)
        self.assertIn("Install pinned Chrome for Testing", quality)
        self.assertIn("CHROME_FOR_TESTING_VERSION: 152.0.7923.0", quality)
        self.assertIn(
            'CHROME_PATH="$MENTAT_LIGHTHOUSE_CHROME_PATH" npm --prefix web run lighthouse:gate',
            quality,
        )
        self.assertIn("node-foundation-lighthouse-failure", quality)
        self.assertIn("npm --prefix web ci --ignore-scripts", quality)
        self.assertIn("npm --prefix web run lighthouse:gate", quality)
        self.assertIn('preview_data_dir="$RUNNER_TEMP/mentat-web-preview-data"', quality)
        self.assertIn(
            'timeout --preserve-status --signal=INT --kill-after=10s 10s env MENTAT_DATA_DIR="$preview_data_dir" python server.py --port "$bootstrap_port"',
            quality,
        )
        self.assertIn('test -f "$preview_data_dir/private/console/mentat.sqlite3"', quality)
        self.assertIn("python scripts/mentat_web_preview.py --port 8896", quality)
        self.assertIn(
            'MENTAT_DATA_DIR="$preview_data_dir" python scripts/verify_web_preview_lifecycle.py',
            quality,
        )
        self.assertIn("WEB_RESULT: ${{ needs.web-foundation.result }}", quality)
        self.assertIn('test "$WEB_RESULT" = success', quality)


if __name__ == "__main__":
    unittest.main()
