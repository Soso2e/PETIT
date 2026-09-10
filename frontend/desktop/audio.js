(function (root) {
  'use strict';
  function encodeWav(chunks, sampleRate) {
    const length = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const buffer = new ArrayBuffer(44 + length * 2);
    const view = new DataView(buffer);
    const text = (offset, value) => [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
    text(0, 'RIFF'); view.setUint32(4, 36 + length * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true); text(36, 'data'); view.setUint32(40, length * 2, true);
    let offset = 44;
    for (const chunk of chunks) for (const sample of chunk) {
      const value = Math.max(-1, Math.min(1, Number.isFinite(sample) ? sample : 0));
      view.setInt16(offset, value < 0 ? value * 32768 : value * 32767, true); offset += 2;
    }
    return buffer;
  }
  class Endpointer {
    constructor(rate) { this.rate = rate; this.total = 0; this.lastSpeech = 0; this.speech = 0; }
    push(frame) {
      this.total += frame.length;
      const rms = Math.sqrt(frame.reduce((sum, value) => sum + value * value, 0) / frame.length);
      if (rms > 0.012) { this.lastSpeech = this.total; this.speech += frame.length; }
      return this.total >= 30 * this.rate || (!this.speech && this.total >= 8 * this.rate) ||
        (this.speech > .15 * this.rate && this.total - this.lastSpeech >= 1.2 * this.rate);
    }
  }
  const api = { encodeWav, Endpointer };
  if (typeof module !== 'undefined') module.exports = api;
  else root.PetitAudio = api;
})(globalThis);
