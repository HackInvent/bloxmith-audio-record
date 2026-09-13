/**
 * Role: Mounts click-to-talk controls directly on the Audio Record node card.
 * File Name: node_card.js
 * Author: Alexandre EL
 * Email: alex@hackinvent.com
 * Created Date: 2026-06-20
 */

(function () {
  "use strict";

  const registry = (window.CWBlockUiBlocks = window.CWBlockUiBlocks || {});

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
   * Stop canvas drag/selection events from stealing the press-and-hold gesture.
   *
   * @param {Event} event - Browser pointer/mouse event.
   */
  function isolateCardControl(event) {
    event.preventDefault();
    event.stopPropagation();
  }

  /**
   * Return static capture config from the rendered node card data attributes.
   *
   * @param {HTMLElement} root - Audio Record card root.
   * @returns {object} Config payload for save_browser_audio.
   */
  function captureConfig(root) {
    return {
      output_dir: root.dataset.audioOutputDir || "exports/audio",
      target_format: root.dataset.audioTargetFormat || "native",
      filename_template: root.dataset.audioFilenameTemplate || "audio_{node_id}_{timestamp}",
      max_duration_sec: Number(root.dataset.audioMaxDurationSec || 120),
    };
  }

  /**
   * Set compact status text on the card.
   *
   * @param {HTMLElement} root - Audio Record card root.
   * @param {string} message - Status message.
   */
  function setStatus(root, message) {
    const status = root.querySelector("[data-audio-record-card-status]");
    if (status) {
      status.textContent = message;
    }
  }

  registry.audio_recordNodeCard = {
    /**
     * Bind the Audio Record node-card press-and-hold recorder.
     *
     * @param {HTMLElement} root - Mounted node-card block root.
     * @param {object} api - Generic block UI API.
     */
    mount(root, api) {
      const button = root.querySelector("[data-audio-record-card-hold]");
      if (!(button instanceof HTMLButtonElement) || typeof window.CWAudioRecord?.createRecorder !== "function") {
        return;
      }
      let pointerActive = false;
      const recorder = window.CWAudioRecord.createRecorder({
        applyAction: (action, values) => api?.applyAction?.(action, values),
        config: () => captureConfig(root),
        maxDurationSec: () => Number(root.dataset.audioMaxDurationSec || 120),
        onStatus: (message) => setStatus(root, message),
        onStart: () => {
          button.classList.add("is-recording");
          button.textContent = "Rec...";
          if (!pointerActive) {
            recorder.stop();
          }
        },
        onStop: () => {
          button.classList.remove("is-recording");
          button.textContent = "Maintenir";
        },
        onSaved: (result) => {
          const savedPath = String(result.saved_path || result.node_patch?.config?.latest_audio_path || "");
          const warning = runtimePublicationWarning(result);
          setStatus(root, warning ? "Run absent" : savedPath ? "Audio envoye" : "Audio enregistre");
          api?.log?.(savedPath ? `[audio-record] Audio enregistre: ${savedPath}` : "[audio-record] Audio enregistre.");
          if (warning) {
            api?.log?.(`[audio-record-warn] ${warning}`);
          }
        },
        onError: (_error, message) => api?.log?.(`[audio-record-error] ${message}`),
      });

      const begin = (event) => {
        isolateCardControl(event);
        pointerActive = true;
        button.classList.add("is-recording");
        button.textContent = "...";
        void recorder.start();
      };
      const end = (event) => {
        isolateCardControl(event);
        pointerActive = false;
        recorder.stop();
      };
      button.addEventListener("pointerdown", begin);
      button.addEventListener("pointerup", end);
      button.addEventListener("pointercancel", end);
      button.addEventListener("mouseleave", (event) => {
        if (pointerActive) {
          end(event);
        }
      });
      for (const eventName of ["mousedown", "mouseup", "click", "dblclick", "contextmenu"]) {
        button.addEventListener(eventName, isolateCardControl);
      }
      const observer = new MutationObserver(() => {
        if (!root.isConnected) {
          recorder.dispose();
          observer.disconnect();
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
    },
  };
})();
