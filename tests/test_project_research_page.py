from __future__ import annotations

import gzip
import io
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import subprocess
import threading
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from link_preview_policy import LinkPreviewPolicyError, NormalizedPreviewURL, normalize_preview_url
from link_preview_transport import LinkPreviewTransportError, fetch_public_research_page, fetch_public_resource
from link_preview_workers import LinkPreviewWorkerError
import link_preview_workers as workers
from mentat import project_research_page as pages
from mentat import project_research_reader as readers
from tests.test_link_preview_transport import FixtureNetwork, response


class PublicResearchPageTests(unittest.TestCase):
    def test_article_omits_active_embedded_hidden_and_navigation_content(self):
        result = pages.extract_page(b'''<html><head><title>Garage &amp; Storage</title>
        <script>secret</script></head><body><nav>navigation</nav><main><p>Use 5<em>0</em> bins.</p>
        <div hidden>hidden</div><div aria-hidden="true">also hidden</div><svg>embedded</svg>
        <form>password</form><style>css</style><template>template</template><p>Second paragraph.</p>
        <a href="/guide">Storage guide</a><a href="https://127.0.0.1/">private</a>
        <a href="https://python.org/?api_key=secret">credential</a></main><footer>footer</footer></body></html>''',
                                    "text/html; charset=utf-8", "https://python.org/docs/")
        self.assertEqual(result["title"], "Garage & Storage")
        self.assertIn("Use 50 bins. Second paragraph.", result["text"])
        for ignored in ("secret", "hidden", "navigation", "embedded", "password", "css", "template", "footer"):
            self.assertNotIn(ignored, result["text"])
        self.assertEqual(result["links"], [{"url": "https://python.org/guide", "text": "Storage guide"}])
        self.assertFalse(result["text_truncated"])

    def test_plain_text_is_inert_and_controls_bidi_are_removed(self):
        value = '<script>plain source</script>\x00\u202e text'
        result = pages.extract_page(value.encode(), "text/plain; charset=utf-8", "https://python.org/")
        self.assertEqual(result["text"], "<script>plain source</script> text")
        self.assertEqual(result["links"], [])

    def test_text_and_link_labels_are_utf8_bounded_and_truncation_explicit(self):
        result = pages.extract_page(("<title>" + "界" * 1000 + "</title><p>" + "界" * 50000 + "</p>").encode(),
                                    "text/html", "https://python.org/")
        self.assertLessEqual(len(result["title"].encode()), 512)
        self.assertLessEqual(len(result["text"].encode()), pages.MAX_TEXT)
        self.assertTrue(result["text_truncated"])
        readers._validate(result)

    def test_link_candidates_normalize_deduplicate_and_remain_capped(self):
        html = ''.join('<a href="/link-' + str(index) + '">' + 'x' * 500 + '</a>' for index in range(40))
        html += '<a href="/link-0">duplicate</a><a href="javascript:alert(1)">bad</a>'
        result = pages.extract_page(html.encode(), "text/html", "https://python.org/")
        self.assertEqual(len(result["links"]), 32)
        self.assertTrue(all(len(link["text"].encode()) <= 256 for link in result["links"]))
        readers._validate(result)

    def test_structure_mime_charset_and_body_limits_fail_closed(self):
        cases = [(b"<div>" * 129, "text/html"), (b"<br>" * (pages.MAX_TAGS + 1), "text/html"),
                 (b"x" * (2 * 1024 * 1024 + 1), "text/plain"), (b"pdf", "application/pdf"),
                 (b"\xff", "text/html; charset=utf-8"), (b"abc", "text/plain; charset=utf-16")]
        for body, mime in cases:
            with self.subTest(mime=mime), self.assertRaises(pages.ResearchPageError):
                pages.extract_page(body, mime, "https://python.org/")

    def test_parent_rejects_extra_unbounded_or_noncanonical_worker_payloads(self):
        valid = pages.extract_page(b"hello", "text/plain", "https://python.org/")
        for changed in (dict(valid, raw_html="hidden"), dict(valid, text="x" * (pages.MAX_TEXT + 1)),
                        dict(valid, final_url="https://127.0.0.1/"), dict(valid, text="bidi\u202e"),
                        dict(valid, links=[{"url": "https://python.org/", "text": "\x00"}])):
            with self.subTest(changed=tuple(changed)), self.assertRaises(ValueError):
                readers._validate(changed)


