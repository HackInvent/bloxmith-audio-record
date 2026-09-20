# -----------------------------------------------------------------------------
# Role: Implements the browser audio recording block runtime and UI contract.
# File Name: block.py
# Author: Alexandre EL
# Email: alex@hackinvent.com
# Created Date: 2026-06-20
# -----------------------------------------------------------------------------

from __future__ import annotations

import base64
import binascii
from html import escape
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from types import SimpleNamespace
from typing import Any

from bloxsmith_app.block_api import (
    APPLICATION_JSON,
    BlockDefinition,
    BlockRuntimeContext,
    BlockRuntimeOutput,
    BlockRuntimeResult,
    FILE_PATH,
    render_inspector_template,
    render_mini_node_card_template,
    render_node_card_template,
)


DEFAULT_AUDIO_OUTPUT_DIR = "exports/audio"
DEFAULT_AUDIO_FILENAME_TEMPLATE = "audio_{node_id}_{timestamp}"
DEFAULT_AUDIO_TARGET_FORMAT = "native"
DEFAULT_MAX_DURATION_SEC = 120
MAX_BROWSER_AUDIO_BYTES = 80 * 1024 * 1024
SUPPORTED_TARGET_FORMATS = {"native", "webm", "mp3", "m4a"}
SUPPORTED_BROWSER_AUDIO_EXTENSIONS = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}
TARGET_FORMAT_MIME_TYPES = {
    "webm": "audio/webm",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
}


