(function (root) {
  'use strict';
  // A half-duplex turn resumes only after BOTH chat and playback finish.
  class VoiceConversation {
    constructor({ listen, changed, schedule = (fn) => setTimeout(fn, 150) }) {
      this.listen = listen; this.changed = changed; this.schedule = schedule;
      this.active = false; this.generation = 0;
    }
    start() { this.active = true; this.generation++; this.changed(true); this.listen(); }
    stop() { this.active = false; this.generation++; this.changed(false); }
    beginTurn() {
      this.generation++; this.chatDone = false; this.audioDone = false; this.queued = false;
      return this.generation;
    }
    finishChat(token, result) {
      if (!this.active || token !== this.generation) return;
      if (!result || result.error || !result.reply || result.pending_actions?.length) { this.stop(); return; }
      this.chatDone = true; this.resume(token);
    }
    finishAudio(token, success) {
      if (!this.active || token !== this.generation) return;
      if (!success) { this.stop(); return; }
      this.audioDone = true; this.resume(token);
    }
    resume(token) {
      if (!this.chatDone || !this.audioDone || this.queued) return;
      this.queued = true;
      this.schedule(() => { if (this.active && token === this.generation) this.listen(); });
    }
  }
  if (typeof module !== 'undefined') module.exports = VoiceConversation;
  else root.PetitVoiceConversationController = VoiceConversation;
})(globalThis);
