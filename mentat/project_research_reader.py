"""Private Linux public-page prerequisite, never a browser/Run capability."""
from __future__ import annotations

from pathlib import Path
import queue
import sys
import threading
import time

from link_preview_policy import normalize_preview_url
from link_preview_workers import LinkPreviewWorkerError, _WorkerSlot, minimal_worker_environment
from mentat.project_research_page import MAX_TEXT, MAX_LINKS, _clean


def _command():
    root = Path(__file__).resolve().parent.parent
    bootstrap = f"import runpy,sys;sys.path.insert(0,{str(root)!r});runpy.run_module('mentat.project_research_worker',run_name='__main__')"
    return (sys.executable, "-I", "-c", bootstrap)


def _validate(result):
    if (not isinstance(result, dict) or set(result) != {"status", "final_url", "title", "text", "text_truncated", "links"}
            or result["status"] != "ready" or type(result["text_truncated"]) is not bool
            or not isinstance(result["links"], list) or len(result["links"]) > MAX_LINKS):
        raise ValueError()
    for key, maximum in (("title", 512), ("text", MAX_TEXT)):
        value = result[key]
        if not isinstance(value, str) or len(value.encode("utf-8")) > maximum or _clean(value) != value:
            raise ValueError()
    if normalize_preview_url(result["final_url"]).canonical_url != result["final_url"]:
        raise ValueError()
    seen = set()
    for link in result["links"]:
        if (not isinstance(link, dict) or set(link) != {"url", "text"}
                or normalize_preview_url(link["url"]).canonical_url != link["url"] or link["url"] in seen
                or not isinstance(link["text"], str) or len(link["text"].encode("utf-8")) > 256
                or _clean(link["text"]) != link["text"]):
            raise ValueError()
        seen.add(link["url"])
    return result


class PublicPageReader:
    """Two dedicated slots; no caller command, header, method or environment."""
    def __init__(self):
        if sys.platform != "linux":
            raise LinkPreviewWorkerError("link_preview.unavailable")
        self._closed = False
        self._guard = threading.Lock()
        self._slots = []
        self._available = queue.Queue(maxsize=2)
        try:
            for _ in range(2):
                slot = _WorkerSlot(_command(), clock=time.monotonic, environment=minimal_worker_environment(),
                                   operation_watchdog_seconds=10.25, maximum_line_bytes=256 * 1024)
                self._slots.append(slot)
                self._available.put_nowait(slot)
        except BaseException as startup_error:
            try:
                self.close()
            except BaseException:
                startup_error._mentat_reader_owner = self
                raise startup_error from None
            raise

    def read_page(self, url: str):
        normalized = normalize_preview_url(url)
        with self._guard:
            if self._closed:
                raise LinkPreviewWorkerError("link_preview.unavailable")
        try:
            slot = self._available.get(timeout=.25)
        except queue.Empty:
            raise LinkPreviewWorkerError("link_preview.capacity_unavailable") from None
        try:
            result = slot.execute(kind="research_page", url=normalized.canonical_url)
            try:
                validated = _validate(result)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                slot.replace()
                raise LinkPreviewWorkerError("link_preview.unavailable") from None
            with self._guard:
                if self._closed:
                    raise LinkPreviewWorkerError("link_preview.unavailable")
                return validated
        finally:
            with self._guard:
                if not self._closed:
                    self._available.put_nowait(slot)

    def close(self):
        with self._guard:
            self._closed = True
        failure = None
        for slot in self._slots:
            try:
                slot.abort()
            except BaseException as error:
                # Resource teardown attempts all slots before re-raising even
                # an interrupt or unexpected bug, with recovery ownership.
                failure = failure or error
        if failure is not None:
            failure._mentat_reader_owner = self
            raise failure
