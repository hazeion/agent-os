"""Binding-aware local CLI and remote Runs API Agent Console transports."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable

from remote_hermes import RemoteHermesClient, RemoteHermesError, load_connection


class HermesTransportError(RuntimeError):
    """Bounded transport failure with no endpoint, credential, or local path."""

    _MESSAGES = {
        "transport_binding_changed": "The Hermes connection changed before this operation could start.",
        "transport_unavailable": "Hermes connection settings are unavailable.",
        "local_console_unavailable": "Hermes CLI was not found in the Mentat server environment.",
        "remote_console_not_implemented": "Remote Agent Console is not available yet.",
        "remote_run_capability_unavailable": "This Hermes host does not support remote Console runs.",
        "remote_session_capability_unavailable": "This Hermes host does not support remote session history.",
        "remote_session_not_found": "That remote session is no longer available.",
        "remote_session_unavailable": "Remote session history is unavailable.",
        "remote_session_alias_invalid": "That remote session selection is no longer valid.",
        "remote_capability_inventory_unavailable": "This Hermes host does not support read-only skills and toolsets visibility.",
        "remote_capability_inventory_schema_invalid": "This Hermes host returned an unsupported skills or toolsets inventory.",
        "remote_capability_inventory_private": "This Hermes host returned unsafe skills or toolsets metadata.",
        "remote_profile_capability_unavailable": "This Hermes host does not support complete read-only profile discovery.",
        "remote_private_reflection": "Remote content was blocked by Mentat's content-safety checks.",
        "remote_approval_unsupported": "This remote run needs approval, which Mentat cannot answer yet.",
        "remote_run_failed": "The remote Hermes run failed.",
        "remote_submission_unverified": "Mentat could not verify whether the remote run started.",
        "remote_stop_unverified": "Mentat could not verify that the remote run stopped.",
        "console_request_invalid": "The Hermes Console request is invalid.",
    }

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code

    @property
    def public_message(self) -> str:
        return self._MESSAGES.get(
            self.code,
            "Hermes transport is unavailable.",
        )


@dataclass(frozen=True)
class TransportBinding:
    mode: str
    label: str
    binding_id: str

    def public_summary(
        self,
        *,
        console_available: bool,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mode": self.mode,
            "label": self.label,
            "binding_id": self.binding_id,
            "console_available": console_available,
        }
        if error_code:
            payload["error_code"] = error_code
        return payload


@dataclass(frozen=True)
class LocalConsoleLaunch:
    command: tuple[str, ...]
    cwd: str
    env: dict[str, str]


class HermesConsoleTransport:
    """Transport-neutral Console interface bound to one selected authority."""

    mode = "unavailable"
    console_available = False
    unavailable_code = "remote_console_not_implemented"

    def __init__(self, binding: TransportBinding):
        self.binding = binding

    def public_summary(self) -> dict[str, Any]:
        return self.binding.public_summary(
            console_available=self.console_available,
            error_code=None if self.console_available else self.unavailable_code,
        )

    def revalidate(self, data_root: Path) -> None:
        try:
            selected = load_connection(Path(data_root))
        except RemoteHermesError as exc:
            raise HermesTransportError("transport_unavailable") from exc
        if (
            selected.mode != self.binding.mode
            or selected.label != self.binding.label
            or selected.binding_id != self.binding.binding_id
        ):
            raise HermesTransportError("transport_binding_changed")

    def build_console_launch(
        self,
        *,
        profile_id: str,
        prompt: str,
        session_id: str | None,
        image_path: Path | None,
    ) -> LocalConsoleLaunch:
        raise HermesTransportError(self.unavailable_code)

    def spawn_console(self, launch: LocalConsoleLaunch):
        raise HermesTransportError(self.unavailable_code)


class RemoteHermesConsoleTransport(HermesConsoleTransport):
    mode = "remote"
    unavailable_code = "remote_run_capability_unavailable"

    def __init__(
        self,
        binding: TransportBinding,
        *,
        client: RemoteHermesClient,
    ):
        super().__init__(binding)
        self._client = client
        self._ready = False
        self._sessions_ready = False
        self.model = "configured default"

    @property
    def console_available(self) -> bool:
        return self._ready

    def prepare_console(self) -> dict[str, Any]:
        try:
            discovery = self._client.require_console_run_capabilities()
        except RemoteHermesError as exc:
            self._ready = False
            raise HermesTransportError(exc.code) from exc
        self.model = str(discovery.get("model") or "configured default")
        self._ready = True
        return {
            "model": self.model,
            "capabilities": tuple(discovery.get("capabilities") or ()),
        }

    @property
    def session_visibility_available(self) -> bool:
        return self._sessions_ready

    def prepare_sessions(self) -> dict[str, Any]:
        try:
            discovery = self._client.require_session_resource_capabilities()
        except RemoteHermesError as exc:
            self._sessions_ready = False
            raise HermesTransportError(exc.code) from exc
        self._sessions_ready = True
        return {"capabilities": tuple(discovery.get("capabilities") or ())}

    def list_sessions(self) -> dict[str, Any]:
        if not self._sessions_ready:
            raise HermesTransportError("remote_session_capability_unavailable")
        try:
            return self._client.list_sessions()
        except RemoteHermesError as exc:
            raise HermesTransportError(exc.code) from exc

    def get_session(self, remote_session_id: str) -> dict[str, Any]:
        if not self._sessions_ready:
            raise HermesTransportError("remote_session_capability_unavailable")
        try:
            return self._client.get_session(remote_session_id)
        except RemoteHermesError as exc:
            raise HermesTransportError(exc.code) from exc

    def get_session_messages(
        self,
        remote_session_id: str,
        *,
        structural_ids: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        if not self._sessions_ready:
            raise HermesTransportError("remote_session_capability_unavailable")
        try:
            return self._client.get_session_messages(
                remote_session_id,
                structural_ids=structural_ids,
            )
        except RemoteHermesError as exc:
            raise HermesTransportError(exc.code) from exc

    def read_capability_inventory(self) -> dict[str, Any]:
        try:
            return self._client.read_capability_inventory()
        except RemoteHermesError as exc:
            raise HermesTransportError(exc.code) from exc

    def submit_run(
        self,
        prompt: str,
        *,
        continuation: dict[str, Any] | None = None,
        image_data_urls: list[str] | None = None,
    ) -> dict[str, str]:
        if not self._ready:
            raise HermesTransportError(self.unavailable_code)
        try:
            if continuation is not None and image_data_urls is not None:
                raise HermesTransportError("console_request_invalid")
            if continuation is not None:
                return self._client.submit_continuation(prompt, continuation)
            if image_data_urls is not None:
                return self._client.submit_run_with_images(prompt, image_data_urls)
            return self._client.submit_run(prompt)
        except RemoteHermesError as exc:
            raise HermesTransportError(exc.code) from exc

    def get_continuation_descriptor(self, remote_session_id: str) -> dict[str, Any]:
        try:
            return self._client.get_continuation_descriptor(remote_session_id)
        except RemoteHermesError as exc:
            raise HermesTransportError(exc.code) from exc

    def respond_to_approval(self, remote_run_id: str, request_id: str, choice: str) -> dict[str, Any]:
        try:
            return self._client.respond_to_approval(remote_run_id, request_id, choice)
        except RemoteHermesError as exc:
            raise HermesTransportError(exc.code) from exc

    def respond_to_clarification(self, remote_run_id: str, request_id: str, response: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._client.respond_to_clarification(remote_run_id, request_id, response)
        except RemoteHermesError as exc:
            raise HermesTransportError(exc.code) from exc

    def read_profiles(self) -> list[dict[str, Any]]:
        try:
            method = getattr(self._client, "read_profiles", None)
            if not callable(method):
                raise HermesTransportError("remote_profile_capability_unavailable")
            return method()
        except RemoteHermesError as exc:
            raise HermesTransportError(exc.code) from exc

    def get_run(self, remote_run_id: str) -> dict[str, Any]:
        try:
            return self._client.get_run(remote_run_id)
        except RemoteHermesError as exc:
            raise HermesTransportError(exc.code) from exc

    def iter_run_events(
        self,
        remote_run_id: str,
        *,
        should_stop: Callable[[], bool] | None = None,
    ):
        try:
            yield from self._client.iter_run_events(
                remote_run_id,
                should_stop=should_stop,
            )
        except RemoteHermesError as exc:
            raise HermesTransportError(exc.code) from exc

    def stop_run(self, remote_run_id: str) -> dict[str, str]:
        try:
            return self._client.stop_run(remote_run_id)
        except RemoteHermesError as exc:
            raise HermesTransportError(exc.code) from exc


class LocalHermesConsoleTransport(HermesConsoleTransport):
    mode = "local"
    unavailable_code = "local_console_unavailable"

    def __init__(
        self,
        binding: TransportBinding,
        *,
        command_path: str | None,
        hermes_home: Path,
        cwd: Path,
        shared_bin: Path | None = None,
        popen_factory: Callable[..., Any] | None = None,
    ):
        super().__init__(binding)
        self.command_path = str(command_path) if command_path else None
        self.hermes_home = Path(hermes_home)
        self.cwd = Path(cwd)
        self.shared_bin = Path(shared_bin) if shared_bin is not None else None
        self._popen_factory = popen_factory

    @property
    def console_available(self) -> bool:
        return bool(self.command_path)

    def build_console_launch(
        self,
        *,
        profile_id: str,
        prompt: str,
        session_id: str | None,
        image_path: Path | None,
    ) -> LocalConsoleLaunch:
        if not self.command_path:
            raise HermesTransportError("local_console_unavailable")
        if not isinstance(profile_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{0,63}",
            profile_id,
        ):
            raise HermesTransportError("console_request_invalid")
        if not isinstance(prompt, str) or not prompt:
            raise HermesTransportError("console_request_invalid")
        if session_id is not None and (
            not isinstance(session_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_.:-]+", session_id)
        ):
            raise HermesTransportError("console_request_invalid")

        command = [
            self.command_path,
            "-p",
            profile_id,
            "chat",
            "-q",
            prompt,
            "-Q",
            "--source",
            "mentat",
        ]
        if image_path is not None:
            command.extend(["--image", str(image_path)])
        if session_id:
            command.extend(["--resume", session_id])

        env = os.environ.copy()
        env["HERMES_HOME"] = str(self.hermes_home)
        env["PYTHONUNBUFFERED"] = "1"
        if self.shared_bin is not None:
            current_path = env.get("PATH") or ""
            path_entries = current_path.split(os.pathsep) if current_path else []
            if str(self.shared_bin) not in path_entries:
                env["PATH"] = os.pathsep.join(
                    [str(self.shared_bin), *path_entries]
                )
        return LocalConsoleLaunch(tuple(command), str(self.cwd), env)

    def spawn_console(self, launch: LocalConsoleLaunch):
        factory = self._popen_factory or subprocess.Popen
        return factory(
            list(launch.command),
            cwd=launch.cwd,
            env=launch.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )


def select_hermes_console_transport(
    data_root: Path,
    *,
    local_builder: Callable[[TransportBinding], LocalHermesConsoleTransport],
    remote_builder: Callable[[TransportBinding, str, str], RemoteHermesConsoleTransport] | None = None,
) -> HermesConsoleTransport:
    """Select exactly one adapter without touching local state in remote mode."""

    selected = load_connection(Path(data_root))
    binding = TransportBinding(
        mode=selected.mode,
        label=selected.label,
        binding_id=selected.binding_id,
    )
    if selected.mode == "remote":
        builder = remote_builder or (
            lambda current_binding, endpoint, api_key: RemoteHermesConsoleTransport(
                current_binding,
                client=RemoteHermesClient(endpoint, api_key),
            )
        )
        adapter = builder(
            binding,
            selected.endpoint or "",
            selected.api_key or "",
        )
        if not isinstance(adapter, RemoteHermesConsoleTransport):
            raise HermesTransportError("transport_unavailable")
        if adapter.binding != binding:
            raise HermesTransportError("transport_binding_changed")
        return adapter
    adapter = local_builder(binding)
    if not isinstance(adapter, LocalHermesConsoleTransport):
        raise HermesTransportError("local_console_unavailable")
    if adapter.binding != binding:
        raise HermesTransportError("transport_binding_changed")
    return adapter


__all__ = [
    "HermesConsoleTransport",
    "HermesTransportError",
    "LocalConsoleLaunch",
    "LocalHermesConsoleTransport",
    "RemoteHermesConsoleTransport",
    "TransportBinding",
    "select_hermes_console_transport",
]
