'use strict';
// Isolated utility process: native audio never runs on Electron's UI thread.
// No audio/text/key logging; only a detection or a generic failure crosses IPC.
const { Porcupine } = require('@picovoice/porcupine-node');
const { PvRecorder } = require('@picovoice/pvrecorder-node');
let running = false;
process.parentPort.on('message', async ({ data }) => {
  if (data.type !== 'start' || running) return;
  running = true;
  let engine, recorder;
  try {
    engine = new Porcupine(data.key, [data.keywordPath], [0.6], { modelPath: data.modelPath });
    recorder = new PvRecorder(engine.frameLength);
    if (recorder.sampleRate !== engine.sampleRate) throw new Error('sample-rate');
    recorder.start();
    process.parentPort.postMessage({ type: 'ready' });
    while (running) {
      const pcm = await recorder.read();
      if (engine.process(pcm) >= 0) {
        recorder.stop();
        running = false;
        process.parentPort.postMessage({ type: 'wake' });
      }
    }
  } catch {
    process.parentPort.postMessage({ type: 'error' });
  } finally {
    if (recorder?.isRecording) recorder.stop();
    recorder?.release();
    engine?.release();
  }
});