class PublicResearchTransportTests(unittest.TestCase):
    def test_fixed_get_is_credential_free_and_preview_limit_does_not_change(self):
        body = b"x" * (600 * 1024)
        network = FixtureNetwork({"python.org": ("8.8.8.8",)}, [response(body, headers=(("Content-Type", "text/plain"),))])
        result = fetch_public_research_page(normalize_preview_url("https://python.org/docs"),
                    resolver=network.resolver, dialer=network.dialer)
        self.assertEqual(result.body, body)
        sent = network.connections[0].request
        self.assertIn(b"GET /docs HTTP/1.1", sent)
        self.assertIn(b"User-Agent: MentatProjectResearch/1", sent)
        for forbidden in (b"Authorization:", b"Cookie:", b"Proxy-Authorization:", b"Referer:", b"Origin:"):
            self.assertNotIn(forbidden, sent)
        old = FixtureNetwork({"python.org": ("8.8.8.8",)}, [response(body, headers=(("Content-Type", "text/html"),))])
        with self.assertRaises(LinkPreviewTransportError):
            fetch_public_resource(normalize_preview_url("https://python.org/docs"), kind="page", resolver=old.resolver, dialer=old.dialer)

    def test_gzip_decoded_and_encoded_bounds_are_two_mib(self):
        for content, gzip_body in ((b"x" * (2 * 1024 * 1024 + 1), False),
                                   (gzip.compress(b"x" * (2 * 1024 * 1024 + 1)), True)):
            headers = (("Content-Type", "text/plain"),) + ((("Content-Encoding", "gzip"),) if gzip_body else ())
            network = FixtureNetwork({"python.org": ("8.8.8.8",)}, [response(content, headers=headers)])
            with self.assertRaises(LinkPreviewTransportError):
                fetch_public_research_page(normalize_preview_url("https://python.org/"), resolver=network.resolver, dialer=network.dialer)

    def test_mixed_dns_private_redirect_peer_substitution_and_forged_target_refuse(self):
        mixed = FixtureNetwork({"python.org": ("8.8.8.8", "10.0.0.1")}, [])
        with self.assertRaises(LinkPreviewTransportError):
            fetch_public_research_page(normalize_preview_url("https://python.org/"), resolver=mixed.resolver, dialer=mixed.dialer)
        self.assertEqual(mixed.dials, [])
        network = FixtureNetwork({"python.org": ("8.8.8.8",)}, [response(b"", status=302, headers=(("Location", "https://169.254.169.254/"),))])
        with self.assertRaises(LinkPreviewTransportError):
            fetch_public_research_page(normalize_preview_url("https://python.org/"), resolver=network.resolver, dialer=network.dialer)
        self.assertEqual(len(network.connections), 1)
        wrong = FixtureNetwork({"python.org": ("8.8.8.8",)}, [response(b"ok", headers=(("Content-Type", "text/plain"),))])
        dial = wrong.dialer
        def substituted(*args):
            connection = dial(*args)
            connection.address = "127.0.0.1"
            return connection
        with self.assertRaises(LinkPreviewTransportError):
            fetch_public_research_page(normalize_preview_url("https://python.org/"), resolver=wrong.resolver, dialer=substituted)
        forged = NormalizedPreviewURL("https://python.org/", "python.org", "/\r\nAuthorization: injected", False)
        with self.assertRaises(LinkPreviewTransportError):
            fetch_public_research_page(forged)

    def test_unsupported_platform_refuses_before_worker_launch(self):
        with patch.object(readers.sys, "platform", "win32"), patch.object(readers, "_WorkerSlot") as started:
            with self.assertRaises(LinkPreviewWorkerError):
                readers.PublicPageReader()
        started.assert_not_called()


