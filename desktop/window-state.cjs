'use strict';
const fs = require('node:fs');

function fitBounds(saved, fallback, areas) {
  const valid = saved && ['x', 'y', 'width', 'height'].every((key) => Number.isFinite(saved[key]));
  const value = valid ? saved : fallback;
  const area = areas.find((a) => value.x >= a.x && value.x < a.x + a.width && value.y >= a.y && value.y < a.y + a.height) || areas[0];
  const width = Math.min(area.width, Math.max(340, Math.round(value.width)));
  const height = Math.min(area.height, Math.max(400, Math.round(value.height)));
  return { width, height,
    x: Math.round(Math.max(area.x, Math.min(value.x ?? area.x + (area.width - width) / 2, area.x + area.width - width))),
    y: Math.round(Math.max(area.y, Math.min(value.y ?? area.y + area.height - height - 32, area.y + area.height - height))) };
}

function windowState(file) {
  let values = {};
  try { values = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { /* First launch or corrupt geometry. */ }
  return {
    get: (kind, fallback, areas) => fitBounds(values?.[kind], fallback, areas),
    remember(kind, bounds) {
      values = { ...values, [kind]: bounds };
      try {
        fs.writeFileSync(`${file}.tmp`, JSON.stringify(values), { mode: 0o600 });
        fs.renameSync(`${file}.tmp`, file);
      } catch { /* Geometry must never prevent use of PETIT. */ }
    },
  };
}
module.exports = { fitBounds, windowState };
