"""Built dashboard with real context authority; unrelated integrations are inert."""
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

from agent_registry import AgentRegistry
from mentat import local_bridge
from project_context_editor import read_project_editor
from project_repository import mutate_authoritative_projects
from task_repository import mutate_authoritative_tasks
from tests.test_project_repository import project
from tests import test_project_context as context_tests
from tests.test_task_repository import task

ROOT = Path(__file__).resolve().parents[1]
STANDALONE = ROOT / 'web/.next/standalone'
ENVELOPE = {'schema_version': 1, 'service': 'mentat-local-bridge', 'runtime': 'python', 'status': 'ready'}
PROJECT = {'id': 'project_mentat', 'name': 'Garage', 'revision': 1, 'status': 'active'}


class ContextFixtureHandler(local_bridge.BridgeRequestHandler):
    def do_GET(self):
        if (self.path == local_bridge.BRIDGE_HEALTH_PATH or self.path.startswith(local_bridge.PROJECT_CONTEXT_ROOT)
                or self.path.startswith(local_bridge.PROJECT_DELIVERABLE_ROOT)
                or self.path.startswith(local_bridge.PROJECT_PLAN_ROOT)
                or self.path.startswith(local_bridge.TASK_INPUT_ROOT)
                or self.path.startswith(local_bridge.BRIDGE_PLANNING_TASKS_PATH)
                or self.path.startswith(local_bridge.BRIDGE_PLANNING_TASK_DETAIL_PATH)
                or self.path.startswith(local_bridge.BRIDGE_PLANNING_TASK_PATH)):
            return super().do_GET()
        if not self._request_is_private() or not self._owner_access_allowed(unsafe=False):
            return self._send_json({'error': 'unauthorized'}, 401)
        if self.path.startswith(local_bridge.BRIDGE_PLANNING_OVERVIEW_PATH):
            return self._send_json({**ENVELOPE, 'projects': [PROJECT], 'project_count': 1, 'attention': [], 'attention_count': 0, 'today': '2026-09-22', 'truncated': False}, 200)
        if self.path == '/bridge/v1/agents':
            return self._send_json({**ENVELOPE, 'agents': [{'id': 'agent_research', 'name': 'Research Agent', 'runtime_type': 'codex', 'runtime_config_id': 'context_config', 'capabilities': ['run.start']}], 'count': 1}, 200)
        return self._send_json({**ENVELOPE, 'status': 'unavailable'}, 503)

    def do_POST(self):
        if (self.path.startswith(local_bridge.PROJECT_CONTEXT_ROOT) or self.path.startswith(local_bridge.TASK_INPUT_ROOT)
                or self.path.startswith(local_bridge.PROJECT_DELIVERABLE_ROOT)
                or self.path.startswith(local_bridge.PROJECT_PLAN_ROOT)
                or self.path in {local_bridge.BRIDGE_PLANNING_DELETION_PREVIEW_PATH, local_bridge.BRIDGE_PLANNING_DELETION_CONFIRM_PATH}):
            return super().do_POST()
        return self._send_json({**ENVELOPE, 'status': 'unavailable'}, 503)


