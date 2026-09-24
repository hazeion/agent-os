"""Built owner Inbox shows exact Run outcomes on desktop and mobile."""

from __future__ import annotations

from contextlib import closing
import http.client
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import threading
import time
import unittest
from unittest.mock import patch

import mentat_db
from mentat import local_bridge
from private_state import history_path
from run_repository import RunRepository, save_authoritative_run_summaries
from tests import test_project_context as context_tests
from tests.sqlite_authority_support import ensure_run_sqlite_authority
from tests.test_project_context_browser import ContextFixtureHandler
from tests.test_run_repository import run_fixture


ROOT = Path(__file__).resolve().parents[1]
STANDALONE = ROOT / "web" / ".next" / "standalone"


@unittest.skipUnless(os.environ.get("CHROME_PATH") and shutil.which("node") and
                     (STANDALONE / "server.js").is_file(),
                     "Built website and explicit Chrome required")
class RunInboxBrowserTests(unittest.TestCase):
    def test_built_run_notice_desktop_and_mobile(self):
        for width in (1280, 390):
            with self.subTest(width=width):
                self.run_viewport(width)

    def run_viewport(self, width: int) -> None:
        fixture = context_tests.ProjectContextTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        ensure_run_sqlite_authority(fixture.root, history_path(fixture.root))
        save_authoritative_run_summaries(fixture.root, [
            run_fixture("run_browser_failure", status="failed", bound=False)
        ])
        with closing(mentat_db.connect(fixture.root)) as connection:
            connection.execute(
                "UPDATE mentat_runs SET terminal_finalized=1,completed_at=updated_at,"
                "state_revision=state_revision+1 WHERE id='run_browser_failure'",
            )
            connection.commit()
            RunRepository(connection).validate()
        import server
        with patch.object(server, "DATA_DIR", fixture.root):
            token = secrets.token_urlsafe(32)
            bridge = local_bridge.BridgeHTTPServer(("127.0.0.1", 0), token)
            bridge.RequestHandlerClass = ContextFixtureHandler
            bridge.daemon_threads = False
            thread = threading.Thread(target=bridge.serve_forever, daemon=True)
            thread.start()
            with socket.socket() as candidate:
                candidate.bind(("127.0.0.1", 0))
                port = candidate.getsockname()[1]
            environment = {key: value for key, value in os.environ.items()
                           if key in {"PATH", "SystemRoot", "SYSTEMROOT", "TEMP", "TMP",
                                      "USERPROFILE", "LOCALAPPDATA", "APPDATA", "CHROME_PATH",
                                      "MENTAT_CONTEXT_TEST_NO_SANDBOX"}}
            environment.update(PORT=str(port), HOSTNAME="127.0.0.1", NODE_ENV="production",
                               MENTAT_GATEWAY_MODE="local",
                               MENTAT_BRIDGE_ORIGIN=f"http://127.0.0.1:{bridge.server_port}",
                               MENTAT_BRIDGE_TOKEN=token)
            process = subprocess.Popen(
                [shutil.which("node"), str(STANDALONE / "server.js")], cwd=STANDALONE,
                env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                for _ in range(150):
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                    try:
                        connection.request("GET", "/api/gateway/health")
                        response = connection.getresponse()
                        response.read()
                        if response.status == 200:
                            break
                    except OSError:
                        pass
                    finally:
                        connection.close()
                    time.sleep(0.1)
                else:
                    self.fail("website_not_ready")
                browser_environment = {key: value for key, value in environment.items()
                                       if not key.startswith("MENTAT_")}
                browser_environment.update(
                    MENTAT_RUN_INBOX_TEST_PORT=str(port), MENTAT_RUN_INBOX_TEST_WIDTH=str(width),
                    MENTAT_CONTEXT_TEST_NO_SANDBOX=environment.get("MENTAT_CONTEXT_TEST_NO_SANDBOX", ""),
                )
                result = subprocess.run(
                    [shutil.which("node"), str(ROOT / "web/scripts/run-inbox-browser-smoke.mjs")],
                    cwd=ROOT / "web", env=browser_environment, capture_output=True,
                    text=True, timeout=90,
                )
                self.assertEqual(result.returncode, 0, result.stdout[-8000:] + result.stderr[-12000:])
            finally:
                process.terminate()
                try:
                    process.wait(5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(3)
                bridge.shutdown()
                bridge.server_close()
                thread.join(5)
