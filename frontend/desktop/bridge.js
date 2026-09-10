(() => {
  'use strict';
  if (!window.petitDesktop) return;
  // Match the tiny SpeechRecognition contract consumed by the shared voice.js.
  // Each start owns a generation; late permission/STT responses cannot submit after abort.
  class DesktopRecognition {
    constructor() { this.generation = 0; this.active = false; this.chunks = []; }
    start() {
      if (this.active) throw new Error('録音中です。');
      this.active = true; this.chunks = []; this.processing = false;
      const generation = ++this.generation;
      this.onstart?.();
      void this.capture(generation).catch((error) => {
        if (generation !== this.generation) return;
        this.onerror?.({ error: error.name === 'NotAllowedError' ? 'not-allowed' : 'audio-capture',
          message: error.name === 'NotAllowedError' ? 'マイクが許可されていません。OSのプライバシー設定を確認してください。' : 'マイクを開始できません。接続とOS権限を確認してください。' });
        this.finish();
      });
    }
    async capture(generation) {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false });
      if (generation !== this.generation) { stream.getTracks().forEach((track) => track.stop()); return; }
      this.stream = stream;
      this.context = new AudioContext({ sampleRate: 16000 });
      await this.context.audioWorklet.addModule('/static/desktop/capture-worklet.js');
      if (generation !== this.generation) return;
      await this.context.resume();
      if (generation !== this.generation) return;
      this.rate = this.context.sampleRate; this.endpoint = new PetitAudio.Endpointer(this.rate);
      this.source = this.context.createMediaStreamSource(stream);
      this.node = new AudioWorkletNode(this.context, 'petit-capture');
      this.node.port.onmessage = ({ data }) => {
        if (generation !== this.generation || this.processing) return;
        this.chunks.push(data);
        if (this.endpoint.push(data)) this.stop();
      };
      this.source.connect(this.node);
      // The processor outputs silence; connecting keeps the audio graph running without mic feedback.
      this.node.connect(this.context.destination);
      this.timer = setTimeout(() => this.stop(), 31000);
    }
    release() {
      clearTimeout(this.timer);
      this.source?.disconnect(); this.node?.disconnect();
      this.stream?.getTracks().forEach((track) => track.stop()); this.stream = null;
      if (this.context && this.context.state !== 'closed') void this.context.close().catch(() => {});
      this.context = null;
    }
    finish() { this.release(); this.active = false; this.processing = false; this.chunks = []; this.generation++; this.onend?.(); }
    stop() {
      if (!this.active || this.processing) return;
      this.processing = true; this.release();
      const generation = this.generation;
      if (!this.chunks.length || !this.endpoint?.speech) {
        this.onerror?.({ error: 'no-speech' }); this.finish(); return;
      }
      const wav = PetitAudio.encodeWav(this.chunks, this.rate); this.chunks = [];
      document.getElementById('voice-state').textContent = '聞き取った音声を文字にしています…';
      window.petitDesktop.transcribe(wav).then((text) => {
        if (generation !== this.generation) return;
        if (text) { const result = [{ transcript: text }]; result.isFinal = true; this.onresult?.({ resultIndex: 0, results: [result] }); }
        else this.onerror?.({ error: 'no-speech' });
      }).catch((error) => {
        if (generation === this.generation) this.onerror?.({ error: 'network', message: error.message });
      }).finally(() => { if (generation === this.generation) this.finish(); });
    }
    abort() { if (!this.active) return; void window.petitDesktop.cancel(); this.finish(); }
  }
  window.PetitDesktopSpeechRecognition = DesktopRecognition;
})();
