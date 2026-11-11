/*
 * PETIT mascot「プティちゃん」— Web / Desktop 共通の軽量SVGレンダラー。
 *
 * - 依存なし・フィルターなし。描画は小さなインラインSVG 1つとCSSアニメーションだけ。
 * - 表情は「パーツ（目・口・眉・頬・汗・エフェクト）の組み合わせ」で定義する。
 *   新しい表情は EMOTIONS に1行足すだけ。新しい形は PARTS に1エントリ足す。
 * - 動作は data-action 属性で切り替え、アニメーション本体は petit-mascot.css にある。
 * - PETITの状態（考え中・聞き取り・発話など）は STATES で表情＋動作へ対応付ける。
 * - toStaticSVG() は DOM なしでも動くので、トレイ/メニューバー/アイコン生成に流用できる。
 *
 * 会話本文・音声・認証情報は一切扱わない（表示専用）。
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root && typeof root === 'object') root.PetitMascot = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const VERSION = 2;
  // レジストリは null プロトタイプ（'constructor' 等の名前で誤って一致しない）。
  const dict = (obj) => Object.freeze(Object.assign(Object.create(null), obj));

  // ---------------------------------------------------------------- colors
  const DEFAULT_COLORS = Object.freeze({
    body: '#FFE9B9', ring: '#F37865', leaf: '#F07861', ink: '#303953', mouth: '#F17D6D',
    cheek: '#FF9C8F', star: '#F8B548', sweat: '#8EC9F0', white: '#FFFFFF',
  });

  const PRESETS = dict({
    pear:     { label: 'ペア',     body: '#FFE9B9', ring: '#F37865', leaf: '#F07861' },
    mint:     { label: 'ミント',   body: '#D3F5E6', ring: '#3FAE97', leaf: '#2F9C83' },
    sakura:   { label: 'さくら',   body: '#FFE3EB', ring: '#EE7AA0', leaf: '#E1668D' },
    sky:      { label: 'そら',     body: '#DDEBFF', ring: '#5B8DEF', leaf: '#4C7BD9' },
    lavender: { label: 'ラベンダー', body: '#ECE3FF', ring: '#9B7CEA', leaf: '#8667D6' },
    lemon:    { label: 'レモン',   body: '#FFF4A8', ring: '#F2A33A', leaf: '#E48C2A' },
    cocoa:    { label: 'ココア',   body: '#E9CBA7', ring: '#B9694A', leaf: '#A65A3E' },
  });

  const HEX = /^#[0-9a-f]{6}$/i;
  const isHex = (value) => typeof value === 'string' && HEX.test(value);

  function mixHex(a, b, t) {
    const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
    const ch = (shift) => Math.round(((pa >> shift) & 255) * (1 - t) + ((pb >> shift) & 255) * t);
    return '#' + [16, 8, 0].map((s) => ch(s).toString(16).padStart(2, '0')).join('');
  }

  /** プリセット名 or {preset, body, ring, leaf} を、描画に使う全色へ展開する。 */
  function resolveColors(input) {
    const opts = typeof input === 'string' ? { preset: input } : (input || {});
    const preset = Object.hasOwn(PRESETS, opts.preset) ? PRESETS[opts.preset] : PRESETS.pear;
    const c = { ...DEFAULT_COLORS, body: preset.body, ring: preset.ring, leaf: preset.leaf };
    for (const key of Object.keys(DEFAULT_COLORS)) if (isHex(opts[key])) c[key] = opts[key];
    // 輪だけ指定されたら葉も輪に寄せる（葉は輪と同系色がデザイン上の基準）。
    if (isHex(opts.ring) && !isHex(opts.leaf)) c.leaf = mixHex(opts.ring, '#000000', 0.05);
    c.bodyHi = mixHex(c.body, '#FFFFFF', 0.45);
    c.bodyLo = mixHex(c.body, '#F2A35A', 0.18);
    c.shade = mixHex(c.body, '#C9762E', 0.45);
    c.vein = mixHex(c.body, '#FFFFFF', 0.2);
    return c;
  }

  // ---------------------------------------------------------------- parts
  // ellipse を1本のpathにする（ノード数削減）。
  const ell = (cx, cy, rx, ry) => `M${cx - rx} ${cy}a${rx} ${ry} 0 1 0 ${2 * rx} 0a${rx} ${ry} 0 1 0 ${-2 * rx} 0Z`;

  // paint(kind) はライブ時はCSS変数のclass、静的出力時は実際の色属性になる。
  const PARTS = dict({
    eyes: dict({
      open: (p) => `<path ${p('ink')} d="${ell(211, 298, 19, 29)}${ell(306, 298, 19, 29)}"/>` +
        `<path ${p('white')} d="${ell(218, 285, 8, 12)}${ell(313, 285, 8, 12)}${ell(206, 309, 4, 4)}${ell(301, 309, 4, 4)}"/>`,
      happy: (p) => `<path ${p('ink', 10)} d="M192 306Q211 276 230 306M287 306Q306 276 325 306"/>`,
      closed: (p) => `<path ${p('ink', 9)} d="M192 300Q211 314 230 300M287 300Q306 314 325 300"/>`,
      wink: (p) => `<path ${p('ink')} d="${ell(211, 298, 19, 29)}"/><path ${p('white')} d="${ell(218, 285, 8, 12)}${ell(206, 309, 4, 4)}"/>` +
        `<path ${p('ink', 10)} d="M287 304Q306 280 325 304"/>`,
      dizzy: (p) => `<path ${p('ink', 8)} d="M197 284L225 312M225 284L197 312M292 284L320 312M320 284L292 312"/>`,
    }),
    brows: dict({
      angry: (p) => `<path ${p('ink', 9)} d="M186 254L232 272M327 254L281 272"/>`,
      worried: (p) => `<path ${p('ink', 8)} d="M188 268L230 254M325 268L283 254"/>`,
      tilt: (p) => `<path ${p('ink', 8)} d="M190 262Q210 248 231 257M284 268L326 264"/>`,
      up: (p) => `<path ${p('ink', 8)} d="M192 254Q211 242 230 252M283 252Q302 242 321 254"/>`,
    }),
    mouth: dict({
      soft: (p) => `<path ${p('mouth', 7)} d="M241 322Q256 336 271 322"/>`,
      open: (p) => `<path ${p('mouth')} d="M241 316Q255 315 272 316C273 329 264 341 257 341C248 341 241 327 241 316Z"/>`,
      talk: (p) => `<path ${p('mouth')} d="M241 316Q255 315 272 316C273 329 264 341 257 341C248 341 241 327 241 316Z"/>`,
      grin: (p) => `<path ${p('mouth')} d="M233 314Q256 318 279 314C280 337 268 351 256 351C244 351 232 337 233 314Z"/>`,
      frown: (p) => `<path ${p('mouth', 7)} d="M241 336Q256 322 271 336"/>`,
      wavy: (p) => `<path ${p('mouth', 6)} d="M236 332Q242 324 248 332T260 332T272 332"/>`,
      flat: (p) => `<path ${p('mouth', 7)} d="M244 328L268 328"/>`,
      o: (p) => `<path ${p('mouth')} d="${ell(256, 331, 10, 13)}"/>`,
      small: (p) => `<path ${p('mouth')} d="${ell(256, 330, 6, 7)}"/>`,
    }),
    cheeks: dict({ on: (p) => `<path ${p('cheek')} opacity=".55" d="${ell(172, 334, 17, 10)}${ell(344, 334, 17, 10)}"/>` }),
    sweat: dict({ on: (p) => `<path ${p('sweat')} d="M354 222Q368 246 354 256Q340 246 354 222Z"/>` }),
    fx: dict({
      sparkle: (p) => `<g class="pm-fx-a"><path ${p('star')} d="M89 175Q98 207 120 212Q98 219 89 251Q80 219 58 212Q80 207 89 175Z"/></g>` +
        `<g class="pm-fx-b"><path ${p('star')} d="M409 183Q414 198 430 204Q414 210 409 225Q404 210 388 204Q404 198 409 183Z"/></g>` +
        `<g class="pm-fx-c"><path ${p('star')} d="M435 363Q440 380 454 385Q440 390 435 407Q430 390 416 385Q430 380 435 363Z"/></g>`,
      heart: (p) => `<g class="pm-fx-a"><path ${p('ring')} d="M130 162C96 138 100 104 120 104C128 104 130 112 130 117C130 112 132 104 140 104C160 104 164 138 130 162Z"/></g>`,
      anger: (p) => `<g class="pm-fx-a"><path ${p('ring', 8)} d="M116 106Q128 116 118 128M144 102Q134 116 148 124M118 142Q130 132 142 144M152 132Q138 134 142 148"/></g>`,
      question: (p) => `<g class="pm-fx-a"><path ${p('ink', 11)} d="M112 116Q112 90 136 90Q160 90 160 112Q160 128 138 136L138 152"/></g><g class="pm-fx-a"><path ${p('ink')} d="${ell(138, 174, 7, 7)}"/></g>`,
      exclaim: (p) => `<g class="pm-fx-a"><path ${p('ring', 13)} d="M136 88L136 146"/></g><g class="pm-fx-a"><path ${p('ring')} d="${ell(136, 172, 8, 8)}"/></g>`,
      zzz: (p) => `<g class="pm-fx-a"><path ${p('ink', 7)} d="M152 168h22l-22 24h22"/></g><g class="pm-fx-b"><path ${p('ink', 7)} d="M118 126h28l-28 30h28"/></g>` +
        `<g class="pm-fx-c"><path ${p('ink', 7)} d="M76 80h22l-22 24h22"/></g>`,
      dots: (p) => `<g class="pm-fx-a"><path ${p('ink')} opacity=".7" d="${ell(168, 176, 8, 8)}"/></g><g class="pm-fx-b"><path ${p('ink')} opacity=".7" d="${ell(138, 146, 11, 11)}"/></g>` +
        `<g class="pm-fx-c"><path ${p('ink')} opacity=".7" d="${ell(102, 108, 15, 15)}"/></g>`,
      note: (p) => `<g class="pm-fx-a"><path ${p('ink', 7)} d="M126 156V104L160 96V146"/></g><g class="pm-fx-a"><path ${p('ink')} d="${ell(116, 158, 12, 9)}${ell(150, 148, 12, 9)}"/></g>`,
    }),
  });

  // ---------------------------------------------------------------- emotions
  // eyes/mouth/brows/fx は PARTS のキー。lid は目の開き具合（CSS変形）、look は視線の既定値。
  const EMOTIONS = dict({
    neutral:   { eyes: 'open', mouth: 'soft' },
    happy:     { eyes: 'open', mouth: 'open', cheeks: true },
    joy:       { eyes: 'happy', mouth: 'grin', cheeks: true, fx: 'sparkle' },
    love:      { eyes: 'happy', mouth: 'soft', cheeks: true, fx: 'heart' },
    proud:     { eyes: 'wink', mouth: 'grin', cheeks: true, fx: 'sparkle' },
    curious:   { eyes: 'open', mouth: 'small', brows: 'up', look: [0.35, -0.2] },
    focused:   { eyes: 'open', mouth: 'small', lid: 'wide' },
    thinking:  { eyes: 'open', mouth: 'flat', brows: 'tilt', fx: 'dots', look: [-0.55, -0.7] },
    talking:   { eyes: 'open', mouth: 'talk', cheeks: true },
    singing:   { eyes: 'happy', mouth: 'talk', cheeks: true, fx: 'note' },
    surprised: { eyes: 'open', mouth: 'o', brows: 'up', lid: 'wide', fx: 'exclaim' },
    confused:  { eyes: 'open', mouth: 'wavy', brows: 'tilt', sweat: true, fx: 'question' },
    worried:   { eyes: 'open', mouth: 'wavy', brows: 'worried', sweat: true },
    sad:       { eyes: 'open', mouth: 'frown', brows: 'worried', lid: 'low', look: [0, 0.5] },
    angry:     { eyes: 'open', mouth: 'frown', brows: 'angry', lid: 'low', fx: 'anger' },
    dizzy:     { eyes: 'dizzy', mouth: 'wavy', sweat: true },
    sleepy:    { eyes: 'open', mouth: 'small', lid: 'drowsy' },
    asleep:    { eyes: 'closed', mouth: 'small', fx: 'zzz' },
  });

  // ---------------------------------------------------------------- actions
  // CSS側の [data-action="..."] と1対1。ms がある動作は一回きり（react で使う）。
  const ACTIONS = dict({
    idle: {}, walk: {}, run: {}, hop: { ms: 700 }, jump: { ms: 900 }, celebrate: {}, dance: {},
    sleep: {}, think: {}, listen: {}, talk: {}, shake: { ms: 600 }, nod: { ms: 700 }, surprise: { ms: 500 },
    turn: { ms: 900 }, stretch: { ms: 1500 }, look: { ms: 2400 }, wiggle: { ms: 600 }, dangle: {}, land: { ms: 520 },
    pulse: {},
  });

  // ---------------------------------------------------------------- PETIT states
  // 会話・音声・処理状態 → 表情＋動作。transient は一時表示(ms)のあと基準状態へ戻る。
  const STATES = dict({
    idle:      { emotion: 'neutral', action: 'idle' },
    wake:      { emotion: 'curious', action: 'idle', caption: '呼んでね' },
    active:    { emotion: 'happy', action: 'idle', caption: 'なあに？' },
    typing:    { emotion: 'curious', action: 'idle', look: [0, 0.75] },
    listening: { emotion: 'focused', action: 'listen', caption: '聞いているよ' },
    thinking:  { emotion: 'thinking', action: 'think', caption: '考え中…' },
    speaking:  { emotion: 'talking', action: 'talk' },
    approval:  { emotion: 'curious', action: 'nod', caption: '確認してね' },
    success:   { emotion: 'joy', action: 'celebrate', transient: 1700 },
    error:     { emotion: 'confused', action: 'shake', caption: 'うまくいかなかった…', transient: 2600 },
    offline:   { emotion: 'worried', action: 'idle', caption: 'つながらない…' },
    sleep:     { emotion: 'asleep', action: 'sleep' },
  });

  const MOTION_MODES = ['auto', 'full', 'reduced'];
  function motionAllowed(mode) {
    if (mode === 'full') return true;
    if (mode === 'reduced') return false;
    return !(typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  // ---------------------------------------------------------------- markup
  let uidSeq = 0;
  const SLOT_ORDER = ['brows', 'eyes'];

  function livePaint(kind, strokeWidth) {
    return strokeWidth
      ? `class="pm-s-${kind}" fill="none" stroke-width="${strokeWidth}" stroke-linecap="round" stroke-linejoin="round"`
      : `class="pm-f-${kind}"`;
  }
  function staticPaint(colors) {
    return (kind, strokeWidth) => strokeWidth
      ? `fill="none" stroke="${colors[kind]}" stroke-width="${strokeWidth}" stroke-linecap="round" stroke-linejoin="round"`
      : `fill="${colors[kind]}"`;
  }

  // filter(slot, variant) が true のパーツだけを出力する（静的出力では現在の表情だけ）。
  function partsMarkup(slot, paint, filter) {
    return Object.entries(PARTS[slot]).filter(([variant]) => filter(slot, variant))
      .map(([variant, draw]) => `<g data-slot="${slot}" data-variant="${variant}">${draw(paint)}</g>`).join('');
  }

  function buildMarkup({ uid, paint, filter, colors }) {
    const grad = `pm-g-${uid}`, clip = `pm-c-${uid}`;
    const stop = (offset, key) => colors ? `<stop offset="${offset}" stop-color="${colors[key]}"/>` : `<stop offset="${offset}" class="pm-stop-${key}"/>`;
    const ringAttrs = colors ? `fill="none" stroke="${colors.ring}"` : 'class="pm-ring-line" fill="none"';
    const ring = `<ellipse ${ringAttrs} cx="256" cy="327" rx="216" ry="54" stroke-width="23"/>`;
    const bodyFill = `fill="url(#${grad})"`;
    return `<defs><linearGradient id="${grad}" x1="0" y1="0" x2=".95" y2="1">${stop(0, 'bodyHi')}${stop(0.56, 'body')}${stop(1, 'bodyLo')}</linearGradient>` +
      `<clipPath id="${clip}"><rect x="0" y="327" width="512" height="185"/></clipPath></defs>` +
      `<path class="pm-shadow" ${paint('ink')} opacity=".14" d="${ell(256, 462, 112, 12)}"/>` +
      `<g class="pm-char">` +
        `<g class="pm-ring pm-ring-back"><g transform="rotate(-12 256 327)">${ring}</g></g>` +
        `<g class="pm-foot pm-foot-l"><path ${paint('ink')} transform="rotate(-13 202 423)" d="${ell(202, 423, 24, 34)}"/></g>` +
        `<g class="pm-foot pm-foot-r"><path ${paint('ink')} transform="rotate(13 318 423)" d="${ell(318, 423, 24, 34)}"/></g>` +
        `<g class="pm-body">` +
          `<path ${bodyFill} d="M256 132C300 130 317 171 336 222C349 260 377 286 395 324C411 356 413 381 400 405C381 441 331 447 258 448C185 448 137 440 117 406C101 380 104 351 119 324C138 288 168 260 181 221C199 167 216 132 256 132Z"/>` +
          `<path ${paint('shade')} opacity=".2" d="M395 323C414 356 413 383 400 405C381 441 331 447 258 448C194 448 151 441 127 421C199 440 339 416 393 350Z"/>` +
          `<path ${paint('white')} opacity=".9" transform="rotate(-28 307 175)" d="${ell(307, 175, 12, 22)}${ell(324, 202, 6, 6)}"/>` +
        `</g>` +
        `<g class="pm-face">` +
          `<g class="pm-look">${SLOT_ORDER.map((s) => `<g class="pm-${s}">${partsMarkup(s, paint, filter)}</g>`).join('')}</g>` +
          `<g class="pm-cheeks">${partsMarkup('cheeks', paint, filter)}</g>` +
          `<g class="pm-mouth">${partsMarkup('mouth', paint, filter)}</g>` +
          `<g class="pm-sweat">${partsMarkup('sweat', paint, filter)}</g>` +
        `</g>` +
        `<g class="pm-stem">` +
          `<path ${paint('ink')} d="M256 142C255 120 254 108 244 89C238 78 237 65 246 64C262 63 270 84 268 99C266 111 260 131 263 143Z"/>` +
          `<g class="pm-leaf"><path ${paint('leaf')} d="M262 103C267 65 316 49 357 48C355 90 310 120 262 103Z"/>` +
          `<path ${paint('vein', 6)} d="M277 91Q306 73 336 65"/></g>` +
        `</g>` +
        `<g class="pm-ring pm-ring-front"><g transform="rotate(-12 256 327)"><g clip-path="url(#${clip})">${ring}</g></g></g>` +
      `</g>` +
      `<g class="pm-fx">${partsMarkup('fx', paint, filter)}</g>`;
  }

  function partsFor(emotionName) {
    const e = EMOTIONS[emotionName] || EMOTIONS.neutral;
    return { eyes: e.eyes || 'open', mouth: e.mouth || 'soft', brows: e.brows || '', fx: e.fx || '',
      cheeks: e.cheeks ? 'on' : '', sweat: e.sweat ? 'on' : '' };
  }

  /** アニメーションなしの単体SVG文字列。アイコン・トレイ・メニューバー画像の元に使う。 */
  function toStaticSVG({ emotion = 'neutral', colors, size = 512, fx = true } = {}) {
    const c = resolveColors(colors);
    const parts = partsFor(emotion);
    const filter = (slot, variant) => parts[slot] === variant && (fx || slot !== 'fx');
    const body = buildMarkup({ uid: `s${++uidSeq}`, paint: staticPaint(c), filter, colors: c });
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="${size}" height="${size}">${body}</svg>`;
  }

  // ---------------------------------------------------------------- live controller
  function create(host, options = {}) {
    if (!host || typeof document === 'undefined') throw new Error('PetitMascot.create needs a DOM host');
    const el = document.createElement('div');
    el.className = 'pm-root';
    el.dataset.action = 'idle';
    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('class', 'pm-svg');
    svg.setAttribute('viewBox', '0 0 512 512');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    svg.innerHTML = buildMarkup({ uid: `l${++uidSeq}`, paint: livePaint, filter: () => true });
    el.appendChild(svg);
    host.appendChild(el);

    const slots = Array.from(svg.querySelectorAll('[data-slot]'));
    let base = { emotion: 'neutral', action: 'idle', look: null };
    let overlay = null, overlayTimer = 0, stateName = 'idle', stateTimer = 0;
    let pointerLook = null;

    function render() {
      const cur = overlay || base;
      const emotion = EMOTIONS[cur.emotion] ? cur.emotion : 'neutral';
      const parts = partsFor(emotion);
      for (const node of slots) node.classList.toggle('pm-on', parts[node.dataset.slot] === node.dataset.variant);
      el.dataset.emotion = emotion;
      el.dataset.action = ACTIONS[cur.action] ? cur.action : 'idle';
      el.dataset.lid = EMOTIONS[emotion].lid || '';
      const look = pointerLook || cur.look || EMOTIONS[emotion].look || [0, 0];
      el.style.setProperty('--pm-look-x', String(look[0]));
      el.style.setProperty('--pm-look-y', String(look[1]));
    }

    function setColors(input) {
      const c = resolveColors(input);
      for (const [key, value] of Object.entries(c)) el.style.setProperty(`--pm-${key}`, value);
      return c;
    }
    function setSize(px) {
      const n = Math.round(Number(px));
      if (Number.isFinite(n) && n >= 24 && n <= 512) el.style.setProperty('--pm-size', `${n}px`);
    }

    const api = {
      el,
      /** 基準の表情（react 中は react が優先） */
      setEmotion(name) { if (EMOTIONS[name]) { base = { ...base, emotion: name }; render(); } },
      setAction(name) { if (ACTIONS[name]) { base = { ...base, action: name }; render(); } },
      /** 表情・動作を一時的に重ねる。ms 後に基準へ戻る。 */
      react(emotion, action, ms) {
        clearTimeout(overlayTimer);
        const duration = ms || ACTIONS[action]?.ms || 1200;
        overlay = { emotion: EMOTIONS[emotion] ? emotion : base.emotion, action: ACTIONS[action] ? action : base.action };
        // 同じ一回きりの動作を連続で鳴らせるよう、いったん外して付け直す。
        el.dataset.action = 'idle'; void el.offsetWidth;
        render();
        overlayTimer = setTimeout(() => { overlay = null; render(); }, duration);
        return duration;
      },
      clearReaction() { clearTimeout(overlayTimer); overlay = null; render(); },
      /** PETITの状態名（STATES）で表情と動作をまとめて切り替える。 */
      setState(name) {
        const s = STATES[name];
        if (!s) return null;
        clearTimeout(stateTimer);
        if (s.transient) {
          api.react(s.emotion, s.action, s.transient);
        } else {
          stateName = name;
          base = { emotion: s.emotion, action: s.action, look: s.look || null };
          if (overlay) api.clearReaction(); else render();
        }
        el.dataset.state = name;
        return s;
      },
      state: () => stateName,
      emotion: () => (overlay || base).emotion,
      action: () => (overlay || base).action,
      /** 視線 (-1..1)。null で表情の既定に戻す。 */
      look(x, y) {
        pointerLook = x == null ? null : [Math.max(-1, Math.min(1, x)), Math.max(-1, Math.min(1, y || 0))];
        render();
      },
      setFacing(dir) { el.dataset.facing = dir < 0 ? 'left' : 'right'; },
      setColors, setSize,
      setLite(on) { el.toggleAttribute('data-lite', Boolean(on)); },
      /** 'auto'（OSの動きを減らす設定に従う）| 'full'（常に動かす）| 'reduced'（止める） */
      setMotion(mode) { el.dataset.motion = MOTION_MODES.includes(mode) ? mode : 'auto'; },
      /** この表示で実際に動いてよいか（歩行など JS 側の動きの判定に使う） */
      motionAllowed() { return motionAllowed(el.dataset.motion); },
      pause(on) { el.toggleAttribute('data-paused', Boolean(on)); },
      destroy() { clearTimeout(overlayTimer); clearTimeout(stateTimer); el.remove(); },
    };

    setColors(options.colors || options.preset || 'pear');
    if (options.size) setSize(options.size);
    if (options.lite) api.setLite(true);
    api.setMotion(options.motion || 'auto');
    api.setState(options.state || 'idle');
    return api;
  }

  /**
   * 待機中の「生きている感じ」を出す軽量スケジューラー（setTimeout だけ、rAFなし）。
   * canAct() が false の間（会話中など）は何もしない。
   */
  const IDLE_LIFE = [
    { w: 5, emotion: 'curious', action: 'look' },
    { w: 3, emotion: 'happy', action: 'hop' },
    { w: 2, emotion: 'neutral', action: 'stretch' },
    { w: 2, emotion: 'happy', action: 'turn' },
    { w: 2, emotion: 'singing', action: 'dance', ms: 2200 },
    { w: 1, emotion: 'sleepy', action: 'idle', ms: 2600 },
    { w: 1, emotion: 'proud', action: 'wiggle' },
  ];
  function pickWeighted(list) {
    const total = list.reduce((sum, item) => sum + item.w, 0);
    let r = Math.random() * total;
    for (const item of list) { r -= item.w; if (r <= 0) return item; }
    return list[0];
  }
  function startIdleLife(mascot, { canAct = () => true, minMs = 7000, maxMs = 16000, behaviors = IDLE_LIFE } = {}) {
    let timer = 0, stopped = false;
    const schedule = () => {
      if (stopped) return;
      timer = setTimeout(() => {
        if (canAct()) { const b = pickWeighted(behaviors); mascot.react(b.emotion, b.action, b.ms); }
        schedule();
      }, minMs + Math.random() * (maxMs - minMs));
    };
    schedule();
    return () => { stopped = true; clearTimeout(timer); };
  }

  return Object.freeze({
    VERSION, PRESETS, DEFAULT_COLORS, PARTS, EMOTIONS, ACTIONS, STATES, IDLE_LIFE, MOTION_MODES,
    create, toStaticSVG, resolveColors, isHex, startIdleLife, pickWeighted, motionAllowed,
    /** 画面のどこからでも状態を伝える: PetitMascot.signal('thinking') */
    signal(state, detail = {}) {
      if (typeof document === 'undefined' || !STATES[state]) return;
      document.dispatchEvent(new CustomEvent('petit:mascot', { detail: { ...detail, state } }));
    },
  });
});
