/**
 * Resolve one block text in the active language, from the catalog of the owning release.
 *
 * @param {HTMLElement} element - Element inside the mounted surface, carrying its release.
 * @param {string} key - Block catalog key.
 * @param {object} params - Placeholder values.
 * @param {string} fallback - Authored English text.
 * @returns {string} Localized text.
 */
function text(element, key, params, fallback) {
  const release = element?.closest?.("[data-block-release]")?.dataset?.blockRelease || "";
  return window.CWI18n?.t?.(key, params, fallback, release) ?? fallback;
}

/**
 * Role: Provides reusable browser microphone recording helpers for Audio Record surfaces.
 * File Name: recorder.js
 * Author: Alexandre EL
 * Email: alex@hackinvent.com
 * Created Date: 2026-06-20
 */

/**
 * Return the best MediaRecorder MIME type supported by the browser.
 *
 * @returns {string} MIME type string or empty string for browser default.
 */
function preferredMimeType() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
    "audio/ogg",
  ];
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return "";
  }
  return candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate)) || "";
}

/**
 * Convert a Blob to a base64 data URL accepted by block.py.
 *
 * @param {Blob} blob - Recorded browser audio blob.
 * @returns {Promise<string>} Blob encoded as data URL.
 */
function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error(text(document.body, "block.audio_record.read_failed", {}, "Reading the audio failed.")));
    reader.readAsDataURL(blob);
  });
}

/**
 * Stop every track from a browser media stream.
 *
 * @param {MediaStream | null | undefined} stream - Stream to stop.
 */
function stopStream(stream) {
  if (!stream) {
    return;
  }
  for (const track of stream.getTracks()) {
    track.stop();
  }
}

/**
 * Create a reusable click-to-talk recorder bound to one block UI surface.
 *
 * @param {object} options - Recorder callbacks and configuration.
 * @param {Function} options.applyAction - Function calling the block UI action.
 * @param {Function} [options.config] - Returns config values to submit with the blob.
 * @param {Function} [options.onStatus] - Receives user-facing status messages.
 * @param {Function} [options.onStart] - Called once the recorder starts.
 * @param {Function} [options.onStop] - Called after local recording stops.
 * @param {Function} [options.onSaved] - Called with the block UI action result.
 * @param {Function} [options.onError] - Called with the caught error and message.
 * @param {number} [options.maxDurationSec] - Automatic stop delay in seconds.
 * @returns {object} Recorder controller with start/stop/dispose methods.
 */
export function createRecorder(options = {}) {
  const state = {
    chunks: [],
    disposed: false,
    maxDurationTimer: 0,
    mimeType: "",
    recorder: null,
    startedAt: 0,
    starting: false,
    stream: null,
  };

  const status = (message) => options.onStatus?.(message);
  const maxDurationSec = () => Math.max(1, Number(options.maxDurationSec?.() || options.maxDurationSec || 120));

  async function save(blob) {
    if (!blob || blob.size <= 0) {
      status(text(document.body, "block.audio_record.no_audio_captured", {}, "No audio captured."));
      return null;
    }
    status(text(document.body, "block.audio_record.saving_audio", {}, "Saving the audio..."));
    const durationMs = state.startedAt ? Date.now() - state.startedAt : 0;
    const dataUrl = await blobToDataUrl(blob);
    if (typeof options.applyAction !== "function") {
      throw new Error("Action d'enregistrement indisponible.");
    }
    const result = await options.applyAction("save_browser_audio", {
      data_url: dataUrl,
      mime_type: blob.type || state.mimeType || "",
      duration_ms: durationMs,
      config: typeof options.config === "function" ? options.config() : {},
    });
    options.onSaved?.(result || {});
    return result || {};
  }

  function cleanup() {
    window.clearTimeout(state.maxDurationTimer);
    stopStream(state.stream);
    state.stream = null;
    state.starting = false;
    options.onStop?.();
  }

  async function start() {
    if (state.disposed || state.starting || (state.recorder && state.recorder.state !== "inactive")) {
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      status(text(document.body, "block.audio_record.browser_recording_unavailable", {}, "Browser audio recording is unavailable."));
      return;
    }
    state.chunks = [];
    state.startedAt = Date.now();
    state.starting = true;
    state.mimeType = preferredMimeType();
    status(text(document.body, "block.audio_record.opening_microphone", {}, "Opening the microphone..."));
    try {
      state.stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      const recorder = new MediaRecorder(state.stream, state.mimeType ? { mimeType: state.mimeType } : {});
      state.recorder = recorder;
      recorder.addEventListener("dataavailable", (event) => {
        if (event.data && event.data.size > 0) {
          state.chunks.push(event.data);
        }
      });
      recorder.addEventListener("stop", () => {
        const blob = new Blob(state.chunks, { type: recorder.mimeType || state.mimeType || "audio/webm" });
        cleanup();
        void save(blob).catch((error) => {
          const message = error instanceof Error ? error.message : String(error || "unknown error");
          status(text(document.body, "block.audio_record.record_failed", { error: message }, `Recording failed: ${message}`));
          options.onError?.(error, message);
        });
      });
      recorder.start();
      state.starting = false;
      options.onStart?.();
      status(text(document.body, "block.audio_record.speak_now", {}, "Speak now. Release to finish."));
      state.maxDurationTimer = window.setTimeout(() => stop(), maxDurationSec() * 1000);
    } catch (error) {
      cleanup();
      const message = error instanceof Error ? error.message : String(error || "unknown error");
      status(text(document.body, "block.audio_record.microphone_unreachable", { error: message }, `Microphone unreachable: ${message}`));
      options.onError?.(error, message);
    }
  }

  function stop() {
    if (state.recorder && state.recorder.state !== "inactive") {
      state.recorder.stop();
    } else if (state.starting) {
      cleanup();
    }
  }

  function dispose() {
    state.disposed = true;
    stop();
    cleanup();
  }

  return { start, stop, dispose };
}

createRecorder = createRecorder;
