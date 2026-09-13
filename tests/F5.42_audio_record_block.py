#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Role: Verifies browser-backed audio record block behavior without requiring hardware.
# File Name: F5.42_audio_record_block.py
# Author: Alexandre EL
# Email: alex@hackinvent.com
# Created Date: 2026-06-20
# -----------------------------------------------------------------------------

# Test cases:
# - FB1 - Render the modal browser microphone controls with declared MediaRecorder JS assets.
# - FB2 - Save a browser-submitted audio data URL under the configured output directory.
# - FB3 - Return a clear failed runtime result when no browser audio has been captured.
# - FB4 - Emit the saved audio path and metadata directly and in centralized/zeromq_active runs.
# - FB5 - Render editable capture settings in the block-owned modal and inspector panel.
# - FB6 - Allow browser capture graph patches while an active runtime is prepared.
# - FB7 - Publish the captured audio path to downstream workers in an active runtime.
# - FB8 - Render a node-card press-and-hold recording control with block-owned JS.

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen
import sys
import tempfile


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
TESTS_DIR = ROOT_DIR / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from blocs import get_block_definition
from bloxsmith_app.block_runtime import BlockRuntimeContext
from bloxsmith_app.port_types import APPLICATION_JSON, FILE_PATH
from ui_smoke_common import create_project_api, create_run_api, expect, http_json, isolated_server, wait_for_run_predicate, wait_for_run_terminal


AUDIO_BYTES = b"browser audio webm bytes"


def data_url() -> str:
    """Return a small browser-like WebM audio data URL for capture tests."""

    return "data:audio/webm;base64," + base64.b64encode(AUDIO_BYTES).decode("ascii")


def context(root_dir: Path, latest_audio_path: str) -> BlockRuntimeContext:
    """Build a direct runtime context for the Audio Record block."""

    return BlockRuntimeContext(
        run_id="run-audio-test",
        node_id="audio-record-1",
        kind="audio_record",
        title="Audio",
        config={
            "output_dir": "exports/audio-test",
            "target_format": "native",
            "latest_audio_path": latest_audio_path,
            "latest_audio_mime": "audio/webm",
            "latest_audio_duration_ms": 1200,
            "latest_audio_size_bytes": len(AUDIO_BYTES),
            "latest_audio_at": "2026-06-20T00:00:00Z",
        },
        inputs={},
        input_content_types={},
        input_message="",
        input_ports=(),
        output_ports=(
            SimpleNamespace(id=1, name="audio_path"),
            SimpleNamespace(id=2, name="metadata"),
        ),
        root_dir=root_dir,
    )


def audio_display_document(config: dict) -> dict:
    """Return a minimal graph that routes Audio Record to Display."""

    return {
        "kind": "bloxsmith.graph",
        "schema_version": "2",
        "graph_id": "",
        "title": "Audio Record Test",
        "editor": {"viewport": {"x": 0, "y": 0, "zoom": 0.75}},
        "nodes": [
            {
                "id": "audio-record-1",
                "kind": "audio_record",
                "title": "Audio navigateur",
                "position": {"x": 80, "y": 120},
                "inputs": [],
                "outputs": [
                    {
                        "id": 1,
                        "name": "audio_path",
                        "title": "Audio",
                        "emits": ["file/path", "audio/*", "message/*"],
                        "multiplicity": "many",
                    },
                    {
                        "id": 2,
                        "name": "metadata",
                        "title": "Metadata",
                        "emits": ["application/json", "message/*"],
                        "multiplicity": "many",
                    },
                ],
                "config": dict(config),
            },
            {
                "id": "display-1",
                "kind": "display",
                "title": "Affichage",
                "position": {"x": 360, "y": 120},
                "inputs": [
                    {
                        "id": 1,
                        "name": "in",
                        "title": "In",
                        "accepts": ["file/path", "audio/*", "message/*"],
                        "multiplicity": "many",
                    }
                ],
                "outputs": [],
                "config": {},
            },
        ],
        "edges": [
            {
                "id": "edge-audio-display",
                "from": {"node": "audio-record-1", "port": 1},
                "to": {"node": "display-1", "port": 1},
                "kind": "data",
            }
        ],
        "inputs": [],
        "outputs": [],
    }


