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
  const TTS_CHUNK_TARGET_CHARS = 48;
  const TTS_CHUNK_MAX_CHARS = 72;
  const TTS_CHUNK_TIMEOUT_MS = 5000;
  const voiceApprovePhrases = new Set([
    "はい", "うん", "お願い", "お願いします", "やって", "やってください",
    "実行", "実行して", "実行してください", "それで", "それでお願い",
    "ok", "okay", "オーケー",
  ]);
  const voiceCancelPhrases = new Set([
    "いいえ", "いや", "やめて", "やめる", "キャンセル", "取り消し",
    "実行しない", "しないで", "中止",
  ]);
  const completedActionReplies = {
    create_task: "タスクを追加しました。",
    add_task: "タスクを追加しました。",
    update_task: "タスクを変更しました。",
    complete_task: "タスクを完了にしました。",
    retry_task_sync: "タスク同期を再試行しました。",
    add_schedule: "予定を追加しました。",
    save_memory: "記憶に保存しました。",
    create_handoff_note: "引き継ぎメモを保存しました。",
    edit_brain_note: "BRAINノートを変更しました。",
    link_github_repository_candidate: "GitHubリポジトリを紐付けました。",
    ignore_github_repository_candidate: "GitHubリポジトリ候補を無視しました。",
  };

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

  function splitLongSpeechSegment(segment) {
    const chunks = [];
    let rest = segment.trim();
    while (rest.length > TTS_CHUNK_MAX_CHARS) {
      const candidates = [
        rest.lastIndexOf("、", TTS_CHUNK_MAX_CHARS),
        rest.lastIndexOf("，", TTS_CHUNK_MAX_CHARS),
        rest.lastIndexOf(",", TTS_CHUNK_MAX_CHARS),
        rest.lastIndexOf(" ", TTS_CHUNK_MAX_CHARS),
      ];
      let breakAt = Math.max(...candidates);
      if (breakAt < Math.floor(TTS_CHUNK_TARGET_CHARS / 2)) breakAt = TTS_CHUNK_MAX_CHARS;
      else breakAt += 1;
      chunks.push(rest.slice(0, breakAt).trim());
      rest = rest.slice(breakAt).trim();
    }
    if (rest) chunks.push(rest);
    return chunks;
  }

  function splitSpeechText(text) {
    const sentenceParts = String(text || "").match(/[^。！？!?\n]+[。！？!?]?/g) || [];
    const segments = sentenceParts.flatMap((part) => splitLongSpeechSegment(part));
    const chunks = [];
    let current = "";

    for (const segment of segments) {
      if (!segment) continue;
      if (!current) {
        current = segment;
        continue;
      }
      if (current.length < TTS_CHUNK_TARGET_CHARS && (current + segment).length <= TTS_CHUNK_MAX_CHARS) {
        current += segment;
        continue;
      }
      chunks.push(current);
      current = segment;
    }
    if (current) chunks.push(current);
    return chunks;
  }

  function normalizeVoiceCommand(text) {
    return String(text || "")
      .toLowerCase()
      .replace(/[\s、。,.!！?？]/g, "")
      .trim();
  }

  function directReplyText(bubble) {
    return Array.from(bubble.childNodes)
      .filter((node) => node.nodeType === Node.TEXT_NODE)
      .map((node) => node.textContent || "")
      .join("")
      .trim();
  }

  function replaceDirectReplyText(bubble, text) {
    const textNodes = Array.from(bubble.childNodes).filter((node) => node.nodeType === Node.TEXT_NODE);
    if (!textNodes.length) {
      bubble.prepend(document.createTextNode(text));
      return;
    }
    textNodes[0].textContent = text;
    for (const node of textNodes.slice(1)) node.remove();
  }

  function naturalizeCompletedAction(bubble) {
    const raw = directReplyText(bubble);
    if (!raw.startsWith("確認された内容を実行しました。")) return raw;
    const toolsText = bubble.querySelector(".tools")?.textContent || "";
    const actionName = Object.keys(completedActionReplies).find((name) => toolsText.includes(name));
    const friendly = actionName ? completedActionReplies[actionName] : "変更を実行しました。";
    replaceDirectReplyText(bubble, friendly);
    return friendly;
  }

  function pendingActionControls() {
    const candidates = Array.from(messagesEl.querySelectorAll(".action-confirm")).reverse();
    for (const controls of candidates) {
      const buttons = controls.querySelectorAll("button");
      if (buttons.length >= 2 && !buttons[0].disabled && !buttons[1].disabled) {
        return { approve: buttons[0], cancel: buttons[1] };
      }
    }
    return null;
  }

  function handlePendingVoiceDecision(transcript) {
    const pending = pendingActionControls();
    if (!pending) return false;
    const command = normalizeVoiceCommand(transcript);
    if (voiceApprovePhrases.has(command)) {
      setVoiceState("確認された操作を実行します。");
      pending.approve.click();
      return true;
    }
    if (voiceCancelPhrases.has(command)) {
      setVoiceState("操作をキャンセルします。");
      pending.cancel.click();
      return true;
    }
    return false;
  }

  function findJapaneseVoice() {
    if (!browserSpeechSupported) return null;
    const voices = window.speechSynthesis.getVoices();
    return voices.find((voice) => voice.lang === "ja-JP")
      || voices.find((voice) => voice.lang && voice.lang.toLowerCase().startsWith("ja"))
      || null;
  }

  function createAbortError() {
    const error = new Error("音声処理を中止しました。");
    error.name = "AbortError";
    return error;
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
    setVoiceState("");
  }

  function speakWithBrowser(text, { reason = "端末の音声で再生しています…" } = {}) {
    if (!browserSpeechSupported) return false;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "ja-JP";
    utterance.rate = 1.05;
    utterance.pitch = 1.0;
    const voice = findJapaneseVoice();
    if (voice) utterance.voice = voice;
    utterance.onstart = () => setVoiceState(reason);
    utterance.onend = () => setVoiceState("");
    utterance.onerror = () => setVoiceState("音声を再生できませんでした。", { error: true });
    window.speechSynthesis.speak(utterance);
    return true;
  }

  async function requestTtsBlob(text, controller) {
    if (controller.signal.aborted) throw createAbortError();

    const requestController = new AbortController();
    let timedOut = false;
    const cancelRequest = () => requestController.abort();
    controller.signal.addEventListener("abort", cancelRequest, { once: true });
    const timeoutId = window.setTimeout(() => {
      timedOut = true;
      requestController.abort();
    }, TTS_CHUNK_TIMEOUT_MS);

    try {
      const response = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
        signal: requestController.signal,
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
      return await response.blob();
    } catch (error) {
      if (timedOut) {
        const timeoutError = new Error("音声の準備がタイムアウトしました。");
        timeoutError.name = "TtsTimeoutError";
        throw timeoutError;
      }
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
      controller.signal.removeEventListener("abort", cancelRequest);
    }
  }

  function startTtsChunk(text, controller) {
    return requestTtsBlob(text, controller).then(
      (blob) => ({ blob, error: null }),
      (error) => ({ blob: null, error }),
    );
  }

  async function playAudioBlob(blob, controller) {
    if (controller.signal.aborted) throw createAbortError();
    releaseAudio();
    currentAudioUrl = URL.createObjectURL(blob);
    const audio = new Audio(currentAudioUrl);
    currentAudio = audio;

    await new Promise((resolve, reject) => {
      let settled = false;
      const finish = (error = null) => {
        if (settled) return;
        settled = true;
        controller.signal.removeEventListener("abort", handleAbort);
        if (currentAudio === audio) releaseAudio();
        if (error) reject(error);
        else resolve();
      };
      const handleAbort = () => finish(createAbortError());

      controller.signal.addEventListener("abort", handleAbort, { once: true });
      audio.onplay = () => {
        if (currentTtsRequest === controller) setVoiceState("PETITが話しています…");
      };
      audio.onended = () => finish();
      audio.onerror = () => finish(new Error("AivisSpeech音声の再生に失敗しました。"));
      audio.play().catch((error) => finish(error));
    });
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

    const chunks = splitSpeechText(spoken);
    if (!chunks.length) return;

    const controller = new AbortController();
    currentTtsRequest = controller;
    setVoiceState("音声を準備中…");

    let nextChunkIndex = 0;
    let pendingChunk = startTtsChunk(chunks[0], controller);

    try {
      while (nextChunkIndex < chunks.length) {
        const currentIndex = nextChunkIndex;
        const result = await pendingChunk;
        if (result.error) throw result.error;
        if (!result.blob || controller.signal.aborted || currentTtsRequest !== controller) return;

        const followingIndex = currentIndex + 1;
        pendingChunk = followingIndex < chunks.length
          ? startTtsChunk(chunks[followingIndex], controller)
          : null;

        await playAudioBlob(result.blob, controller);
        nextChunkIndex = followingIndex;
      }

      if (currentTtsRequest === controller) {
        currentTtsRequest = null;
        setVoiceState("");
      }
    } catch (error) {
      const cancelled = controller.signal.aborted || currentTtsRequest !== controller;
      if (cancelled) return;

      controller.abort();
      currentTtsRequest = null;
      releaseAudio();
      console.warn("AivisSpeech playback failed", error);

      const remainingText = chunks.slice(nextChunkIndex).join("") || spoken;
      const reason = error instanceof Error && error.name === "TtsTimeoutError"
        ? "音声の準備に時間がかかったため、端末の音声で再生しています…"
        : "AivisSpeechを利用できないため、端末の音声で再生しています…";
      if (!speakWithBrowser(remainingText, { reason })) {
        setVoiceState("音声を再生できませんでした。", { error: true });
      }
    }
  }

  function enhanceAssistantMessage(message, { autoSpeak = false } = {}) {
    if (!(message instanceof Element) || message.dataset.voiceEnhanced === "1" || message.id === "typing") return;
    const bubble = message.querySelector(":scope > .bubble");
    if (!bubble || bubble.classList.contains("typing") || bubble.classList.contains("bubble--error")) return;

    message.dataset.voiceEnhanced = "1";
    const replyText = naturalizeCompletedAction(bubble);
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
        if (handlePendingVoiceDecision(transcript)) {
          inputEl.value = "";
          inputEl.dispatchEvent(new Event("input"));
          return;
        }
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
    setVoiceState(voiceReplyEnabled ? "音声応答を有効にしました。" : "音声応答を無効にしました。");
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
