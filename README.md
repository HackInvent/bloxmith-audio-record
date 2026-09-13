# Audio Record

<!-- block-metadata:start -->
[![Block version: 0.1.0](https://img.shields.io/badge/block-0.1.0-blue)](model.json)
[![BloxSmith compatibility: 1.0.9](https://img.shields.io/badge/BloxSmith-1.0.9-brightgreen)](compatibility.json)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

Verified BloxSmith versions: **1.0.9** (bundled-block tests; see [test evidence](compatibility.json)).
<!-- block-metadata:end -->


`audio_record` records microphone audio from the operator browser and stores the latest capture as a project-local file. It is a source block: during a run it publishes the path of the last saved audio file plus JSON metadata.

## Functional behavior

- FB1: records audio through the browser `navigator.mediaDevices.getUserMedia` and `MediaRecorder` APIs.
- FB2: uploads the finished browser blob to `block.py` through the block-owned `save_browser_audio` UI action.
- FB3: saves the audio under `output_dir`, default `exports/audio`.
- FB4: optionally converts the browser capture to `webm`, `mp3`, or `m4a` through `ffmpeg` when a non-native target format is selected.
- FB5: emits the latest saved audio path and metadata in both One Shot Simulation (`centralized`) and Active Runtime (`zeromq_active`).
- FB6: allows the browser capture UI action to persist latest-capture metadata while an Active Runtime is prepared, because it only updates runtime-mutable node config.
- FB7: publishes the captured `audio_path` output immediately into the loaded Active Runtime so downstream blocks receive the new path without pressing global Play.
- FB8: provides a press-and-hold record button directly on the node card; release stops recording, saves the file, and publishes the path when Active Runtime is loaded.

## Ports

Outputs:

- `audio_path` (`file/path`, `audio/*`, `message/*`): path to the latest saved audio file.
- `metadata` (`application/json`, `message/*`): compact JSON metadata for the latest capture.

The block has no input. It is triggered as a source block during play/run.

## Configuration

- `output_dir`: relative directory where browser recordings are saved. Default: `exports/audio`.
- `target_format`: `native`, `webm`, `mp3`, or `m4a`. Default: `native`. `mp3`, `m4a`, and forced `webm` conversion require `ffmpeg`.
- `filename_template`: filename stem. Supported placeholders: `{node_id}`, `{timestamp}`, `{format}`. Default: `audio_{node_id}_{timestamp}`.
- `max_duration_sec`: maximum recording duration before automatic stop. Default: `120`.
- `latest_audio_path`, `latest_audio_mime`, `latest_audio_duration_ms`, `latest_audio_size_bytes`, `latest_audio_at`: runtime capture metadata persisted in node config by the UI action.

## UI

The modal and node card own click-to-talk recording controls. Press and hold **Hold to talk** (`Maintenir pour parler` in the current UI) in the modal or **Hold** (`Maintenir` in the current UI) on the node card, release to stop, then the block uploads and stores the capture. If no Active Runtime is loaded, the UI warns that the audio was saved but the output was not sent to the graph. The modal opts into autonomous runtime refresh so polling does not remount the capture UI while the user is recording. Capture persistence can run while Active Runtime is prepared because the block marks this UI action as `allow_while_running` and only patches runtime-mutable node config. When an Active Runtime is loaded, the same action also publishes the saved path on the `audio_path` output. The inspector exposes the same persistence parameters but does not access the microphone.

## Runtime output example

`audio_path`:

```text
exports/audio/audio_audio-record-1_20260620-103000-123.webm
```

`metadata`:

```json
{
  "path": "exports/audio/audio_audio-record-1_20260620-103000-123.webm",
  "mime_type": "audio/webm",
  "duration_ms": 2450,
  "size_bytes": 38122,
  "captured_at": "2026-06-20T08:30:00Z",
  "capture_source": "browser",
  "target_format": "native"
}
```

## Errors

- If no capture exists, runtime returns `failed` with a clear message asking the user to record audio through the modal.
- If browser audio is empty, malformed, too large, or unsupported, the UI action returns an error without modifying node config.
- If a conversion format is requested but `ffmpeg` is missing or fails, the UI action returns a conversion error.

## Tests

- `tests/F5.42_audio_record_block.py` verifies UI rendering, browser data URL persistence, graph patch persistence, capture patching while an active runtime is prepared, node-card press-and-hold recording UI, active publication to downstream workers, direct runtime execution, and `audio_record -> display` in `centralized` and `zeromq_active`.

## Compatibility policy

[compatibility.json](compatibility.json) records HackInvent's verified BloxSmith versions and test evidence. Only the versions listed above have been verified, using the block-owned suites in a **bundled-block test installation**. This is not a certification of managed-package installation, every browser/OS, or live provider availability. Other framework versions are unverified, not necessarily incompatible.

The block-version badge follows `model.json`, not a published Git tag. `unversioned` means that no block release version is declared; no number is inferred from the framework version. The framework still uses `model.json` for its runtime/install contract; the tester-owned JSON does not replace it. Official integration tests run in the private `bloxmith-blocs` workspace. Test helpers and the proprietary framework are not bundled in this public block repository.
