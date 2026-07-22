// Unlock mobile browser audio playback from a real user gesture before async TTS completes.
(() => {
  if (typeof Audio === "undefined") return;

  const SILENT_WAV = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";
  const AudioContextApi = window.AudioContext || window.webkitAudioContext;
  let audioContext = null;
  let unlocked = false;
  let unlocking = false;

  async function unlockAudio() {
    if (unlocked || unlocking) return;
    unlocking = true;
    try {
      if (AudioContextApi) {
        audioContext ||= new AudioContextApi();
        if (audioContext.state === "suspended") await audioContext.resume();
        const source = audioContext.createBufferSource();
        source.buffer = audioContext.createBuffer(1, 1, 22050);
        source.connect(audioContext.destination);
        source.start(0);
      }

      const audio = new Audio(SILENT_WAV);
      audio.playsInline = true;
      audio.volume = 0.01;
      const playResult = audio.play();
      if (playResult && typeof playResult.then === "function") await playResult;
      audio.pause();
      audio.removeAttribute("src");
      unlocked = true;
      window.__petitAudioUnlocked = true;
      removeListeners();
    } catch (error) {
      console.debug("PETIT audio unlock was deferred", error);
    } finally {
      unlocking = false;
    }
  }

  function onGesture(event) {
    if (event.type === "keydown" && !["Enter", " "].includes(event.key)) return;
    void unlockAudio();
  }

  function removeListeners() {
    document.removeEventListener("pointerdown", onGesture, true);
    document.removeEventListener("touchend", onGesture, true);
    document.removeEventListener("keydown", onGesture, true);
  }

  document.addEventListener("pointerdown", onGesture, true);
  document.addEventListener("touchend", onGesture, true);
  document.addEventListener("keydown", onGesture, true);
})();
