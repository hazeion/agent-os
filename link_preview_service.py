"""Message-bound asynchronous orchestration for safe rich-link previews."""

from __future__ import annotations

import base64
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import re
import threading
from typing import Callable, Protocol

from conversation_repository import ConversationRepositoryError
from link_preview_cache import (
    BLOCKED_SECONDS,
    LinkPreviewCache,
    LinkPreviewCacheError,
    LinkPreviewPreference,
    LinkPreviewPreferenceStore,
    MAXIMUM_READY_SECONDS,
    UNAVAILABLE_SECONDS,
)
from link_preview_policy import LinkPreviewPolicyError, normalize_preview_url
from link_preview_workers import LinkPreviewWorkerError, LinkPreviewWorkerPool
from link_preview_webp import valid_transformed_webp


MAXIMUM_MESSAGE_URLS = 3
MAXIMUM_PENDING_JOBS = 8
MAXIMUM_EPHEMERAL_ENTRIES = 512
_HTTPS_CANDIDATE = re.compile(r"https://[^\s<>\"'`]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = re.compile(r"[,.!?;:]+$")
_CONVERSATION_ID = re.compile(r"conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}")
_MESSAGE_ID = re.compile(r"msg_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}")
_UNSAFE_TEXT = re.compile("[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")


class LinkPreviewServiceError(RuntimeError):
    def __init__(self, code: str):
        safe = code if code in {
            "link_preview.capacity_unavailable",
            "link_preview.conflict",
            "link_preview.invalid",
            "link_preview.not_found",
            "link_preview.unavailable",
        } else "link_preview.unavailable"
        super().__init__(safe)
        self.code = safe


class MessageRepository(Protocol):
    def read_message(self, message_id: str): ...


@dataclass(frozen=True)
class _Candidate:
    ordinal: int
    normalized_url: str | None
    static_status: str | None


def _trim_candidate(value: str) -> str:
    candidate = _TRAILING_PUNCTUATION.sub("", value)
    for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
        while candidate.endswith(closing) and candidate.count(opening) < candidate.count(closing):
            candidate = candidate[:-1]
    return candidate


def _candidates(text: str) -> tuple[_Candidate, ...]:
    result: list[_Candidate] = []
    seen: set[str] = set()
    for raw_index, match in enumerate(_HTTPS_CANDIDATE.finditer(text), start=1):
        if raw_index > MAXIMUM_MESSAGE_URLS:
            break
        raw = _trim_candidate(match.group(0))
        try:
            normalized = normalize_preview_url(raw).canonical_url
        except LinkPreviewPolicyError:
            result.append(_Candidate(raw_index, None, "blocked"))
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(_Candidate(raw_index, normalized, None))
    return tuple(result)


def _message_text(message) -> str:
    try:
        parts = message.content["parts"]
        text = parts[0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LinkPreviewServiceError("link_preview.unavailable") from exc
    if not isinstance(parts, list) or len(parts) != 1 or not isinstance(text, str):
        raise LinkPreviewServiceError("link_preview.unavailable")
    return text


def _freshness(cache_control: object, vary: object) -> int | None:
    if not isinstance(cache_control, list) or not all(isinstance(value, str) for value in cache_control):
        return None
    if not isinstance(vary, list) or not all(isinstance(value, str) for value in vary):
        return None
    if any(token.strip() == "*" for value in vary for token in value.split(",")):
        return None
    directives = [token.strip().lower() for value in cache_control for token in value.split(",") if token.strip()]
    if "no-store" in directives or "no-cache" in directives:
        return None
    max_ages: list[int] = []
    for directive in directives:
        if not directive.startswith("max-age"):
            continue
        name, separator, value = directive.partition("=")
        if name != "max-age" or not separator or not value.isdecimal():
            return None
        max_ages.append(int(value))
    if len(max_ages) > 1:
        return None
    return min(MAXIMUM_READY_SECONDS, max_ages[0]) if max_ages else MAXIMUM_READY_SECONDS


def _safe_optional(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or value.strip() != value or len(value) > maximum or _UNSAFE_TEXT.search(value):
        raise LinkPreviewServiceError("link_preview.unavailable")
    return value


class LinkPreviewService:
    def __init__(
        self,
        repository: MessageRepository,
        cache: LinkPreviewCache,
        preferences: LinkPreviewPreferenceStore,
        *,
        worker_factory: Callable[[], LinkPreviewWorkerPool] = LinkPreviewWorkerPool,
        offline: Callable[[], bool] = lambda: False,
    ):
        self._repository = repository
        self._cache = cache
        self._preferences = preferences
        self._worker_factory = worker_factory
        self._offline = offline
        self._workers: LinkPreviewWorkerPool | None = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mentat-link-preview")
        self._pending: dict[tuple[str, int, int], Future[None] | None] = {}
        self._ephemeral: OrderedDict[tuple[str, int, int], dict[str, object]] = OrderedDict()
        self._lock = threading.RLock()
        self._closed = False
        self._generation = 0

    def _remember_ephemeral_locked(self, key: tuple[str, int, int], projection: dict[str, object]) -> None:
        self._ephemeral.pop(key, None)
        self._ephemeral[key] = dict(projection)
        while len(self._ephemeral) > MAXIMUM_EPHEMERAL_ENTRIES:
            self._ephemeral.popitem(last=False)

    def _exact_message(self, conversation_id: str, message_id: str, revision: int):
        if (
            not isinstance(conversation_id, str)
            or not _CONVERSATION_ID.fullmatch(conversation_id)
            or not isinstance(message_id, str)
            or not _MESSAGE_ID.fullmatch(message_id)
            or type(revision) is not int
            or revision < 1
        ):
            raise LinkPreviewServiceError("link_preview.invalid")
        try:
            message = self._repository.read_message(message_id)
        except ConversationRepositoryError as exc:
            code = "link_preview.not_found" if exc.code.endswith("not_found") else "link_preview.unavailable"
            raise LinkPreviewServiceError(code) from exc
        if message.conversation_id != conversation_id or message.revision != revision:
            raise LinkPreviewServiceError("link_preview.conflict")
        if message.role != "user" or message.state != "accepted":
            raise LinkPreviewServiceError("link_preview.conflict")
        return message

    def _current_locked(self, conversation_id: str, message_id: str, revision: int, generation: int) -> bool:
        if generation != self._generation or self._closed:
            return False
        try:
            self._exact_message(conversation_id, message_id, revision)
            return self._preferences.read().enabled
        except (LinkPreviewServiceError, LinkPreviewCacheError, OSError, ValueError):
            return False

    def _pool(self, generation: int, conversation_id: str, message_id: str, revision: int) -> LinkPreviewWorkerPool:
        with self._lock:
            if not self._current_locked(conversation_id, message_id, revision, generation):
                raise LinkPreviewServiceError("link_preview.unavailable")
            if self._workers is None:
                self._workers = self._worker_factory()
            return self._workers

    def enqueue(
        self,
        *,
        conversation_id: str,
        message_id: str,
        message_revision: int,
        retry: bool = False,
    ) -> dict[str, object]:
        if type(retry) is not bool:
            raise LinkPreviewServiceError("link_preview.invalid")
        message = self._exact_message(conversation_id, message_id, message_revision)
        candidates = _candidates(_message_text(message))
        preference = self._preferences.read()
        if not preference.enabled or self._offline():
            return self.read(conversation_id=conversation_id, message_id=message_id, message_revision=message_revision)
        for candidate in candidates:
            key = (message_id, message_revision, candidate.ordinal)
            if candidate.normalized_url is None:
                continue
            if not retry and self._cache.lookup(candidate.normalized_url) is not None:
                continue
            with self._lock:
                if key in self._pending:
                    continue
                if len(self._pending) >= MAXIMUM_PENDING_JOBS:
                    self._remember_ephemeral_locked(key, {"candidate_ordinal": candidate.ordinal, "status": "unavailable"})
                    continue
                self._pending[key] = None
                try:
                    future = self._executor.submit(
                    self._run_candidate,
                        conversation_id,
                        message_id,
                        message_revision,
                    candidate,
                    self._generation,
                    )
                except RuntimeError:
                    self._pending.pop(key, None)
                    self._remember_ephemeral_locked(key, {"candidate_ordinal": candidate.ordinal, "status": "unavailable"})
                    continue
                if key in self._pending:
                    self._pending[key] = future
        return self.read(conversation_id=conversation_id, message_id=message_id, message_revision=message_revision)

    def _still_current(self, conversation_id: str, message_id: str, revision: int, generation: int) -> bool:
        with self._lock:
            return self._current_locked(conversation_id, message_id, revision, generation)

    def _publish_status(
        self,
        conversation_id: str,
        message_id: str,
        revision: int,
        generation: int,
        key: tuple[str, int, int],
        candidate: _Candidate,
        status: str,
        *,
        persist: bool,
    ) -> None:
        with self._lock:
            if not self._current_locked(conversation_id, message_id, revision, generation):
                return
            if persist and candidate.normalized_url is not None:
                self._cache.store(candidate.normalized_url, final_normalized_url=candidate.normalized_url, status=status, ttl_seconds=BLOCKED_SECONDS if status == "blocked" else UNAVAILABLE_SECONDS)
                self._ephemeral.pop(key, None)
            else:
                self._remember_ephemeral_locked(key, {"candidate_ordinal": candidate.ordinal, "status": status})

    def _run_candidate(self, conversation_id: str, message_id: str, revision: int, candidate: _Candidate, generation: int) -> None:
        key = (message_id, revision, candidate.ordinal)
        try:
            if candidate.normalized_url is None or not self._still_current(conversation_id, message_id, revision, generation):
                return
            try:
                page = self._pool(generation, conversation_id, message_id, revision).execute(kind="page", normalized_url=candidate.normalized_url)
            except LinkPreviewWorkerError as exc:
                status = "blocked" if exc.code == "link_preview.blocked" else "unavailable"
                self._publish_status(conversation_id, message_id, revision, generation, key, candidate, status, persist=exc.code != "link_preview.capacity_unavailable")
                return
            if page == {"status": "unavailable"}:
                self._publish_status(conversation_id, message_id, revision, generation, key, candidate, "unavailable", persist=True)
                return
            projection, transient = self._page_result(candidate.ordinal, page)
            image: bytes | None = None
            image_final_url: str | None = None
            if transient["image_candidate"] is not None and self._still_current(conversation_id, message_id, revision, generation):
                try:
                    image_result = self._pool(generation, conversation_id, message_id, revision).execute(kind="image", normalized_url=transient["image_candidate"])
                    image, image_final_url = self._image_result(image_result)
                except LinkPreviewWorkerError:
                    image = None
            ttl = _freshness(transient["cache_control"], transient["vary"])
            with self._lock:
                if not self._current_locked(conversation_id, message_id, revision, generation):
                    return
                if ttl is not None and ttl > 0:
                    stored = self._cache.store(
                        candidate.normalized_url,
                        final_normalized_url=transient["final_url"],
                        status="ready",
                        ttl_seconds=ttl,
                        title=projection.get("title"),
                        description=projection.get("description"),
                        site_name=projection.get("site_name"),
                        display_host=projection.get("display_host"),
                        image_alt=projection.get("image_alt"),
                        image_webp=image,
                        image_normalized_url=transient["image_candidate"] if image is not None else None,
                        image_final_normalized_url=image_final_url if image is not None else None,
                    )
                    projection = {"candidate_ordinal": candidate.ordinal, **stored}
                    self._ephemeral.pop(key, None)
                else:
                    self._remember_ephemeral_locked(key, projection)
        except (LinkPreviewCacheError, LinkPreviewServiceError, OSError, ValueError):
            with self._lock:
                if self._current_locked(conversation_id, message_id, revision, generation):
                    self._remember_ephemeral_locked(key, {"candidate_ordinal": candidate.ordinal, "status": "unavailable"})
        finally:
            with self._lock:
                self._pending.pop(key, None)

    @staticmethod
    def _page_result(ordinal: int, value: object) -> tuple[dict[str, object], dict[str, object]]:
        expected = {"cache_control", "description", "display_host", "final_url", "image_alt", "image_candidate", "site_name", "status", "title", "vary"}
        if not isinstance(value, dict) or set(value) != expected or value.get("status") != "ready":
            raise LinkPreviewServiceError("link_preview.unavailable")
        final_url = value.get("final_url")
        image_candidate = value.get("image_candidate")
        if not isinstance(final_url, str):
            raise LinkPreviewServiceError("link_preview.unavailable")
        final_normalized = normalize_preview_url(final_url)
        final_url = final_normalized.canonical_url
        if image_candidate is not None:
            if not isinstance(image_candidate, str):
                raise LinkPreviewServiceError("link_preview.unavailable")
            image_candidate = normalize_preview_url(image_candidate).canonical_url
        title = _safe_optional(value.get("title"), 200)
        description = _safe_optional(value.get("description"), 500)
        display_host = _safe_optional(value.get("display_host"), 253)
        if title is None and description is None or display_host is None:
            raise LinkPreviewServiceError("link_preview.unavailable")
        if display_host != final_normalized.host:
            raise LinkPreviewServiceError("link_preview.unavailable")
        projection = {
            "candidate_ordinal": ordinal,
            "description": description,
            "display_host": display_host,
            "image_alt": _safe_optional(value.get("image_alt"), 200),
            "site_name": _safe_optional(value.get("site_name"), 120),
            "status": "ready",
            "title": title,
        }
        projection = {key: item for key, item in projection.items() if item is not None}
        return projection, {
            "cache_control": value["cache_control"],
            "final_url": final_url,
            "image_candidate": image_candidate,
            "vary": value["vary"],
        }

    @staticmethod
    def _image_result(value: object) -> tuple[bytes | None, str | None]:
        if value == {"status": "unavailable"}:
            return None, None
        if not isinstance(value, dict) or set(value) != {"body", "final_url", "status"} or value.get("status") != "ready" or not isinstance(value.get("body"), str) or not isinstance(value.get("final_url"), str):
            raise LinkPreviewServiceError("link_preview.unavailable")
        final_url = normalize_preview_url(value["final_url"]).canonical_url
        try:
            body = base64.b64decode(value["body"], validate=True)
        except (ValueError, TypeError) as exc:
            raise LinkPreviewServiceError("link_preview.unavailable") from exc
        return (body, final_url) if valid_transformed_webp(body) else (None, None)

    def read(self, *, conversation_id: str, message_id: str, message_revision: int) -> dict[str, object]:
        message = self._exact_message(conversation_id, message_id, message_revision)
        candidates = _candidates(_message_text(message))
        preference = self._preferences.read()
        previews: list[dict[str, object]] = []
        for candidate in candidates:
            key = (message_id, message_revision, candidate.ordinal)
            if not preference.enabled:
                previews.append({
                    "candidate_ordinal": candidate.ordinal,
                    "status": "disabled" if candidate.normalized_url is not None else "blocked",
                })
                continue
            with self._lock:
                pending = key in self._pending
                ephemeral = self._ephemeral.get(key)
                if ephemeral is not None:
                    self._ephemeral.move_to_end(key)
            if pending:
                previews.append({"candidate_ordinal": candidate.ordinal, "status": "pending"})
            elif ephemeral is not None:
                previews.append(dict(ephemeral))
            elif candidate.normalized_url is None:
                previews.append({"candidate_ordinal": candidate.ordinal, "status": candidate.static_status or "blocked"})
            else:
                cached = self._cache.lookup(candidate.normalized_url)
                if cached is not None:
                    previews.append({"candidate_ordinal": candidate.ordinal, **cached})
                else:
                    previews.append({"candidate_ordinal": candidate.ordinal, "status": "unavailable"})
        return {
            "schema_version": 1,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "message_revision": message_revision,
            "enabled": preference.enabled,
            "previews": previews,
        }

    def preference(self) -> LinkPreviewPreference:
        return self._preferences.read()

    def update_preference(self, *, enabled: bool, expected_revision: int) -> LinkPreviewPreference:
        workers: LinkPreviewWorkerPool | None = None
        futures: tuple[Future[None], ...] = ()
        with self._lock:
            updated = self._preferences.update(enabled=enabled, expected_revision=expected_revision)
            if not updated.enabled:
                futures = tuple(future for future in self._pending.values() if future is not None)
                self._ephemeral.clear()
                self._generation += 1
                workers = self._workers
                self._workers = None
        if not updated.enabled:
            for future in futures:
                future.cancel()
            if workers is not None:
                workers.close()
        return updated

    def clear_cache(self) -> None:
        with self._lock:
            self._generation += 1
            self._ephemeral.clear()
            self._cache.clear()

    def image(self, image_id: str) -> tuple[bytes, int] | None:
        if not self._preferences.read().enabled:
            return None
        return self._cache.image(image_id)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            workers = self._workers
            self._workers = None
            futures = tuple(future for future in self._pending.values() if future is not None)
        for future in futures:
            future.cancel()
        if workers is not None:
            workers.close()
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["LinkPreviewService", "LinkPreviewServiceError", "MAXIMUM_EPHEMERAL_ENTRIES"]
