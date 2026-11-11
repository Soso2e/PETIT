'use strict';
// プティちゃんの描画は frontend/mascot が正本。Electron のローカル画面(pet.html)は
// file:// で読むため、同じファイルを desktop/mascot へ複製する。差分は test/pet-shell.test.cjs が検出する。
const fs = require('node:fs');
const path = require('node:path');
const FILES = ['petit-mascot.js', 'petit-mascot.css'];
const from = path.join(__dirname, '..', '..', 'frontend', 'mascot');
const to = path.join(__dirname, '..', 'mascot');
fs.mkdirSync(to, { recursive: true });
for (const file of FILES) fs.copyFileSync(path.join(from, file), path.join(to, file));
console.log(`synced ${FILES.join(', ')} -> desktop/mascot`);
module.exports = { FILES };
