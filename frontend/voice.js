// PETIT voice mode — browser speech input + AivisSpeech output layered over the existing chat UI.
(() => {
  const messagesEl = document.getElementById("messages");
  const formEl = document.getElementById("chat-form");
  const inputEl = document.getElementById("input");
  const sendEl = document.getElementById("send");
  const micEl = document.getElementById("mic");
  const voiceToggleEl = document.getElementById("voice-toggle");
  const voiceStateEl = document.getElementById("voice-state");

  if (!messagesEl || !formEl || !inputEl || !sendEl || !micEl || !voiceToggleEl || !voiceStateEl) return;

  const SpeechRecognitionApi = window.SpeechRecognition || window.webkitSpeechRecognition;
  const speechRecognitionSupported = Boolean(SpeechRecognitionApi);
  const browserSpeechSupported = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
  const audioPlaybackSupported = typeof Audio !== "undefined" && typeof fetch === "function";

  let voiceReplyEnabled = localStorage.getItem("petit_voice_reply_enabled") === "1";
  let recognition = null;
  let listening = false;
  let finalTranscript = "";
  let draftBeforeListening = "";
  let observerReady = false;
  let currentAudio = null;
  let currentAudioUrl = null;
  let currentTtsRequest = null;

  function setVoiceState(message, { error = false } = {}) {
    voiceStateEl.textContent = message || "";
    voiceStateEl.className = "voice-state" + (error ? " voice-state--error" : "");
  }

  function updateVoiceToggle() {
    if (!audioPlaybackSupported && !browserSpeechSupported) {
      voiceReplyEnabled = false;
      voiceToggleEl.disabled = true;
      voiceToggleEl.textContent = "音声応答 非対応";
      voiceToggleEl.setAttribute("aria-pressed", "false");
      return;
    }

    voiceToggleEl.disabled = false;
    voiceToggleEl.textContent = voiceReplyEnabled ? "音声応答 ON" : "音声応答 OFF";
    voiceToggleEl.classList.toggle("voice-toggle--on", voiceReplyEnabled);
    voiceToggleEl.setAttribute("aria-pressed", String(voiceReplyEnabled));
  }

  function updateMicAvailability() {
    if (speechRecognitionSupported) {
      micEl.disabled = false;
      micEl.title = "押して話す";
      return;
    }

    micEl.disabled = true;
    micEl.title = "このブラウザは音声入力に対応していません";
    setVoiceState("音声入力はこのブラウザでは利用できません。ChromeまたはEdgeで開いてください。", { error: true });
  }

  function normalizeSpeechText(text) {
    return String(text || "")
      .replace(/```[\s\S]*?```/g, " コードは画面を確認してください。 ")
      .replace(/https?:\/\/\S+/g, " URLは画面を確認してください。 ")
      .replace(/[`*_>#\[\]()]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function findJapaneseVoice() {
    if (!browserSpeechSupported) return null;
    const voices = window.speechSynthesis.getVoices();
    return voices.find((voice) => voice.lang === "ja-JP")
      || voices.find((voice) => voice.lang && voice.lang.toLowerCase().startsWith("ja"))
      || null;
  }

  function releaseAudio() {
    if (currentAudio) {
      currentAudio.pause();
      currentAudio.src = "";
      currentAudio = null;
    }
    if (currentAudioUrl) {
      URL.revokeObjectURL(currentAudioUrl);
      currentAudioUrl = null;
    }
  }

  function stopSpeaking() {
    if (currentTtsRequest) {
      currentTtsRequest.abort();
      currentTtsRequest = null;
    }
    releaseAudio();
    if (browserSpeechSupported) window.speechSynthesis.cancel();
  }

  function speakWithBrowser(text) {
    if (!browserSpeechSupported) return false;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "ja-JP";
    utterance.rate = 1.05;
    utterance.pitch = 1.0;
    const voice = findJapaneseVoice();
    if (voice) utterance.voice = voice;
    utterance.onstart = () => setVoiceState("AivisSpeechに接続できないため、ブラウザ音声で再生しています…");
    utterance.onend = () => setVoiceState("");
    utterance.onerror = () => setVoiceState("音声の再生に失敗しました。", { error: true });
    window.speechSynthesis.speak(utterance);
    return true;
  }

  async function speakText(text, { force = false } = {}) {
    if (!voiceReplyEnabled && !force) return;
    const spoken = normalizeSpeechText(text);
    if (!spoken) return;

    stopSpeaking();
    if (!audioPlaybackSupported) {
      if (!speakWithBrowser(spoken)) setVoiceState("音声再生に対応していません。", { error: true });
      return;
    }

    const controller = new AbortController();
    currentTtsRequest = controller;
    setVoiceState("AivisSpeechで音声を生成しています…");

    try {
      const response = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: spoken }),
        signal: controller.signal,
      });
      if (!response.ok) {
        let detail = "";
        try {
          detail = (await response.json()).error || "";
        } catch (_error) {
          detail = "";
        }
        throw new Error(detail || `HTTP ${response.status}`);
      }

      const blob = await response.blob();
      if (controller.signal.aborted || currentTtsRequest !== controller) return;
      currentTtsRequest = null;
      currentAudioUrl = URL.createObjectURL(blob);
      currentAudio = new Audio(currentAudioUrl);
      currentAudio.onplay = () => setVoiceState("PETITが話しています…");
      currentAudio.onended = () => {
        releaseAudio();
        setVoiceState("");
      };
      currentAudio.onerror = () => {
        releaseAudio();
        setVoiceState("AivisSpeech音声の再生に失敗しました。", { error: true });
      };
      await currentAudio.play();
    } catch (error) {
      if (controller.signal.aborted) return;
      currentTtsRequest = null;
      releaseAudio();
      if (!speakWithBrowser(spoken)) {
        const message = error instanceof Error ? error.message : "AivisSpeechへ接続できません。";
        setVoiceState(`音声を再生できませんでした。${message}`, { error: true });
      }
    }
  }

  function enhanceAssistantMessage(message, { autoSpeak = false } = {}) {
    if (!(message instanceof Element) || message.dataset.voiceEnhanced === "1" || message.id === "typing") return;
    const bubble = message.querySelector(":scope > .bubble");
    if (!bubble || bubble.classList.contains("typing") || bubble.classList.contains("bubble--error")) return;

    message.dataset.voiceEnhanced = "1";
    const replyText = bubble.textContent || "";
    if (!replyText.trim()) return;

    const replay = document.createElement("button");
    replay.type = "button";
    replay.className = "replay";
    replay.textContent = "🔊";
    replay.setAttribute("aria-label", "この返答を読み上げる");
    replay.title = "読み上げる";
    replay.addEventListener("click", () => void speakText(replyText, { force: true }));
    message.appendChild(replay);

    if (autoSpeak && observerReady) void speakText(replyText);
  }

  const messageObserver = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (!(node instanceof Element)) continue;
        if (node.matches(".msg--user")) stopSpeaking();
        if (node.matches(".msg--assistant")) enhanceAssistantMessage(node, { autoSpeak: true });
        for (const message of node.querySelectorAll?.(".msg--assistant") || []) {
          enhanceAssistantMessage(message, { autoSpeak: true });
        }
      }
    }
  });
  messageObserver.observe(messagesEl, { childList: true, subtree: true });

  function setListeningState(on) {
    listening = on;
    micEl.classList.toggle("mic--listening", on);
    micEl.setAttribute("aria-label", on ? "音声入力を停止" : "音声入力を開始");
    micEl.textContent = on ? "■" : "🎤";
    if (on) setVoiceState("聞き取り中… もう一度押すと停止します");
  }

  function ensureRecognition() {
    if (!speechRecognitionSupported || recognition) return recognition;

    recognition = new SpeechRecognitionApi();
    recognition.lang = "ja-JP";
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      finalTranscript = "";
      setListeningState(true);
    };

    recognition.onresult = (event) => {
      let interimTranscript = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const transcript = event.results[index][0].transcript;
        if (event.results[index].isFinal) finalTranscript += transcript;
        else interimTranscript += transcript;
      }
      inputEl.value = (finalTranscript + interimTranscript).trimStart();
      inputEl.dispatchEvent(new Event("input"));
    };

    recognition.onerror = (event) => {
      const friendly = {
        "audio-capture": "マイクを利用できません。",
        "not-allowed": "マイクの使用が許可されていません。ブラウザ設定を確認してください。",
        "no-speech": "音声を聞き取れませんでした。もう一度試してください。",
        network: "音声認識サービスへ接続できませんでした。",
      }[event.error] || `音声入力に失敗しました（${event.error}）。`;
      setVoiceState(friendly, { error: true });
    };

    recognition.onend = () => {
      setListeningState(false);
      const transcript = finalTranscript.trim();
      if (transcript) {
        inputEl.value = transcript;
        inputEl.dispatchEvent(new Event("input"));
        setVoiceState(`聞き取り: ${transcript}`);
        formEl.requestSubmit();
      } else if (!inputEl.value.trim()) {
        inputEl.value = draftBeforeListening;
      }
    };

    return recognition;
  }

  function toggleListening() {
    if (!speechRecognitionSupported || sendEl.disabled) return;
    const speechRecognition = ensureRecognition();
    if (!speechRecognition) return;

    if (listening) {
      speechRecognition.stop();
      return;
    }

    draftBeforeListening = inputEl.value;
    finalTranscript = "";
    stopSpeaking();
    inputEl.value = "";
    try {
      speechRecognition.start();
    } catch (error) {
      inputEl.value = draftBeforeListening;
      setVoiceState("音声入力を開始できませんでした。少し待ってから再試行してください。", { error: true });
    }
  }

  voiceToggleEl.addEventListener("click", () => {
    if (!audioPlaybackSupported && !browserSpeechSupported) return;
    voiceReplyEnabled = !voiceReplyEnabled;
    localStorage.setItem("petit_voice_reply_enabled", voiceReplyEnabled ? "1" : "0");
    if (!voiceReplyEnabled) stopSpeaking();
    updateVoiceToggle();
    setVoiceState(voiceReplyEnabled ? "AivisSpeech音声応答を有効にしました。" : "音声応答を無効にしました。");
  });

  micEl.addEventListener("click", toggleListening);

  updateVoiceToggle();
  updateMicAvailability();

  // Existing conversations are restored during startup. Enhance them without reading
  // the entire history aloud, then enable auto-speech for newly arriving replies.
  window.setTimeout(() => {
    for (const message of messagesEl.querySelectorAll(".msg--assistant")) {
      enhanceAssistantMessage(message, { autoSpeak: false });
    }
    observerReady = true;
  }, 1500);
})();
