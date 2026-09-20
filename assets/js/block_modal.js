/**
 * Role: Mounts browser microphone recording controls for the Audio Record modal.
 * File Name: block_modal.js
 * Author: Alexandre EL
 * Email: alex@hackinvent.com
 * Created Date: 2026-06-20
 */
import { createRecorder } from "./recorder.js";

/**
 * Return a user-facing warning when capture was saved but not published.
 *
 * @param {object} result - Result returned by save_browser_audio.
 * @returns {string} Warning text, or empty string when publication succeeded.
 */
function runtimePublicationWarning(result) {
  const runtimeResult = result?.active_runtime_actions_result;
  if (!runtimeResult) {
    return "";
  }
  if (runtimeResult.skipped && runtimeResult.reason === "no_active_run") {
    return "Aucun run actif: audio enregistre, output non envoye.";
  }
  if (runtimeResult.skipped) {
    return "Audio enregistre, publication runtime ignoree.";
  }
  if (runtimeResult.ok !== true) {
    return "Audio enregistre, publication runtime non confirmee.";
  }
  return "";
}

/**
 * Read a block config field from the mounted modal.
 *
 * @param {HTMLElement} root - Audio Record modal root.
 * @param {string} name - Config field name.
 * @returns {string} Current field value.
 */
function configFieldValue(root, name) {
  const field = root.querySelector(`[data-block-config-field="${name}"]`);
  if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement || field instanceof HTMLTextAreaElement) {
    return field.value;
  }
  return "";
}

/**
 * Collect config values that affect audio capture persistence.
 *
 * @param {HTMLElement} root - Audio Record modal root.
 * @returns {object} Pending config patch.
 */
function captureConfig(root) {
  return {
    output_dir: configFieldValue(root, "output_dir"),
    target_format: configFieldValue(root, "target_format") || "native",
    filename_template: configFieldValue(root, "filename_template"),
    max_duration_sec: Number(configFieldValue(root, "max_duration_sec") || 120),
  };
}

/**
 * Set the modal capture status line.
 *
 * @param {HTMLElement} root - Audio Record modal root.
 * @param {string} message - Status message.
 */
function setStatus(root, message) {
  const status = root.querySelector("[data-audio-record-status]");
  if (status) {
    status.textContent = message;
  }
}

/**
 * Reset modal buttons to their idle state.
 *
 * @param {HTMLButtonElement} holdButton - Press-and-hold record button.
 * @param {HTMLButtonElement | null} stopButton - Optional explicit stop button.
 */
function resetButtons(holdButton, stopButton) {
  holdButton.disabled = false;
  holdButton.classList.remove("is-recording");
  holdButton.textContent = "Maintenir pour parler";
  if (stopButton instanceof HTMLButtonElement) {
    stopButton.disabled = true;
  }
}

/**
 * Bind the Audio Record modal microphone capture controls.
 *
 * @param {HTMLElement} root - Mounted modal root.
 * @param {object} api - Generic block UI API.
 */
export function mount(root, api) {
  const holdButton = root.querySelector("[data-audio-record-hold]");
  const stopButton = root.querySelector("[data-audio-record-stop]");
  if (!(holdButton instanceof HTMLButtonElement)) {
    return;
  }
  let pointerActive = false;
  const recorder = createRecorder({
    applyAction: (action, values) => api?.applyAction?.(action, values),
    config: () => captureConfig(root),
    maxDurationSec: () => Number(configFieldValue(root, "max_duration_sec") || 120),
    onStatus: (message) => setStatus(root, message),
    onStart: () => {
      holdButton.classList.add("is-recording");
      holdButton.textContent = "Enregistrement...";
      if (stopButton instanceof HTMLButtonElement) {
        stopButton.disabled = false;
      }
      if (!pointerActive) {
        recorder.stop();
      }
    },
    onStop: () => resetButtons(holdButton, stopButton),
    onSaved: (result) => {
      const savedPath = String(result.saved_path || result.node_patch?.config?.latest_audio_path || "");
      const warning = runtimePublicationWarning(result);
      const baseMessage = savedPath ? `Audio enregistre: ${savedPath}` : "Audio enregistre.";
      setStatus(root, warning ? `${baseMessage} ${warning}` : baseMessage);
      api?.log?.(savedPath ? `[audio-record] Audio enregistre: ${savedPath}` : "[audio-record] Audio enregistre.");
      if (warning) {
        api?.log?.(`[audio-record-warn] ${warning}`);
      }
    },
    onError: (_error, message) => api?.log?.(`[audio-record-error] ${message}`),
  });

  const begin = (event) => {
    event.preventDefault();
    pointerActive = true;
    holdButton.classList.add("is-recording");
    holdButton.textContent = "Autorisation micro...";
    if (stopButton instanceof HTMLButtonElement) {
      stopButton.disabled = false;
    }
    void recorder.start();
  };
  const end = (event) => {
    event.preventDefault();
    pointerActive = false;
    recorder.stop();
  };
  holdButton.addEventListener("pointerdown", begin);
  holdButton.addEventListener("pointerup", end);
  holdButton.addEventListener("pointercancel", end);
  holdButton.addEventListener("mouseleave", (event) => {
    if (pointerActive) {
      end(event);
    }
  });
  stopButton?.addEventListener("click", (event) => {
    event.preventDefault();
    pointerActive = false;
    recorder.stop();
  });
  root.addEventListener("click", (event) => {
    if (event.target.closest("[data-close-block-modal]")) {
      recorder.dispose();
    }
  });
  const observer = new MutationObserver(() => {
    if (!root.isConnected) {
      recorder.dispose();
      observer.disconnect();
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
}