# Functional behavior:
# FB1 - Record microphone audio in the operator browser through block-owned HTML/JS.
# FB2 - Store the browser-submitted audio file under the configured exports/audio directory.
# FB3 - Optionally transcode browser audio to mp3/m4a/webm when FFmpeg is available.
# FB4 - Emit the latest saved audio path and metadata in centralized and zeromq_active runtimes.
# FB5 - Keep capture settings editable through block-owned modal and inspector HTML.
# FB6 - Allow browser capture metadata patches while an active runtime is prepared.
# FB7 - Publish the captured audio path immediately when an active runtime is loaded.
# FB8 - Record from the node card through a press-and-hold microphone button.
class AudioRecordBlock(BlockDefinition):
    """Record browser microphone audio and publish the saved project-local file.

    The block owns the browser capture UI, persists submitted audio through its
    UI action, stores only the latest capture metadata in node config, and acts
    as a source block during runtime execution.
    """

    kind = "audio_record"

    def render_node_card(self, *, node: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render the Audio Record canvas card body.

        Args:
            node: Serialized audio node whose config stores latest capture data.
            payload: Optional rendering payload.

        Returns:
            Block UI payload consumed by the generic canvas shell.
        """

        config = self._ui_config(node)
        return render_node_card_template(
            block=self,
            node=node,
            node_classes=["audio-record-node"],
            replacements={
                "title": node.get("title") or self.default_title(),
                "latest_audio": self._short_path(config["latest_audio_path"]) or "Aucun audio",
                "format": config["target_format"],
                "duration": self._duration_label(config["latest_audio_duration_ms"]),
                "output_dir": escape(config["output_dir"], quote=True),
                "target_format": escape(config["target_format"], quote=True),
                "filename_template": escape(config["filename_template"], quote=True),
                "max_duration_sec": str(config["max_duration_sec"]),
            },
        )

    def render_mini_node_card(self, *, node: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render the compact Audio Record card for mobile/reduced displays."""

        config = self._ui_config(node)
        return render_mini_node_card_template(
            block=self,
            node=node,
            node_classes=["audio-record-mini-node"],
            replacements={
                "title": node.get("title") or self.default_title(),
                "latest_audio": self._short_path(config["latest_audio_path"]) or "audio",
            },
        )

    def render_inspector_panel(self, *, node: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render the Audio Record inspector panel with capture settings."""

        config = self._ui_config(node)
        template = (self.directory / "inspector_panel.html").read_text(encoding="utf-8")
        html = render_inspector_template(
            template=template,
            node={**node, "type": self.kind, "kind": self.kind},
            payload=payload,
            replacements=self._template_replacements(config),
            show_duplicate=True,
        )
        return {"html": html, "context": {"node_id": str(node.get("id") or ""), "full_panel": True}}

    def render_modal(self, *, node: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render the Audio Record modal with click-to-talk controls."""

        config = self._ui_config(node)
        template = (self.directory / "block_modal.html").read_text(encoding="utf-8")
        html = self._render_generic_modal_template(template=template, node=node, payload=payload or {})
        for key, value in self._template_replacements(config).items():
            html = html.replace(f"{{{{ {key} }}}}", str(value))
        return {
            "html": html,
            "context": {
                "node_id": str(node.get("id") or ""),
                "node_kind": self.kind,
                "max_duration_sec": config["max_duration_sec"],
            },
        }

    def execute_runtime(self, context: BlockRuntimeContext) -> BlockRuntimeResult:
        """Emit the latest saved browser audio path and metadata.

        Args:
            context: Runtime context containing persisted capture metadata.

        Returns:
            Successful file/path and metadata outputs when an audio capture has
            been saved, otherwise a failed result with actionable logs.
        """

        config = self._runtime_config(context.config)
        logs = [
            (
                f"[audio-record] {context.node_id}: latest={config['latest_audio_path'] or '-'} "
                f"format={config['target_format']} output_dir={config['output_dir']}."
            )
        ]
        output_path = self._resolve_existing_audio_path(context.root_dir, config["latest_audio_path"])
        if output_path is None:
            error = "Aucun audio navigateur capture. Ouvrez le modal du bloc et enregistrez un audio."
            logs.append(f"[audio-record-error] {context.node_id}: {error}")
            return self._failed(error, logs)

        metadata = self._audio_metadata(config=config, output_path=output_path, root_dir=context.root_dir)
        path_value = str(metadata["path"] or output_path)
        metadata_value = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        output_ports = tuple(context.output_ports or ())
        if not output_ports:
            output_ports = (
                SimpleNamespace(id=1, name="audio_path"),
                SimpleNamespace(id=2, name="metadata"),
            )

        outputs: list[BlockRuntimeOutput] = []
        for port in output_ports:
            port_id = int(getattr(port, "id", 1) or 1)
            port_name = str(getattr(port, "name", "") or ("metadata" if port_id == 2 else "audio_path"))
            if port_id == 2 or port_name == "metadata":
                outputs.append(
                    BlockRuntimeOutput(
                        port_id=port_id,
                        port_name=port_name,
                        value=metadata_value,
                        content_type=APPLICATION_JSON,
                        metadata=metadata,
                    )
                )
            else:
                outputs.append(
                    BlockRuntimeOutput(
                        port_id=port_id,
                        port_name=port_name,
                        value=path_value,
                        content_type=FILE_PATH,
                        metadata=metadata,
                    )
                )

        logs.append(f"[done] Audio Record {context.node_id}: audio disponible: {path_value}")
        return BlockRuntimeResult(
            status="success",
            outputs=outputs,
            logs=logs,
            last_message=path_value,
            content_type=FILE_PATH,
            worker_received=path_value,
            metadata=metadata,
        )

    def handle_ui_action(
        self,
        *,
        node: dict[str, Any],
        action: str,
        values: dict[str, Any],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Handle browser audio upload actions emitted by the modal JS.

        Args:
            node: Serialized audio node being edited.
            action: Block-owned action name.
            values: Payload containing a browser audio data URL and config values.
            payload: Optional framework request context.

        Returns:
            A node config patch storing the latest saved audio path and metadata.
        """

        if action == "save_browser_audio":
            return self._handle_browser_audio_action(node=node, values=values)
        if action in {"inspector_update_fields", "modal_update_fields"}:
            return super().handle_ui_action(node=node, action=action, values=values, payload=payload)
        return {"error": f"unsupported_action:{action}"}

    def preview_received(self, *, node: Any, **runtime_services: Any) -> str:
        """Return the latest saved audio path for runtime previews."""

        config = self._runtime_config(getattr(node, "config", {}) or {})
        return config["latest_audio_path"] or "Aucun audio navigateur"

    def _handle_browser_audio_action(self, *, node: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        """Persist a browser-submitted audio blob and return a node config patch."""

        raw_config = dict(node.get("config") if isinstance(node.get("config"), dict) else {})
        pending_config = values.get("config") if isinstance(values, dict) else {}
        if isinstance(pending_config, dict):
            raw_config.update(pending_config)
        config = self._runtime_config(raw_config)
        try:
            mime_type, audio_bytes = self._decode_browser_data_url(values.get("data_url"))
            duration_ms = self._normalize_duration_ms(values.get("duration_ms"))
            output_path, output_mime_type = self._write_audio_capture(
                root_dir=self._ui_root_dir(),
                node_id=str(node.get("id") or "audio"),
                config=config,
                mime_type=mime_type,
                audio_bytes=audio_bytes,
            )
        except ValueError as exc:
            return {"error": str(exc)}

        relative_path = self._relative_path(self._ui_root_dir(), output_path)
        captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        config_patch = {
            "output_dir": config["output_dir"],
            "target_format": config["target_format"],
            "filename_template": config["filename_template"],
            "max_duration_sec": config["max_duration_sec"],
            "latest_audio_path": relative_path,
            "latest_audio_mime": output_mime_type,
            "latest_audio_duration_ms": duration_ms,
            "latest_audio_size_bytes": output_path.stat().st_size,
            "latest_audio_at": captured_at,
            "capture_source": "browser",
        }
        return {
            "node_patch": {"config": config_patch},
            "allow_while_running": True,
            "active_runtime_actions": [
                {
                    "action": "publish_output",
                    "node_id": str(node.get("id") or ""),
                    "port_id": 1,
                    "port_name": "audio_path",
                    "value": relative_path,
                    "content_type": FILE_PATH,
                }
            ],
            "rerender_inspector": False,
            "saved_path": relative_path,
            "metadata": self._audio_metadata(
                config={**config, **config_patch},
                output_path=output_path,
                root_dir=self._ui_root_dir(),
            ),
            "message": f"[audio-record] Audio navigateur enregistre: {relative_path}",
        }

    def _write_audio_capture(
        self,
        *,
        root_dir: Path,
        node_id: str,
        config: dict[str, Any],
        mime_type: str,
        audio_bytes: bytes,
    ) -> tuple[Path, str]:
        """Save audio bytes and transcode when a non-native target is requested."""

        output_dir = self._resolve_output_dir(root_dir, config["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        target_format = config["target_format"]
        source_extension = SUPPORTED_BROWSER_AUDIO_EXTENSIONS.get(mime_type, ".webm")
        if target_format == "native":
            output_path = self._capture_output_path(
                output_dir=output_dir,
                node_id=node_id,
                config=config,
                extension=source_extension,
            )
            output_path.write_bytes(audio_bytes)
            return output_path, mime_type

        target_extension = f".{target_format}"
        output_path = self._capture_output_path(
            output_dir=output_dir,
            node_id=node_id,
            config=config,
            extension=target_extension,
        )
        source_path = output_path.with_suffix(f".source{source_extension}")
        source_path.write_bytes(audio_bytes)
        try:
            self._transcode_audio(source_path=source_path, output_path=output_path, target_format=target_format)
        finally:
            source_path.unlink(missing_ok=True)
        return output_path, TARGET_FORMAT_MIME_TYPES.get(target_format, mime_type)

    def _transcode_audio(self, *, source_path: Path, output_path: Path, target_format: str) -> None:
        """Transcode a browser audio file through FFmpeg when available."""

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise ValueError("ffmpeg_introuvable_pour_conversion_audio")
        command = [ffmpeg, "-y", "-i", str(source_path)]
        if target_format == "mp3":
            command.extend(["-codec:a", "libmp3lame"])
        if target_format == "m4a":
            command.extend(["-codec:a", "aac"])
        command.append(str(output_path))
        completed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        if completed.returncode != 0 or not output_path.is_file() or output_path.stat().st_size <= 0:
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            message = detail[-1] if detail else "conversion_audio_echouee"
            raise ValueError(f"conversion_audio_echouee:{message}")

    def _decode_browser_data_url(self, data_url: Any) -> tuple[str, bytes]:
        """Decode and validate a browser MediaRecorder data URL."""

        text = str(data_url or "").strip()
        if "," not in text:
            raise ValueError("audio_browser_data_url_invalide")
        header, encoded = text.split(",", 1)
        match = re.fullmatch(
            r"data:(audio/[a-z0-9.+-]+)(?:;codecs=[^;]+)?;base64",
            header.strip(),
            flags=re.IGNORECASE,
        )
        if not match:
            raise ValueError("format_audio_navigateur_non_supporte")
        mime_type = match.group(1).lower()
        if mime_type not in SUPPORTED_BROWSER_AUDIO_EXTENSIONS:
            raise ValueError("format_audio_navigateur_non_supporte")
        try:
            audio_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("audio_browser_base64_invalide") from exc
        if not audio_bytes:
            raise ValueError("audio_browser_vide")
        if len(audio_bytes) > MAX_BROWSER_AUDIO_BYTES:
            raise ValueError("audio_browser_trop_volumineux")
        return mime_type, audio_bytes

    def _capture_output_path(self, *, output_dir: Path, node_id: str, config: dict[str, Any], extension: str) -> Path:
        """Build a unique capture output path under the configured output directory."""

        timestamp = time.strftime("%Y%m%d-%H%M%S")
        millis = int(time.time() * 1000) % 1000
        safe_node_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", node_id or "audio")
        raw_template = config["filename_template"] or DEFAULT_AUDIO_FILENAME_TEMPLATE
        try:
            filename = raw_template.format(node_id=safe_node_id, timestamp=timestamp, format=extension.lstrip("."))
        except (KeyError, IndexError, ValueError):
            filename = DEFAULT_AUDIO_FILENAME_TEMPLATE.format(
                node_id=safe_node_id,
                timestamp=timestamp,
                format=extension.lstrip("."),
            )
        safe_filename = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename).strip("._") or f"{safe_node_id}_{timestamp}"
        return output_dir / f"{safe_filename}-{millis:03d}{extension}"

    def _ui_config(self, node: dict[str, Any]) -> dict[str, Any]:
        """Return normalized UI config from a serialized node."""

        return self._runtime_config(node.get("config") if isinstance(node.get("config"), dict) else {})

    def _runtime_config(self, raw_config: dict[str, Any]) -> dict[str, Any]:
        """Normalize runtime and UI config without touching the filesystem."""

        config = raw_config if isinstance(raw_config, dict) else {}
        return {
            "output_dir": self._normalize_output_dir(config.get("output_dir")),
            "target_format": self._normalize_target_format(config.get("target_format")),
            "filename_template": self._normalize_filename_template(config.get("filename_template")),
            "max_duration_sec": self._normalize_max_duration_sec(config.get("max_duration_sec")),
            "latest_audio_path": self._normalize_latest_audio_path(config.get("latest_audio_path")),
            "latest_audio_mime": self._normalize_mime_type(config.get("latest_audio_mime")),
            "latest_audio_duration_ms": self._normalize_duration_ms(config.get("latest_audio_duration_ms")),
            "latest_audio_size_bytes": self._normalize_size_bytes(config.get("latest_audio_size_bytes")),
            "latest_audio_at": str(config.get("latest_audio_at") or "").strip(),
            "capture_source": "browser",
        }

    def _template_replacements(self, config: dict[str, Any]) -> dict[str, str]:
        """Build escaped HTML replacements for Audio Record templates."""

        return {
            "output_dir": escape(config["output_dir"], quote=True),
            "target_format_native_selected": "selected" if config["target_format"] == "native" else "",
            "target_format_webm_selected": "selected" if config["target_format"] == "webm" else "",
            "target_format_mp3_selected": "selected" if config["target_format"] == "mp3" else "",
            "target_format_m4a_selected": "selected" if config["target_format"] == "m4a" else "",
            "filename_template": escape(config["filename_template"], quote=True),
            "max_duration_sec": str(config["max_duration_sec"]),
            "latest_audio_path": escape(config["latest_audio_path"] or "Aucun audio enregistre.", quote=True),
            "latest_audio_value": escape(config["latest_audio_path"], quote=True),
            "latest_audio_hidden": "hidden" if not config["latest_audio_path"] else "",
            "latest_audio_at": escape(config["latest_audio_at"] or "-", quote=True),
            "latest_audio_duration": escape(self._duration_label(config["latest_audio_duration_ms"]), quote=True),
            "latest_audio_size": escape(self._size_label(config["latest_audio_size_bytes"]), quote=True),
        }

    def _audio_metadata(self, *, config: dict[str, Any], output_path: Path, root_dir: Path) -> dict[str, Any]:
        """Return JSON metadata for the latest saved audio file."""

        relative = self._relative_path(root_dir, output_path)
        size = output_path.stat().st_size if output_path.is_file() else config["latest_audio_size_bytes"]
        return {
            "path": relative,
            "mime_type": config["latest_audio_mime"],
            "duration_ms": config["latest_audio_duration_ms"],
            "size_bytes": size,
            "captured_at": config["latest_audio_at"],
            "capture_source": config["capture_source"],
            "target_format": config["target_format"],
        }

    def _resolve_output_dir(self, root_dir: Path, output_dir: str) -> Path:
        """Return a safe output directory inside the application root."""

        output_path = (root_dir / output_dir).resolve()
        try:
            output_path.relative_to(root_dir.resolve())
        except ValueError:
            output_path = (root_dir / DEFAULT_AUDIO_OUTPUT_DIR).resolve()
        return output_path

    def _resolve_existing_audio_path(self, root_dir: Path, latest_audio_path: str) -> Path | None:
        """Resolve a persisted audio path and ensure it points to a readable file."""

        text = str(latest_audio_path or "").strip()
        if not text:
            return None
        candidate = Path(text)
        output_path = candidate.resolve() if candidate.is_absolute() else (root_dir / candidate).resolve()
        try:
            output_path.relative_to(root_dir.resolve())
        except ValueError:
            return None
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            return None
        return output_path

    def _relative_path(self, root_dir: Path, output_path: Path) -> str:
        """Return a POSIX relative output path when possible."""

        try:
            return output_path.resolve().relative_to(root_dir.resolve()).as_posix()
        except ValueError:
            return output_path.as_posix()

    def _ui_root_dir(self) -> Path:
        """Return the application root used by block UI actions."""

        return self.directory.parent.parent

    def _failed(self, error: str, logs: list[str], *, exit_code: int = 1) -> BlockRuntimeResult:
        """Return a standardized failed runtime result."""

        return BlockRuntimeResult(
            status="failed",
            outputs=[],
            logs=logs,
            error=error,
            exit_code=exit_code,
            last_message=error,
            content_type=FILE_PATH,
            worker_received="-",
        )

    def _normalize_output_dir(self, value: Any) -> str:
        text = str(value or "").strip().replace("\\", "/")
        if not text or text.startswith("/") or ".." in Path(text).parts:
            return DEFAULT_AUDIO_OUTPUT_DIR
        return text

    def _normalize_target_format(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        return text if text in SUPPORTED_TARGET_FORMATS else DEFAULT_AUDIO_TARGET_FORMAT

    def _normalize_filename_template(self, value: Any) -> str:
        text = str(value or "").strip().replace("\\", "/")
        if not text or "/" in text or ".." in Path(text).parts:
            return DEFAULT_AUDIO_FILENAME_TEMPLATE
        return text[:80]

    def _normalize_max_duration_sec(self, value: Any) -> int:
        try:
            duration = int(value)
        except (TypeError, ValueError):
            duration = DEFAULT_MAX_DURATION_SEC
        return min(3600, max(1, duration))

    def _normalize_duration_ms(self, value: Any) -> int:
        try:
            duration = int(float(value))
        except (TypeError, ValueError):
            duration = 0
        return max(0, duration)

    def _normalize_size_bytes(self, value: Any) -> int:
        try:
            size = int(value)
        except (TypeError, ValueError):
            size = 0
        return max(0, size)

    def _normalize_latest_audio_path(self, value: Any) -> str:
        text = str(value or "").strip().replace("\\", "/")
        if not text or ".." in Path(text).parts:
            return ""
        return text

    def _normalize_mime_type(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        return text if text in SUPPORTED_BROWSER_AUDIO_EXTENSIONS or text in TARGET_FORMAT_MIME_TYPES.values() else ""

    def _duration_label(self, duration_ms: int) -> str:
        """Return a compact human-readable duration label."""

        if duration_ms <= 0:
            return "-"
        seconds = max(1, round(duration_ms / 1000))
        minutes, remainder = divmod(seconds, 60)
        return f"{minutes}m {remainder:02d}s" if minutes else f"{remainder}s"

    def _size_label(self, size_bytes: int) -> str:
        """Return a compact human-readable byte-size label."""

        if size_bytes <= 0:
            return "-"
        if size_bytes < 1024 * 1024:
            return f"{round(size_bytes / 1024, 1)} KB"
        return f"{round(size_bytes / (1024 * 1024), 1)} MB"

    def _short_path(self, value: str, *, max_chars: int = 42) -> str:
        """Return a readable truncated path for compact UI surfaces."""

        text = str(value or "").strip()
        if len(text) <= max_chars:
            return text
        return f"...{text[-max_chars:]}"