@unittest.skipUnless(sys.platform == "linux", "Linux credential-free research workers")
class PublicResearchWorkerTests(unittest.TestCase):
    def test_raw_close_failure_attempts_every_slot_and_retains_pool_for_retry(self):
        for kind in ("research", "preview"):
            first, second = Mock(), Mock()
            error = OSError("owned cleanup failure")
            first.abort.side_effect = error
            target = readers if kind == "research" else workers
            with patch.object(target, "_WorkerSlot", side_effect=[first, second]):
                pool = readers.PublicPageReader() if kind == "research" else workers.LinkPreviewWorkerPool(command=("fixed",), environ={})
            with self.subTest(kind=kind), self.assertRaises(OSError) as raised:
                pool.close()
            self.assertIs(raised.exception, error)
            first.abort.assert_called_once()
            second.abort.assert_called_once()
            attribute = "_mentat_reader_owner" if kind == "research" else "_mentat_worker_pool"
            self.assertIs(getattr(error, attribute), pool)
            first.abort.side_effect = None
            pool.close()
            self.assertEqual(first.abort.call_count, 2)
            self.assertEqual(second.abort.call_count, 2)

    def test_shared_preview_pool_also_fences_buffered_result_after_close(self):
        entered, release = threading.Event(), threading.Event()
        slot = Mock()
        def buffered(**kwargs):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("preview result barrier timeout")
            return {"status": "ready"}
        slot.execute.side_effect = buffered
        outcomes = []
        with patch.object(workers, "_WorkerSlot", return_value=slot):
            pool = workers.LinkPreviewWorkerPool(command=("fixed",), environ={})
            def execute():
                try:
                    outcomes.append(pool.execute(kind="page", normalized_url="https://python.org/"))
                except BaseException as error:
                    outcomes.append(error)
            request = threading.Thread(target=execute)
            request.start()
            self.assertTrue(entered.wait(2))
            pool.close()
            release.set()
            request.join(2)
            self.assertFalse(request.is_alive())
            self.assertEqual(len(outcomes), 1)
            self.assertIsInstance(outcomes[0], LinkPreviewWorkerError)

    def test_buffered_slot_result_cannot_cross_completed_close(self):
        queued, release = threading.Event(), threading.Event()
        process = Mock()
        process.pid = 40000
        process.stdin, process.stdout = io.BytesIO(), io.BytesIO()
        process.poll.return_value = None
        def reaped(*args, **kwargs):
            process.poll.return_value = -15
            return -15
        process.wait.side_effect = reaped
        reader_thread = Mock(ident=None)
        reader_thread.is_alive.return_value = False
        real_thread = threading.Thread
        outcomes = []
        with (patch.object(workers.subprocess, "Popen", return_value=process),
              patch.object(workers.threading, "Thread", return_value=reader_thread),
              patch.object(workers.os, "killpg"), patch.object(workers.secrets, "token_hex", return_value="a" * 32)):
            slot = workers._WorkerSlot(("fixed",), clock=time.monotonic, environment={})
            def buffered(*args, **kwargs):
                queued.set()
                if not release.wait(2):
                    raise RuntimeError("result barrier timeout")
                return (json.dumps({"type": "result", "id": "a" * 32, "result": {"status": "ready"}}) + "\n").encode()
            slot._messages.get = buffered
            def execute():
                try:
                    outcomes.append(slot.execute(kind="research_page", url="https://python.org/"))
                except BaseException as error:
                    outcomes.append(error)
            request = real_thread(target=execute)
            request.start()
            self.assertTrue(queued.wait(2))
            slot.close()
            release.set()
            request.join(2)
            self.assertFalse(request.is_alive())
            self.assertEqual(len(outcomes), 1)
            self.assertIsInstance(outcomes[0], LinkPreviewWorkerError)

    def test_reader_validation_cannot_publish_after_reader_close(self):
        entered, release = threading.Event(), threading.Event()
        result = pages.extract_page(b"public", "text/plain", "https://python.org/")
        slot = Mock()
        slot.execute.return_value = result
        validator = readers._validate
        outcomes = []
        def blocked(value):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("validation barrier timeout")
            return validator(value)
        with patch.object(readers, "_WorkerSlot", return_value=slot), patch.object(readers, "_validate", blocked):
            reader = readers.PublicPageReader()
            def execute():
                try:
                    outcomes.append(reader.read_page("https://python.org/"))
                except BaseException as error:
                    outcomes.append(error)
            request = threading.Thread(target=execute)
            request.start()
            self.assertTrue(entered.wait(2))
            reader.close()
            release.set()
            request.join(2)
            self.assertFalse(request.is_alive())
            self.assertEqual(len(outcomes), 1)
            self.assertIsInstance(outcomes[0], LinkPreviewWorkerError)

    def test_close_waits_for_in_progress_replacement_publication_then_reaps_it(self):
        entered, release, close_started, closed = (threading.Event() for _ in range(4))
        thread_type = threading.Thread
        processes = []
        errors = []
        def create(*args, **kwargs):
            process = Mock()
            process.pid = 40000 + len(processes)
            process.stdin, process.stdout = io.BytesIO(), io.BytesIO()
            process.poll.return_value = None
            def reaped(*args, **kwargs):
                process.poll.return_value = -15
                return -15
            process.wait.side_effect = reaped
            processes.append(process)
            if len(processes) == 2:
                entered.set()
                if not release.wait(2):
                    raise RuntimeError("replacement barrier timeout")
            return process
        reader_thread = Mock(ident=None)
        reader_thread.is_alive.return_value = False
        with (patch.object(workers.subprocess, "Popen", side_effect=create) as spawned,
              patch.object(workers.threading, "Thread", return_value=reader_thread),
              patch.object(workers.os, "killpg")):
            slot = workers._WorkerSlot(("fixed",), clock=time.monotonic, environment={})
            def replacing():
                try:
                    slot.replace()
                except BaseException as error:
                    errors.append(error)
            def closing():
                close_started.set()
                try:
                    slot.close()
                except BaseException as error:
                    errors.append(error)
                finally:
                    closed.set()
            replace_thread = thread_type(target=replacing)
            close_thread = thread_type(target=closing)
            replace_thread.start()
            self.assertTrue(entered.wait(2))
            close_thread.start()
            self.assertTrue(close_started.wait(2))
            self.assertFalse(closed.wait(.05))
            release.set()
            replace_thread.join(2)
            close_thread.join(2)
            self.assertFalse(replace_thread.is_alive() or close_thread.is_alive())
            self.assertFalse(errors)
            self.assertTrue(closed.is_set())
            self.assertEqual(spawned.call_count, 2)
            self.assertTrue(all(process.poll() is not None and process.stdin.closed and process.stdout.closed for process in processes))
            self.assertIsNone(slot._process)
            with self.assertRaises(LinkPreviewWorkerError):
                slot.execute(kind="research_page", url="https://python.org/")

    def test_replacement_thread_failure_uses_same_cleanup_and_fences_slot(self):
        processes, threads = [], []
        def create(*args, **kwargs):
            process = Mock()
            process.pid = 40000 + len(processes)
            process.stdin, process.stdout = io.BytesIO(), io.BytesIO()
            process.poll.return_value = None
            def reaped(*args, **kwargs):
                process.poll.return_value = -15
                return -15
            process.wait.side_effect = reaped
            processes.append(process)
            return process
        def thread(*args, **kwargs):
            value = Mock(ident=None)
            value.is_alive.return_value = False
            threads.append(value)
            if len(threads) == 2:
                value.start.side_effect = RuntimeError("replacement startup failure")
            return value
        with (patch.object(workers.subprocess, "Popen", side_effect=create),
              patch.object(workers.threading, "Thread", side_effect=thread), patch.object(workers.os, "killpg")):
            slot = workers._WorkerSlot(("fixed",), clock=time.monotonic, environment={})
            with self.assertRaisesRegex(RuntimeError, "replacement startup failure"):
                slot.replace()
            self.assertTrue(slot._shutdown)
            self.assertIsNone(slot._process)
            self.assertTrue(all(process.poll() is not None and process.stdin.closed and process.stdout.closed for process in processes))
            slot.close()

    def test_unreaped_child_and_unjoined_reader_retain_ownership_without_replacement(self):
        for mode in ("unreaped", "reader"):
            process = Mock()
            process.pid = 40000
            process.stdin, process.stdout = io.BytesIO(), io.BytesIO()
            process.poll.return_value = None
            thread = Mock()
            thread.ident = 11
            thread.start.side_effect = RuntimeError("owned startup failure")
            thread.is_alive.return_value = mode == "reader"
            if mode == "unreaped":
                process.wait.side_effect = subprocess.TimeoutExpired("owned", .5)
            else:
                def reaped(*args, **kwargs):
                    process.poll.return_value = -15
                    return -15
                process.wait.side_effect = reaped
            with (self.subTest(mode=mode), patch.object(workers.subprocess, "Popen", return_value=process) as spawned,
                  patch.object(workers.threading, "Thread", return_value=thread), patch.object(workers.os, "killpg"),
                  self.assertRaisesRegex(RuntimeError, "owned startup failure") as raised):
                readers.PublicPageReader()
            owner = raised.exception._mentat_worker_owner
            self.assertIs(owner._process, process)
            self.assertIs(owner._reader, thread)
            self.assertTrue(owner._shutdown)
            self.assertEqual(spawned.call_count, 1)
            with self.assertRaises(LinkPreviewWorkerError):
                owner.execute(kind="research_page", url="https://python.org/")
            # Explicit recovery can finish the same ownership; no new child.
            process.poll.return_value = -15
            thread.is_alive.return_value = False
            with patch.object(workers.os, "killpg"):
                owner.close()
            self.assertIsNone(owner._process)
            self.assertIsNone(owner._reader)

    def test_actual_first_and_second_slot_start_failure_leave_no_process_or_reader(self):
        original_popen, original_start = workers.subprocess.Popen, workers.threading.Thread.start
        for failing_start in (1, 2):
            processes, threads = [], []
            def create(*args, **kwargs):
                process = original_popen(*args, **kwargs)
                processes.append(process)
                return process
            def start(thread):
                threads.append(thread)
                if len(threads) == failing_start:
                    raise RuntimeError("owned actual startup failure")
                return original_start(thread)
            with (self.subTest(failing_start=failing_start),
                  patch.object(workers.subprocess, "Popen", side_effect=create),
                  patch.object(workers.threading.Thread, "start", start),
                  self.assertRaisesRegex(RuntimeError, "owned actual startup failure")):
                readers.PublicPageReader()
            self.assertEqual(len(processes), failing_start)
            self.assertTrue(all(process.poll() is not None for process in processes))
            self.assertTrue(all(process.stdin.closed and process.stdout.closed for process in processes))
            self.assertTrue(all(not thread.is_alive() for thread in threads))

    def test_first_and_second_slot_thread_start_failure_reap_children_and_close_pipes(self):
        for reader_kind, failing_start in (("research", 1), ("research", 2), ("preview", 1), ("preview", 2)):
            processes = []
            threads = []
            def process_factory(*args, **kwargs):
                process = Mock()
                process.pid = 40000 + len(processes)
                process.stdin, process.stdout = io.BytesIO(), io.BytesIO()
                process.poll.return_value = None
                def reaped(*args, **kwargs):
                    process.poll.return_value = -15
                    return -15
                process.wait.side_effect = reaped
                processes.append(process)
                return process
            def thread_factory(*args, **kwargs):
                thread = Mock()
                thread.ident = None
                thread.is_alive.return_value = False
                threads.append(thread)
                if len(threads) == failing_start:
                    thread.start.side_effect = RuntimeError("owned startup failure")
                return thread
            with (self.subTest(reader_kind=reader_kind, failing_start=failing_start),
                  patch.object(workers.subprocess, "Popen", side_effect=process_factory),
                  patch.object(workers.threading, "Thread", side_effect=thread_factory),
                  patch.object(workers.os, "killpg") as signalled,
                  self.assertRaisesRegex(RuntimeError, "owned startup failure")):
                if reader_kind == "research":
                    readers.PublicPageReader()
                else:
                    workers.LinkPreviewWorkerPool(command=("fixed",), environ={})
            self.assertEqual(len(processes), failing_start)
            for process in processes:
                process.wait.assert_called_once()
                self.assertTrue(process.stdin.closed)
                self.assertTrue(process.stdout.closed)
                self.assertIn(process.pid, [call.args[0] for call in signalled.call_args_list])

    def test_actual_worker_rejects_private_url_and_has_finite_resources(self):
        reader = readers.PublicPageReader()
        try:
            for slot in reader._slots:
                self.assertEqual(set(slot._environment), {"LANG", "PYTHONUTF8"})
                status = Path('/proc/' + str(slot._process.pid) + '/limits')
                deadline = time.monotonic() + 2
                text = status.read_text()
                while '268435456' not in text and time.monotonic() < deadline:
                    time.sleep(.01)
                    text = status.read_text()
                self.assertIn('268435456', text)
            with self.assertRaises(LinkPreviewPolicyError):
                reader.read_page("https://127.0.0.1/")
        finally:
            reader.close()

    def test_dns_watchdog_replaces_without_resubmitting_and_keeps_other_slot(self):
        with TemporaryDirectory() as temporary:
            requests = Path(temporary) / "requests"
            script = '''import json,os,sys,time
for line in sys.stdin:
 request=json.loads(line)
 with open(REQUESTS,'a') as out:out.write(request['url']+'\\n')
 if request['url'].endswith('/hang'):
  print(json.dumps({'type':'phase','phase':'dns'}),flush=True);time.sleep(30)
 result={'status':'ready','final_url':request['url'],'title':'','text':str(os.getpid()),'text_truncated':False,'links':[]}
 print(json.dumps({'type':'result','id':request['id'],'result':result}),flush=True)
'''.replace("REQUESTS", repr(str(requests)))
            with patch.object(readers, "_command", return_value=(sys.executable, "-I", "-u", "-c", script)):
                reader = readers.PublicPageReader()
                try:
                    first = [slot._process.pid for slot in reader._slots]
                    with self.assertRaises(LinkPreviewWorkerError):
                        reader.read_page("https://python.org/hang")
                    unaffected = reader.read_page("https://python.org/normal")
                    replacement = reader.read_page("https://python.org/normal")
                    self.assertEqual(int(unaffected["text"]), first[1])
                    self.assertNotIn(int(replacement["text"]), first)
                    self.assertEqual(requests.read_text().splitlines().count("https://python.org/hang"), 1)
                finally:
                    reader.close()


if __name__ == "__main__":
    unittest.main()