def main() -> None:
    block = get_block_definition("audio_record")
    with tempfile.TemporaryDirectory() as tmp_dir:
        root_dir = Path(tmp_dir)
        capture_path = root_dir / "exports/audio-test/audio-record-1_browser_test.webm"
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        capture_path.write_bytes(AUDIO_BYTES)
        result = block.execute_runtime(context(root_dir, "exports/audio-test/audio-record-1_browser_test.webm"))
        expect(result.status == "success", "Saved browser audio must be emitted.")
        expect(result.outputs and result.outputs[0].content_type == FILE_PATH, "The first output must be file/path.")
        emitted_path = Path(result.outputs[0].value)
        expect((root_dir / emitted_path).is_file() or emitted_path.is_file(), "The emitted path must point to the saved audio file.")
        expect(result.outputs[1].content_type == APPLICATION_JSON, "Metadata output must be application/json.")

        failed = block.execute_runtime(context(root_dir, ""))
        expect(failed.status == "failed", "Without browser audio, the block must fail cleanly.")
        expect("Aucun audio navigateur" in failed.error, "The error must ask for a browser audio capture.")

    node = block.build_node_payload(node_id="audio-record-ui")
    card = block.render_node_card(node=node)
    expect("Audio" in card["html"], "The node card must render the Audio block.")
    expect("Aucun audio" in card["html"], "The node card must show no latest audio by default.")
    expect("data-audio-record-card-hold" in card["html"], "The node card must expose a press-and-hold record button.")
    mini_card = block.render_mini_node_card(node=node)
    expect("audio-record-mini-card" in mini_card["html"], "The mini-card must be rendered by the block.")
    inspector = block.render_inspector_panel(node=node)
    expect('data-block-config-field="output_dir"' in inspector["html"], "Inspector must expose output_dir.")
    expect('data-block-config-field="target_format"' in inspector["html"], "Inspector must expose target_format.")
    modal = block.render_modal(node=node)
    expect("data-audio-record-hold" in modal["html"], "Modal must expose click-to-talk control.")
    expect('data-block-runtime-refresh="autonomous"' in modal["html"], "Modal must opt out of centralized runtime rerendering.")
    expect('data-block-config-field="max_duration_sec"' in modal["html"], "Modal must expose max duration.")

    with isolated_server() as server:
        node = block.build_node_payload(
            node_id="audio-record-1",
            config_overrides={"output_dir": "exports/audio-api", "target_format": "native"},
        )
        rendered = http_json(server.base_url, "/api/blocks/audio_record/modal", method="POST", payload={"node": node})
        assets = rendered.get("assets") or []
        expect(
            {"kind": "js", "path": "assets/js/recorder.js"} in assets,
            "Audio modal must declare its shared browser recording JS helper.",
        )
        expect(
            {"kind": "js", "path": "assets/js/block_modal.js"} in assets,
            "Audio modal must declare its browser recording JS asset.",
        )
        with urlopen(f"{server.base_url}/api/blocks/audio_record/assets/assets/js/recorder.js", timeout=5) as response:
            recorder_body = response.read().decode("utf-8")
        expect("MediaRecorder" in recorder_body, "Recorder helper must use MediaRecorder.")
        expect("getUserMedia" in recorder_body, "Recorder helper must request the browser microphone.")
        expect('applyAction("save_browser_audio"' in recorder_body, "Recorder helper must call the block UI action.")
        with urlopen(f"{server.base_url}/api/blocks/audio_record/assets/assets/js/block_modal.js", timeout=5) as response:
            block_modal_js = response.read().decode("utf-8")
        expect("Aucun run actif" in block_modal_js, "Modal JS must warn when no active runtime receives the recording.")
        node_card_rendered = http_json(server.base_url, "/api/blocks/audio_record/node-card", method="POST", payload={"node": node})
        node_card_assets = node_card_rendered.get("assets") or []
        expect(
            {"kind": "js", "path": "assets/js/node_card.js"} in node_card_assets,
            "Audio node card must declare its press-and-hold JS asset.",
        )
        with urlopen(f"{server.base_url}/api/blocks/audio_record/assets/assets/js/node_card.js", timeout=5) as response:
            node_card_js = response.read().decode("utf-8")
        expect("data-audio-record-card-hold" in node_card_js, "Node-card JS must bind the card hold button.")
        expect("audio_recordNodeCard" in node_card_js, "Node-card JS must register with the framework node-card registry suffix.")
        expect("Run absent" in node_card_js, "Node-card JS must warn when no active runtime receives the recording.")

        applied = http_json(
            server.base_url,
            "/api/blocks/audio_record/ui-action",
            method="POST",
            payload={
                "node": node,
                "action": "save_browser_audio",
                "values": {
                    "data_url": data_url(),
                    "duration_ms": 1500,
                    "config": {"output_dir": "exports/audio-api", "target_format": "native"},
                },
            },
        )
        saved_path = str(applied.get("saved_path") or "")
        expect(saved_path.startswith("exports/audio-api/"), "Audio capture must respect output_dir.")
        expect((server.root_dir / saved_path).read_bytes() == AUDIO_BYTES, "Audio capture must be written server-side.")
        expect(applied.get("metadata", {}).get("duration_ms") == 1500, "Audio metadata must preserve duration.")

        document_for_patch = audio_display_document(node.get("config") or {})
        created_project = create_project_api(server, title="Audio Record Graph Patch", document=document_for_patch)
        project_id = str(created_project["project"]["project_id"])
        graph_state = http_json(server.base_url, f"/api/projects/{project_id}/graph/state")
        graph_node = next(item for item in graph_state["document"]["nodes"] if item["id"] == "audio-record-1")
        patched = http_json(
            server.base_url,
            "/api/blocks/audio_record/ui-action",
            method="POST",
            payload={
                "project_id": project_id,
                "base_version": graph_state["version"],
                "apply_graph_patch": True,
                "op_id_prefix": "audio-node-card",
                "node": graph_node,
                "action": "save_browser_audio",
                "values": {
                    "data_url": data_url(),
                    "duration_ms": 1600,
                    "config": {"output_dir": "exports/audio-api", "target_format": "native"},
                },
            },
        )
        expect(patched.get("graph_patch", {}).get("ok") is True, f"Audio capture must patch the graph: {patched}")
        updated_graph = http_json(server.base_url, f"/api/projects/{project_id}/graph/state")
        updated_audio = next(item for item in updated_graph["document"]["nodes"] if item["id"] == "audio-record-1")
        patched_path = str(updated_audio.get("config", {}).get("latest_audio_path") or "")
        expect(patched_path.startswith("exports/audio-api/"), "latest_audio_path must be persisted in the graph.")

        active_started = http_json(
            server.base_url,
            f"/api/projects/{project_id}/runs/prepare",
            method="POST",
            payload={"runtime_mode": "zeromq_active"},
        )
        active_run_id = str(active_started.get("run_id") or "")
        expect(active_run_id, f"Active runtime must prepare before capture patch: {active_started}")
        active_graph_state = http_json(server.base_url, f"/api/projects/{project_id}/graph/state")
        active_graph_node = next(item for item in active_graph_state["document"]["nodes"] if item["id"] == "audio-record-1")
        active_patched = http_json(
            server.base_url,
            "/api/blocks/audio_record/ui-action",
            method="POST",
            payload={
                "project_id": project_id,
                "base_version": active_graph_state["version"],
                "apply_graph_patch": True,
                "op_id_prefix": "audio-node-card-active",
                "node": active_graph_node,
                "action": "save_browser_audio",
                "values": {
                    "data_url": data_url(),
                    "duration_ms": 1700,
                    "config": {"output_dir": "exports/audio-api", "target_format": "native"},
                },
            },
        )
        expect(active_patched.get("graph_patch", {}).get("ok") is True, f"Audio capture must patch while active runtime is prepared: {active_patched}")
        active_publish = active_patched.get("active_runtime_actions_result") or {}
        expect(active_publish.get("ok") is True, f"Audio capture must publish the path into the active runtime: {active_patched}")
        active_updated_graph = http_json(server.base_url, f"/api/projects/{project_id}/graph/state")
        active_audio = next(item for item in active_updated_graph["document"]["nodes"] if item["id"] == "audio-record-1")
        active_path = str(active_audio.get("config", {}).get("latest_audio_path") or "")
        expect(active_path.startswith("exports/audio-api/"), "latest_audio_path must be hot-patched while active runtime is prepared.")
        wait_for_run_predicate(
            server,
            active_run_id,
            lambda state: active_path in str(state.get("results", {}).get("display-1", {}).get("last_message") or ""),
            "Browser capture must send the saved audio path to downstream active workers.",
            timeout_sec=8,
        )
        _ = http_json(server.base_url, f"/api/runs/{active_run_id}/stop", method="POST", payload={})

        config = dict(node.get("config") or {})
        config.update(applied.get("node_patch", {}).get("config") or {})
        document = audio_display_document(config)
        for runtime_mode in ("centralized", "zeromq_active"):
            created = create_run_api(server, document, runtime_mode=runtime_mode)
            run = wait_for_run_terminal(server, str(created.get("run_id") or ""), timeout_sec=15)
            expect(run.get("status") == "success", f"Audio run must succeed in {runtime_mode}.")
            audio_result = run.get("results", {}).get("audio-record-1", {})
            expect(audio_result.get("content_type") == FILE_PATH, f"Audio must emit file/path in {runtime_mode}.")
            expect(saved_path in str(audio_result.get("last_message") or ""), f"Audio must emit the saved capture in {runtime_mode}.")
            display_result = run.get("results", {}).get("display-1", {})
            expect(saved_path in str(display_result.get("last_message") or ""), f"Display must receive the audio path in {runtime_mode}.")

    print("[ok] F5.42_audio_record_block")


if __name__ == "__main__":
    main()
