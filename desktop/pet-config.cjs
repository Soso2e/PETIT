'use strict';
// プティちゃん（Desktopマスコット）の見た目設定と、画面下での小さな散歩の計算。
// 描画用の値だけを扱い、会話・音声・認証情報は含めない。
const { PRESETS, MOTION_MODES, isHex } = require('./mascot/petit-mascot.js');

const PET_DEFAULTS = Object.freeze({
  petSize: 96, petPreset: 'pear', petBody: '', petRing: '', petMotion: 'auto', petRoam: false,
});
const PET_SIZE_MIN = 56;
const PET_SIZE_MAX = 200;

function normalizePet(raw = {}) {
  const size = Math.round(Number(raw.petSize));
  return {
    petSize: Number.isFinite(size) ? Math.min(PET_SIZE_MAX, Math.max(PET_SIZE_MIN, size)) : PET_DEFAULTS.petSize,
    petPreset: Object.hasOwn(PRESETS, raw.petPreset) ? raw.petPreset : PET_DEFAULTS.petPreset,
    petBody: isHex(raw.petBody) ? raw.petBody.toUpperCase() : '',
    petRing: isHex(raw.petRing) ? raw.petRing.toUpperCase() : '',
    petMotion: MOTION_MODES.includes(raw.petMotion) ? raw.petMotion : PET_DEFAULTS.petMotion,
    petRoam: raw.petRoam === true,
  };
}

/** レンダラーへ送る見た目（検証済みの値だけ） */
function petAppearance(config) {
  const p = normalizePet(config);
  return { size: p.petSize, preset: p.petPreset, body: p.petBody, ring: p.petRing, motion: p.petMotion };
}

/** マスコット本体＋上の吹き出し・つまみ分。吹き出しが切れない最小幅を確保する。 */
function petWindowSize(size) {
  const s = normalizePet({ petSize: size }).petSize;
  return { width: Math.max(132, s + 36), height: s + 34 };
}

/** 同じ高さのまま、作業領域内で近くの位置へ。 */
function nextRoamX(bounds, area, rand = Math.random, maxStep = 260) {
  const min = area.x, max = area.x + area.width - bounds.width;
  if (max <= min) return bounds.x;
  const step = (60 + rand() * (maxStep - 60)) * (rand() < 0.5 ? -1 : 1);
  let x = bounds.x + step;
  if (x < min || x > max) x = bounds.x - step; // 端なら反対へ
  return Math.round(Math.min(max, Math.max(min, x)));
}
function roamStep(x, target, speed) {
  const dx = target - x;
  return Math.abs(dx) <= speed ? target : Math.round(x + Math.sign(dx) * speed);
}

module.exports = { PET_DEFAULTS, PET_SIZE_MIN, PET_SIZE_MAX, normalizePet, petAppearance, petWindowSize, nextRoamX, roamStep };
