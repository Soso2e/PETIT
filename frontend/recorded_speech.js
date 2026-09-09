// SpeechRecognition-shaped adapter; audio is sent only to PETIT's configured STT.
(() => {
  class RecordedSpeechRecognition {
    static supported() {
      return Boolean(window.isSecureContext && navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
    }
    start() {
      if (this.active) throw new Error('音声入力は処理中です。');
      this.active = true;
      this.session = (this.session || 0) + 1;
      const session = this.session;
      this.chunks = [];
      this.bytes = 0;
      this.controller = new AbortController();
      this.timer = setTimeout(() => this.fail('マイクの許可待ちが時間切れになりました。サイトのマイク権限を確認してください。'), 30000);
      this.capture(session);
    }
    async capture(session) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (!this.active || session !== this.session) {
          stream.getTracks().forEach(track => track.stop());
          return;
        }
        clearTimeout(this.timer);
        this.stream = stream;
        const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus']
          .find(type => MediaRecorder.isTypeSupported(type));
        if (!mimeType) throw new Error('このブラウザの録音形式には対応していません。');
        this.recorder = new MediaRecorder(stream, { mimeType });
        this.recorder.ondataavailable = event => {
          if (!this.active || session !== this.session) return;
          this.bytes += event.data.size;
          if (this.bytes > 8 * 1024 * 1024) return this.fail('録音が大きすぎます。短く録音し直してください。');
          if (event.data.size) this.chunks.push(event.data);
        };
        this.recorder.onerror = () => this.fail('録音に失敗しました。マイクの接続を確認してください。');
        this.recorder.onstop = () => this.transcribe(session, mimeType);
        this.recorder.start(1000);
        this.timer = setTimeout(() => this.stop(), 60000);
        this.onstart?.();
      } catch (error) {
        if (!this.active || session !== this.session) return;
        const message = {
          NotAllowedError: 'マイクが許可されていません。サイトのマイク権限と、Macのシステム設定 → プライバシーとセキュリティ → マイクを確認してください。',
          NotFoundError: 'マイクが見つかりません。Macのシステム設定 → サウンド → 入力で確認してください。',
          NotReadableError: 'マイクを開けません。他の録音アプリを閉じ、入力デバイスを確認してください。',
        }[error.name] || error.message || '録音を開始できませんでした。';
        this.fail(message);
      }
    }
    stop() {
      if (this.recorder?.state === 'recording') {
        clearTimeout(this.timer);
        this.recorder.stop();
        this.releaseMicrophone();
        this.onprocessing?.();
      }
    }
    releaseMicrophone() {
      this.stream?.getTracks().forEach(track => track.stop());
      this.stream = null;
    }
    async transcribe(session, mimeType) {
      if (!this.active || session !== this.session) return;
      this.timer = setTimeout(() => this.fail('音声認識が時間切れになりました。再試行してください。'), 65000);
      try {
        const response = await fetch('/api/stt', { method: 'POST', headers: { 'Content-Type': mimeType },
          body: new Blob(this.chunks, { type: mimeType }), signal: this.controller.signal });
        const data = await response.json();
        if (!this.active || session !== this.session) return;
        if (!response.ok) throw new Error(data.error || '音声認識に失敗しました。');
        if (typeof data.text !== 'string') throw new Error('音声認識の応答形式が不正です。');
        if (!data.text.trim()) throw new Error('音声を聞き取れませんでした。もう一度話してください。');
        const result = [{ transcript: data.text }];
        result.isFinal = true;
        this.onresult?.({ resultIndex: 0, results: [result] });
        this.finish();
      } catch (error) {
        if (this.active && session === this.session) this.fail(error.message || '音声認識に接続できません。');
      }
    }
    fail(message) {
      this.onerror?.({ error: 'recording', message });
      this.finish();
    }
    finish() {
      if (!this.active) return;
      this.active = false;
      clearTimeout(this.timer);
      this.controller?.abort();
      if (this.recorder) {
        this.recorder.onstop = null;
        this.recorder.onerror = null;
        if (this.recorder.state === 'recording') this.recorder.stop();
      }
      this.releaseMicrophone();
      this.recorder = null;
      this.chunks = [];
      this.onend?.();
    }
    abort() { this.finish(); }
  }
  window.PetitRecordedSpeechRecognition = RecordedSpeechRecognition;
})();