@unittest.skipUnless(os.environ.get('CHROME_PATH') and shutil.which('node') and (STANDALONE / 'server.js').is_file(), 'Built website and explicit Chrome required')
class ProjectContextBrowserTests(unittest.TestCase):
    def test_desktop_and_mobile_owner_context_workflow(self):
        for width in (1280, 390):
            with self.subTest(width=width):
                self.run_viewport(width)

    def run_viewport(self, width):
        fixture = context_tests.ProjectContextTests(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.publish(fixture.upload(), brief='Previous garage goals')
        service = fixture.deletion_service(); service.finalize(service.preview('project', 'project_mentat'))
        mutate_authoritative_projects(fixture.root, lambda rows: ([*rows, project('Garage', 'project_mentat')], None))
        AgentRegistry(fixture.root, supported_runtime_types=('codex',)).create_agent(agent_id='agent_research', name='Research Agent', runtime_config_id='context_config', runtime_type='codex', runtime_agent_ref='default', capabilities=('run.start',))
        mutate_authoritative_tasks(fixture.root, lambda rows: ([*rows, {**task('task_garage_research'), 'title':'Research garage organization', 'project':'Garage', 'project_id':'project_mentat', 'assigned_agent_id':'agent_research'}], None))
        floorplan = fixture.root / 'dimensions.md'; floorplan.write_text('Garage dimensions: 6 metres by 5 metres. Keep bicycle access clear.', encoding='utf-8')
        import server
        with patch.object(server, 'DATA_DIR', fixture.root):
            token = secrets.token_urlsafe(32)
            bridge = local_bridge.BridgeHTTPServer(('127.0.0.1', 0), token)
            bridge.RequestHandlerClass = ContextFixtureHandler; bridge.daemon_threads = False
            thread = threading.Thread(target=bridge.serve_forever, daemon=True); thread.start()
            with socket.socket() as candidate:
                candidate.bind(('127.0.0.1', 0)); port = candidate.getsockname()[1]
            environment = {key: value for key, value in os.environ.items() if key in {'PATH', 'SystemRoot', 'SYSTEMROOT', 'TEMP', 'TMP', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'CHROME_PATH', 'MENTAT_CONTEXT_TEST_NO_SANDBOX'}}
            environment.update(PORT=str(port), HOSTNAME='127.0.0.1', NODE_ENV='production', MENTAT_GATEWAY_MODE='local', MENTAT_BRIDGE_ORIGIN=f'http://127.0.0.1:{bridge.server_port}', MENTAT_BRIDGE_TOKEN=token)
            process = subprocess.Popen([shutil.which('node'), str(STANDALONE / 'server.js')], cwd=STANDALONE, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                for _ in range(150):
                    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
                    try:
                        connection.request('GET', '/api/gateway/health'); response = connection.getresponse(); response.read()
                        if response.status == 200: break
                    except OSError: pass
                    finally: connection.close()
                    time.sleep(.1)
                else: self.fail('website_not_ready')
                browser_environment = {key: value for key, value in environment.items() if not key.startswith('MENTAT_')}
                browser_environment.update(MENTAT_CONTEXT_TEST_PORT=str(port), MENTAT_CONTEXT_TEST_WIDTH=str(width), MENTAT_CONTEXT_TEST_FILE=str(floorplan), MENTAT_CONTEXT_TEST_NO_SANDBOX=environment.get('MENTAT_CONTEXT_TEST_NO_SANDBOX', ''))
                result = subprocess.run([shutil.which('node'), str(ROOT / 'web/scripts/project-context-browser-smoke.mjs')], cwd=ROOT / 'web', env=browser_environment, capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-4000:])
                state = read_project_editor(fixture.root, 'project_mentat')
                self.assertEqual(state['current']['brief'], 'Garage layout: reserve a workbench and bicycle access.')
                self.assertEqual(len(state['current']['files']), 1)
                self.assertEqual(state['grants'][0]['state'], 'revoked')
                with __import__('contextlib').closing(__import__('mentat_db').connect(fixture.root)) as connection:
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_task_input_versions').fetchone()[0], 1)
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_task_input_scopes').fetchone()[0], 1)
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_deliverable_versions').fetchone()[0], 3)
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_deliverable_reviews').fetchone()[0], 2)
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_plan_versions').fetchone()[0], 1)
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_runs').fetchone()[0], 0)
                    self.assertEqual([tuple(row) for row in connection.execute('SELECT action FROM mentat_deliverable_reviews ORDER BY revision')], [('accept',), ('request_changes',)])
            finally:
                process.terminate()
                try: process.wait(5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(3)
                bridge.shutdown(); bridge.server_close(); thread.join(5)
