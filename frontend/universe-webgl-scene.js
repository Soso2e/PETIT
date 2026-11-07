// PETIT Univ WebGL scene: real 3D planets, connections, camera, and crisp DOM labels.
(async () => {
  if (window.PetitUnivWebGL?.initialized) return;

  const THREE_VERSION = "0.185.1";
  const THREE_URL = `https://esm.sh/three@${THREE_VERSION}`;
  const RENDER_JOB = "webgl-scene";
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  const publicApi = {
    initialized: false,
    active: () => false,
    rebuild: () => { },
    reset: () => { },
    focusTask: () => false,
    selectTask: () => false,
    animateTaskExit: async () => false,
    zoomIn: () => { },
    zoomOut: () => { },
  };
  window.PetitUnivWebGL = publicApi;

  let THREE;
  try {
    THREE = await import(THREE_URL);
  } catch (error) {
    console.error("PETIT Univ WebGL dependencies failed to load", error);
    const viewport = document.querySelector(".univ-viewport");
    if (viewport && !viewport.querySelector(".univ-webgl-status")) {
      const status = document.createElement("p");
      status.className = "univ-webgl-status";
      status.textContent = "3Dエンジンを読み込めなかったため、従来表示を使用しています。";
      viewport.appendChild(status);
    }
    return;
  }

  const state = {
    viewport: null,
    map: null,
    stage: null,
    labelLayer: null,
    scene: null,
    sceneRoot: null,
    camera: null,
    renderer: null,
    controls: null,
    raycaster: new THREE.Raycaster(),
    pointer: new THREE.Vector2(),
    interactiveMeshes: [],
    entries: new Map(),
    labels: new Map(),
    animatedMeshes: [],
    visualTweens: new Map(),
    seenBodies: new Set(),
    selectedTaskId: null,
    cameraTween: null,
    // True while OrbitControls owns a drag/pinch/wheel gesture.
    cameraInteracting: false,
    // True once the user has moved the camera themselves. Automatic overview
    // fitting (resize, layout changes) must not undo that until an explicit reset.
    userCameraMoved: false,
    renderFrame: null,
    labelsNeedUpdate: true,
    lastRenderTime: 0,
    rebuildFrame: null,
    resizeObserver: null,
    unregisterRenderJob: null,
    ready: false,
  };

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const text = (value, fallback = "") => String(value ?? "").trim() || fallback;
  const escapeSelector = (value) => CSS.escape(String(value ?? ""));
  const panel = () => document.querySelector('[data-view-panel="universe"]');
  const isPanelActive = () => {
    const root = panel();
    return Boolean(root && !root.hidden && root.getAttribute("aria-hidden") !== "true");
  };

  const hashString = (value) => {
    let hash = 2166136261;
    for (const character of String(value || "PETIT")) {
      hash ^= character.charCodeAt(0);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  };

  const colorFor = (key, type = "parent") => {
    const hue = (hashString(key) % 360) / 360;
    const saturation = type === "child" ? 0.52 : 0.62;
    const lightness = type === "core" ? 0.62 : (type === "child" ? 0.63 : 0.52);
    return new THREE.Color().setHSL(hue, saturation, lightness);
  };

  const showStatus = (message) => {
    if (!state.viewport) return;
    let status = state.viewport.querySelector(".univ-webgl-status");
    if (!status) {
      status = document.createElement("p");
      status.className = "univ-webgl-status";
      state.viewport.appendChild(status);
    }
    status.textContent = message;
  };

  const clearStatus = () => state.viewport?.querySelector(".univ-webgl-status")?.remove();

  const ensureMount = () => {
    state.viewport = document.querySelector(".univ-viewport");
    state.map = document.querySelector("#constellation-grid");
    if (!state.viewport || !state.map) return false;

    state.stage = state.viewport.querySelector(":scope > .univ-webgl-stage");
    if (!state.stage) {
      state.stage = document.createElement("div");
      state.stage.className = "univ-webgl-stage";
      state.stage.setAttribute("aria-label", "Coreを中心とする3Dタスク空間");
      state.viewport.insertBefore(state.stage, state.viewport.firstChild);
    }

    state.labelLayer = state.viewport.querySelector(":scope > .univ-webgl-label-layer");
    if (!state.labelLayer) {
      state.labelLayer = document.createElement("div");
      state.labelLayer.className = "univ-webgl-label-layer";
      state.labelLayer.setAttribute("aria-label", "3Dタスクラベル");
      state.viewport.appendChild(state.labelLayer);
    }

    return true;
  };

  const createRenderer = () => {
    state.scene = new THREE.Scene();
    state.scene.fog = new THREE.FogExp2(0x02040d, 0.0115);

    state.camera = new THREE.PerspectiveCamera(46, 1, 0.1, 480);
    state.camera.position.set(0, 10, 34);

    state.renderer = new THREE.WebGLRenderer({
      antialias: true,
      // The renderer is the single source of truth for the Univ backdrop.
      alpha: false,
      powerPreference: "high-performance",
    });
    state.renderer.setClearColor(0x02040d, 1);
    state.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    state.renderer.outputColorSpace = THREE.SRGBColorSpace;
    state.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    state.renderer.toneMappingExposure = 1.08;
    state.renderer.domElement.tabIndex = -1;
    state.renderer.domElement.setAttribute("aria-label", "PETIT Univ 3Dビュー");
    state.renderer.domElement.classList.add("univ-webgl-canvas");
    state.stage.replaceChildren(state.renderer.domElement);

    // The single Canvas is the background scene and owns camera input. DOM
    // labels/UI remain overlays with pointer-events disabled where appropriate.
    state.inputSurface = state.renderer.domElement;
    // One finger / left drag rotates, two fingers pinch-zoom and pan,
    // right / middle / shift drag pans, wheel and trackpad pinch zoom to the cursor.
    state.controls = createCameraController(state.camera, state.inputSurface);
    state.controls.target.set(0, 0, 0);
    state.controls.minDistance = 8;
    state.controls.maxDistance = 72;
    state.controls.maxPolarAngle = Math.PI * 0.92;
    state.controls.minPolarAngle = Math.PI * 0.08;
    state.inputSurface.style.touchAction = "none";
    state.controls.update();
    state.controls.addEventListener("start", () => {
      state.cameraTween = null;
      state.cameraInteracting = true;
      state.userCameraMoved = true;
      requestRender();
    });
    state.controls.addEventListener("change", () => requestRender());
    state.controls.addEventListener("end", () => {
      state.cameraInteracting = false;
      requestRender();
    });

    state.scene.add(new THREE.HemisphereLight(0x9db5ff, 0x07091a, 1.15));
    const coreLight = new THREE.PointLight(0x9fb6ff, 120, 72, 1.7);
    coreLight.position.set(0, 0, 0);
    state.scene.add(coreLight);
    const rimLight = new THREE.DirectionalLight(0xbdd4ff, 2.1);
    rimLight.position.set(-12, 18, 20);
    state.scene.add(rimLight);

    createStarField();
    state.sceneRoot = new THREE.Group();
    state.sceneRoot.name = "PETIT_Universe_Root";
    state.scene.add(state.sceneRoot);

    state.resizeObserver = new ResizeObserver(resize);
    state.resizeObserver.observe(state.viewport);
    resize();
    installPointerInteraction();
  };

  // Camera input controller for the Univ canvas (replaces OrbitControls).
  // Gesture rules follow map / 3D-viewer practice (Google Maps, Sketchfab,
  // model-viewer, camera-controls):
  // - Only pointers that belong to the gesture move the camera. OrbitControls
  //   read every touch on the document, so a second finger that landed on the
  //   HUD made the rotation jump between both fingers ("ガガガ").
  // - A finger that lands anywhere while a gesture is active joins it.
  // - One finger / left mouse rotates; two fingers pinch-zoom and pan around
  //   their midpoint. After a multi-finger gesture the remaining finger does
  //   nothing until every finger is lifted, so the end of a pinch never turns
  //   into a sudden rotation.
  // - Every pointer-count change re-baselines, so the camera never jumps.
  // - The camera follows the finger with light smoothing, and a quick flick
  //   glides briefly. Stopping before release does not glide.
  const CAMERA_INPUT = {
    rotateSpeed: 0.92,
    dragSmoothMs: 28,
    settleSmoothMs: 70,
    // Glide distance is speed × decay; at most ~55° for the fastest flick.
    flingDecayMs: 140,
    flingMaxIdleMs: 70,
    flingMinSpeed: 0.0006,
    flingMaxSpeed: 0.007,
    tapSlop: { touch: 10, pen: 8, mouse: 5 },
    tapMaxMs: 550,
  };

  const createCameraController = (camera, element) => {
    const listeners = new Map();
    const emit = (type, detail = {}) => {
      (listeners.get(type) || []).forEach((listener) => listener({ type, ...detail }));
    };
    const target = new THREE.Vector3();
    const goalTarget = new THREE.Vector3();
    const spherical = new THREE.Spherical();
    const goal = new THREE.Spherical();
    const offset = new THREE.Vector3();
    const panRight = new THREE.Vector3();
    const panUp = new THREE.Vector3();
    const ndc = new THREE.Vector2();
    const rayCaster = new THREE.Raycaster();
    const viewNormal = new THREE.Vector3();
    const focusPlane = new THREE.Plane();
    const focusPoint = new THREE.Vector3();
    const pointers = new Map();
    const velocity = { theta: 0, phi: 0 };
    const samples = [];
    let mode = "none";
    let baseline = null;
    let animating = false;
    let lastTime = 0;
    let multiTouched = false;
    let tap = null;
    let suppressClickUntil = 0;
    let safariGestureScale = 1;

    const controller = {
      target,
      enabled: true,
      minDistance: 8,
      maxDistance: 72,
      minPolarAngle: 0.1,
      maxPolarAngle: Math.PI - 0.1,
      addEventListener(type, listener) {
        if (!listeners.has(type)) listeners.set(type, new Set());
        listeners.get(type).add(listener);
      },
      removeEventListener(type, listener) {
        listeners.get(type)?.delete(listener);
      },
      get interacting() {
        return pointers.size > 0;
      },
    };

    const clampGoal = () => {
      goal.phi = clamp(goal.phi, controller.minPolarAngle, controller.maxPolarAngle);
      goal.radius = clamp(goal.radius, controller.minDistance, controller.maxDistance);
    };

    const syncFromCamera = () => {
      offset.copy(camera.position).sub(target);
      spherical.setFromVector3(offset);
      goal.copy(spherical);
      goalTarget.copy(target);
    };

    const applyToCamera = () => {
      spherical.makeSafe();
      offset.setFromSpherical(spherical);
      camera.position.copy(target).add(offset);
      camera.lookAt(target);
    };

    const wake = () => {
      if (!animating) {
        animating = true;
        lastTime = 0;
      }
      emit("change");
    };

    const stop = () => {
      velocity.theta = 0;
      velocity.phi = 0;
      samples.length = 0;
      animating = false;
      syncFromCamera();
    };

    // Samples use the input event's own timestamp, so a busy main thread
    // (label layout, rebuilds) does not distort the release velocity.
    const rotate = (dx, dy, time = performance.now()) => {
      const height = element.clientHeight || 1;
      const dTheta = (-2 * Math.PI * dx / height) * CAMERA_INPUT.rotateSpeed;
      const dPhi = (-2 * Math.PI * dy / height) * CAMERA_INPUT.rotateSpeed;
      goal.theta += dTheta;
      goal.phi += dPhi;
      clampGoal();
      samples.push({ time, theta: dTheta, phi: dPhi });
      while (samples.length && time - samples[0].time > 100) samples.shift();
    };

    const pan = (dx, dy) => {
      const height = element.clientHeight || 1;
      const worldPerPixel = (2 * goal.radius * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) / height;
      camera.updateMatrix();
      panRight.setFromMatrixColumn(camera.matrix, 0);
      panUp.setFromMatrixColumn(camera.matrix, 1);
      goalTarget.addScaledVector(panRight, -dx * worldPerPixel).addScaledVector(panUp, dy * worldPerPixel);
    };

    // Zoom toward the point under the cursor / pinch midpoint, like OrbitControls.zoomToCursor.
    const dolly = (scale, clientX = null, clientY = null) => {
      if (!Number.isFinite(scale) || scale <= 0) return;
      const previous = goal.radius;
      goal.radius = clamp(previous * scale, controller.minDistance, controller.maxDistance);
      const applied = goal.radius / previous;
      if (clientX == null || Math.abs(applied - 1) < 1e-6) return;
      const rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      ndc.set(((clientX - rect.left) / rect.width) * 2 - 1, -(((clientY - rect.top) / rect.height) * 2 - 1));
      rayCaster.setFromCamera(ndc, camera);
      camera.getWorldDirection(viewNormal);
      focusPlane.setFromNormalAndCoplanarPoint(viewNormal, goalTarget);
      if (!rayCaster.ray.intersectPlane(focusPlane, focusPoint)) return;
      goalTarget.add(focusPoint.sub(goalTarget).multiplyScalar(1 - applied));
    };

    const centroid = () => {
      let x = 0;
      let y = 0;
      pointers.forEach((point) => { x += point.x; y += point.y; });
      return { x: x / pointers.size, y: y / pointers.size };
    };

    const spread = () => {
      if (pointers.size < 2) return 0;
      const [a, b] = pointers.values();
      return Math.hypot(a.x - b.x, a.y - b.y);
    };

    const rebaseline = () => {
      baseline = pointers.size ? { ...centroid(), spread: spread() } : null;
    };

    const modeFor = (event) => {
      if (event.pointerType === "mouse") {
        return event.button === 0 && !event.shiftKey && !event.ctrlKey && !event.metaKey ? "rotate" : "pan";
      }
      if (pointers.size >= 2) return "pinch";
      return multiTouched ? "locked" : "rotate";
    };

    const addPointer = (event) => {
      if (pointers.has(event.pointerId)) return;
      if (!pointers.size) {
        stop();
        multiTouched = false;
        tap = {
          pointerId: event.pointerId,
          pointerType: event.pointerType || "mouse",
          x: event.clientX,
          y: event.clientY,
          time: performance.now(),
          moved: false,
        };
        emit("start");
      }
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      try {
        element.setPointerCapture(event.pointerId);
      } catch (_error) {
        // Pointer already released; document-level listeners still filter by id.
      }
      if (pointers.size >= 2) {
        multiTouched = true;
        tap = null;
      }
      mode = modeFor(event);
      rebaseline();
      wake();
    };

    const onPointerDown = (event) => {
      if (!controller.enabled) return;
      if (event.pointerType === "mouse" && ![0, 1, 2].includes(event.button)) return;
      if (event.pointerType === "mouse" && pointers.size) return;
      addPointer(event);
    };

    // A finger that lands on an overlay (HUD, nav, labels) while a gesture is
    // already running joins the gesture instead of pressing that control.
    const onDocumentPointerDown = (event) => {
      if (!controller.enabled || !pointers.size || event.pointerType !== "touch") return;
      if (event.target === element || pointers.has(event.pointerId)) return;
      event.preventDefault();
      event.stopPropagation();
      suppressClickUntil = performance.now() + 800;
      addPointer(event);
    };

    const onDocumentClick = (event) => {
      if (performance.now() > suppressClickUntil) return;
      event.preventDefault();
      event.stopPropagation();
    };

    const onPointerMove = (event) => {
      const point = pointers.get(event.pointerId);
      if (!point) return;
      point.x = event.clientX;
      point.y = event.clientY;
      if (tap && tap.pointerId === event.pointerId) {
        const slop = CAMERA_INPUT.tapSlop[tap.pointerType] ?? CAMERA_INPUT.tapSlop.mouse;
        if (Math.hypot(event.clientX - tap.x, event.clientY - tap.y) > slop) tap.moved = true;
      }
      if (!baseline) rebaseline();
      const center = centroid();
      const dx = center.x - baseline.x;
      const dy = center.y - baseline.y;
      const currentSpread = spread();
      if (mode === "rotate") rotate(dx, dy, event.timeStamp);
      else if (mode === "pan") pan(dx, dy);
      else if (mode === "pinch") {
        if (baseline.spread > 0 && currentSpread > 0) dolly(baseline.spread / currentSpread, center.x, center.y);
        pan(dx, dy);
      }
      baseline = { ...center, spread: currentSpread };
      if (mode !== "locked") wake();
    };

    const startFling = (now) => {
      const last = samples[samples.length - 1];
      if (mode !== "rotate" || !last || now - last.time > CAMERA_INPUT.flingMaxIdleMs) return;
      const span = Math.max(16, now - samples[0].time);
      let theta = 0;
      let phi = 0;
      samples.forEach((sample) => { theta += sample.theta; phi += sample.phi; });
      const max = CAMERA_INPUT.flingMaxSpeed;
      velocity.theta = clamp(theta / span, -max, max);
      velocity.phi = clamp(phi / span, -max, max);
      if (Math.hypot(velocity.theta, velocity.phi) < CAMERA_INPUT.flingMinSpeed) {
        velocity.theta = 0;
        velocity.phi = 0;
      }
    };

    const onPointerEnd = (event) => {
      if (!pointers.has(event.pointerId)) return;
      pointers.delete(event.pointerId);
      try {
        if (element.hasPointerCapture?.(event.pointerId)) element.releasePointerCapture(event.pointerId);
      } catch (_error) {
        // Capture already released by the browser.
      }
      if (pointers.size) {
        mode = pointers.size >= 2 ? "pinch" : "locked";
        rebaseline();
        return;
      }
      if (event.type === "pointerup") startFling(event.timeStamp);
      const finishedTap = tap;
      tap = null;
      mode = "none";
      baseline = null;
      samples.length = 0;
      emit("end");
      wake();
      if (
        event.type === "pointerup"
        && finishedTap
        && finishedTap.pointerId === event.pointerId
        && !finishedTap.moved
        && !multiTouched
        && performance.now() - finishedTap.time <= CAMERA_INPUT.tapMaxMs
      ) {
        emit("tap", { clientX: event.clientX, clientY: event.clientY, pointerType: finishedTap.pointerType });
      }
    };

    const onWheel = (event) => {
      if (!controller.enabled) return;
      event.preventDefault();
      const unit = event.deltaMode === 1 ? 16 : (event.deltaMode === 2 ? 100 : 1);
      // Trackpad pinch arrives as ctrl+wheel with small deltas.
      const strength = event.ctrlKey ? 0.01 : 0.0015;
      if (!pointers.size) {
        stop();
        emit("start");
      }
      dolly(Math.exp(clamp(event.deltaY * unit, -240, 240) * strength), event.clientX, event.clientY);
      if (!pointers.size) emit("end");
      wake();
    };

    // Safari trackpad pinch (desktop) and iOS page-zoom gestures.
    const onGestureStart = (event) => {
      event.preventDefault();
      safariGestureScale = 1;
    };
    const onGestureChange = (event) => {
      event.preventDefault();
      if (pointers.size || !controller.enabled || !event.scale) return;
      stop();
      emit("start");
      dolly(safariGestureScale / event.scale, event.clientX, event.clientY);
      safariGestureScale = event.scale;
      emit("end");
      wake();
    };

    element.addEventListener("pointerdown", onPointerDown);
    element.addEventListener("wheel", onWheel, { passive: false });
    element.addEventListener("contextmenu", (event) => event.preventDefault());
    element.addEventListener("touchmove", (event) => event.preventDefault(), { passive: false });
    element.addEventListener("gesturestart", onGestureStart);
    element.addEventListener("gesturechange", onGestureChange);
    element.addEventListener("gestureend", (event) => event.preventDefault());
    document.addEventListener("pointerdown", onDocumentPointerDown, true);
    document.addEventListener("click", onDocumentClick, true);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerEnd);
    window.addEventListener("pointercancel", onPointerEnd);

    controller.stop = stop;
    controller.dollyBy = (scale) => {
      if (pointers.size) return;
      stop();
      dolly(scale);
      wake();
    };
    // Called every rendered frame. Returns true while the camera is still moving.
    controller.update = (time = performance.now()) => {
      if (!animating) {
        syncFromCamera();
        camera.lookAt(target);
        return false;
      }
      const dt = lastTime ? clamp(time - lastTime, 0, 64) : 16;
      lastTime = time;
      if (!pointers.size && (velocity.theta || velocity.phi)) {
        goal.theta += velocity.theta * dt;
        goal.phi += velocity.phi * dt;
        clampGoal();
        const decay = Math.exp(-dt / CAMERA_INPUT.flingDecayMs);
        velocity.theta *= decay;
        velocity.phi *= decay;
        if (Math.abs(velocity.theta) + Math.abs(velocity.phi) < 0.00002) {
          velocity.theta = 0;
          velocity.phi = 0;
        }
      }
      const smoothMs = pointers.size ? CAMERA_INPUT.dragSmoothMs : CAMERA_INPUT.settleSmoothMs;
      const k = reducedMotion.matches ? 1 : 1 - Math.exp(-dt / smoothMs);
      spherical.theta += (goal.theta - spherical.theta) * k;
      spherical.phi += (goal.phi - spherical.phi) * k;
      spherical.radius += (goal.radius - spherical.radius) * k;
      target.lerp(goalTarget, k);
      const settled = !pointers.size
        && !velocity.theta
        && !velocity.phi
        && Math.abs(goal.theta - spherical.theta) < 0.0002
        && Math.abs(goal.phi - spherical.phi) < 0.0002
        && Math.abs(goal.radius - spherical.radius) < 0.002
        && target.distanceToSquared(goalTarget) < 0.000004;
      if (settled) {
        spherical.copy(goal);
        target.copy(goalTarget);
        animating = false;
      }
      applyToCamera();
      emit("change");
      return animating;
    };

    syncFromCamera();
    return controller;
  };

  const seededRandom = (() => {
    let seed = 0x51f15e;
    return () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 0xffffffff;
    };
  })();

  const createStarField = () => {
    const isMobile = window.matchMedia("(max-width: 640px)").matches;
    const count = isMobile ? 1200 : 2400;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const sizes = new Float32Array(count);
    const spikes = new Float32Array(count);

    // Galaxy plane tilt angles (subtle rotation to create a 3D traversing band across the sky)
    const tiltX = 0.38;
    const tiltZ = 0.24;
    const cosX = Math.cos(tiltX);
    const sinX = Math.sin(tiltX);
    const cosZ = Math.cos(tiltZ);
    const sinZ = Math.sin(tiltZ);

    const diskCount = Math.floor(count * 0.65);

    for (let index = 0; index < count; index += 1) {
      let x0 = 0;
      let y0 = 0;
      let z0 = 0;

      // Color selection based on realistic stellar classifications + cosmic accents
      const colorRoll = seededRandom();
      let rCol = 1.0;
      let gCol = 1.0;
      let bCol = 1.0;

      if (colorRoll < 0.24) {
        // High-temperature blue / cyan stars (Rigel / Vega blue)
        rCol = 0.58 + seededRandom() * 0.12;
        gCol = 0.78 + seededRandom() * 0.12;
        bCol = 1.0;
      } else if (colorRoll < 0.56) {
        // Pure diamond white / crisp white (Sirius white)
        rCol = 0.94 + seededRandom() * 0.06;
        gCol = 0.96 + seededRandom() * 0.04;
        bCol = 1.0;
      } else if (colorRoll < 0.80) {
        // Warm golden / soft amber stars (Capella / Sun-like)
        rCol = 1.0;
        gCol = 0.86 + seededRandom() * 0.08;
        bCol = 0.62 + seededRandom() * 0.16;
      } else if (colorRoll < 0.93) {
        // Sunset ruby / salmon amber stars (Betelgeuse / red giants)
        rCol = 1.0;
        gCol = 0.56 + seededRandom() * 0.10;
        bCol = 0.40 + seededRandom() * 0.10;
      } else if (colorRoll < 0.97) {
        // Nebula violet / amethyst accent stars
        rCol = 0.88 + seededRandom() * 0.08;
        gCol = 0.62 + seededRandom() * 0.10;
        bCol = 1.0;
      } else {
        // Emerald mint / aurora teal accent stars
        rCol = 0.55 + seededRandom() * 0.10;
        gCol = 0.98;
        bCol = 0.86 + seededRandom() * 0.10;
      }

      // Star magnitude / size classes:
      // 82% faint delicate star dust, 14% medium prominent stars, 4% brilliant 1st-magnitude stars
      const magRoll = seededRandom();
      let starSize = 0.60;
      let spikeIntensity = 0.0;
      let brightness = 0.65 + seededRandom() * 0.35;

      if (magRoll > 0.96) {
        // Bright 1st magnitude star with subtle diffraction spikes
        starSize = 1.8 + seededRandom() * 0.7;
        spikeIntensity = 0.80 + seededRandom() * 0.35;
        brightness = 1.0;
      } else if (magRoll > 0.82) {
        // Medium prominent star
        starSize = 1.0 + seededRandom() * 0.35;
        spikeIntensity = seededRandom() > 0.6 ? 0.3 : 0.0;
        brightness = 0.85 + seededRandom() * 0.15;
      } else {
        // Faint delicate star dust
        starSize = 0.45 + seededRandom() * 0.35;
        spikeIntensity = 0.0;
      }

      if (index < diskCount) {
        // Galactic disk & spiral bands (far field: radius 140 to 280)
        const arm = index % 2;
        const radius = 140 + Math.pow(seededRandom(), 1.1) * 140;
        const twist = 0.016;
        const baseAngle = arm * Math.PI + radius * twist;
        const jitter = (seededRandom() + seededRandom() - 1.0) * (0.35 + radius * 0.001);
        const theta = baseAngle + jitter;

        x0 = radius * Math.cos(theta);
        z0 = radius * Math.sin(theta);
        y0 = (seededRandom() + seededRandom() - 1.0) * (5.5 + radius * 0.035);
      } else {
        // Spherical outer celestial dome (far field: radius 145 to 280)
        const radius = 145 + seededRandom() * 135;
        const theta = seededRandom() * Math.PI * 2;
        const phi = Math.acos((seededRandom() * 2) - 1);

        x0 = radius * Math.sin(phi) * Math.cos(theta);
        y0 = radius * Math.cos(phi);
        z0 = radius * Math.sin(phi) * Math.sin(theta);
      }

      // Apply galactic plane tilt
      const x1 = x0 * cosZ - y0 * sinZ;
      const y1 = x0 * sinZ + y0 * cosZ;
      const finalX = x1;
      const finalY = y1 * cosX - z0 * sinX;
      const finalZ = y1 * sinX + z0 * cosX;

      positions[index * 3] = finalX;
      positions[index * 3 + 1] = finalY;
      positions[index * 3 + 2] = finalZ;

      colors[index * 3] = rCol * brightness;
      colors[index * 3 + 1] = gCol * brightness;
      colors[index * 3 + 2] = bCol * brightness;

      sizes[index] = starSize;
      spikes[index] = spikeIntensity;
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geometry.setAttribute("aSize", new THREE.BufferAttribute(sizes, 1));
    geometry.setAttribute("aSpike", new THREE.BufferAttribute(spikes, 1));

    // Zero-texture procedural points material with additive blending and fog exemption
    const material = new THREE.PointsMaterial({
      size: 10,
      sizeAttenuation: true,
      transparent: true,
      opacity: 0.95,
      vertexColors: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      fog: false,
    });

    material.onBeforeCompile = (shader) => {
      shader.vertexShader = `
        attribute float aSize;
        attribute float aSpike;
        varying float vSpike;
        ${shader.vertexShader}
      `.replace(
        "void main() {",
        `void main() {
          vSpike = aSpike;`
      ).replace(
        "gl_PointSize = size;",
        "gl_PointSize = size * aSize;"
      );

      const fragmentInjectionTarget = shader.fragmentShader.includes("#include <premultiplied_alpha_fragment>")
        ? "#include <premultiplied_alpha_fragment>"
        : "#include <opaque_fragment>";

      shader.fragmentShader = `
        varying float vSpike;
        ${shader.fragmentShader}
      `.replace(
        "#include <clipping_planes_fragment>",
        `#include <clipping_planes_fragment>
        vec2 coord = gl_PointCoord - vec2(0.5);
        float dist = length(coord);
        if (dist > 0.5) discard;`
      ).replace(
        fragmentInjectionTarget,
        `${fragmentInjectionTarget}
        // Sharp luminous hot core
        float core = clamp(1.0 - dist * 4.6, 0.0, 1.0);
        core = core * core * core;

        // Soft outer corona glow
        float corona = clamp(1.0 - dist * 2.0, 0.0, 1.0);
        corona = pow(corona, 2.2);

        // Elegant cross-diffraction spike for prominent stars
        float spike = 0.0;
        if (vSpike > 0.05) {
          float spikeX = exp(-abs(coord.x) * 36.0) * exp(-abs(coord.y) * 4.8);
          float spikeY = exp(-abs(coord.y) * 36.0) * exp(-abs(coord.x) * 4.8);
          spike = max(spikeX, spikeY) * vSpike;
        }

        // Center saturates to pure brilliant white, outer corona keeps stellar tint
        vec3 starColor = mix(gl_FragColor.rgb, vec3(1.0), core * 0.85);
        float intensity = core * 1.15 + corona * 0.52 + spike * 0.72;

        gl_FragColor.rgb = starColor * intensity;
        gl_FragColor.a = clamp(intensity, 0.0, 1.0) * 0.95;`
      );
    };

    const stars = new THREE.Points(geometry, material);
    stars.name = "PETIT_Star_Field";
    state.scene.add(stars);
  };

  const resize = () => {
    if (!state.viewport || !state.renderer || !state.camera) return;
    const width = Math.max(1, state.viewport.clientWidth);
    const height = Math.max(1, state.viewport.clientHeight);
    state.renderer.setSize(width, height, false);
    state.camera.aspect = width / height;
    state.camera.updateProjectionMatrix();
    // Mobile browser chrome (address bar) and the area rail resize the viewport
    // during ordinary use. Refit only while the camera is still the automatic
    // overview; otherwise a resize mid-gesture snapped the view back.
    if (isPanelActive() && state.overviewRadius && !state.selectedTaskId) fitOverviewAutomatically();
    requestRender();
  };

  const disposeObject = (root) => {
    root?.traverse?.((object) => {
      object.geometry?.dispose?.();
      if (Array.isArray(object.material)) object.material.forEach((material) => material.dispose?.());
      else object.material?.dispose?.();
    });
  };

  const clearUniverse = () => {
    if (state.sceneRoot) {
      disposeObject(state.sceneRoot);
      state.scene.remove(state.sceneRoot);
    }
    state.sceneRoot = new THREE.Group();
    state.sceneRoot.name = "PETIT_Universe_Root";
    state.scene.add(state.sceneRoot);
    state.interactiveMeshes = [];
    state.entries.clear();
    state.animatedMeshes = [];
    state.visualTweens.clear();
    state.labels.forEach(({ element }) => element.remove());
    state.labels.clear();
  };

  const readModel = () => {
    if (!state.map) return [];
    return Array.from(state.map.querySelectorAll(":scope > .univ-task-system")).map((system, index) => {
      const planet = system.querySelector(":scope > .univ-task-planet");
      const project = text(system.dataset.univProject, "Project");
      const taskId = text(planet?.dataset.taskId || system.dataset.rootTaskId);
      const title = text(planet?.querySelector(".constellation-card__heading strong")?.textContent, project);
      const children = Array.from(system.querySelectorAll(":scope > .universe-task-list > .univ-satellite")).map((node, childIndex) => ({
        type: "child",
        taskId: text(node.dataset.taskId),
        title: text(node.querySelector(".universe-task__title")?.textContent, `Child ${childIndex + 1}`),
        domNode: node,
        index: childIndex,
      }));
      return {
        type: "parent",
        taskId,
        title,
        project,
        domNode: planet,
        system,
        index,
        variant: Number(system.dataset.univVariant || index % 5),
        children,
      };
    });
  };

  const createAtmosphere = (radius, color, opacity = 0.12) => {
    const geometry = new THREE.SphereGeometry(radius * 1.38, 32, 24);
    const material = new THREE.ShaderMaterial({
      uniforms: { glowColor: { value: color }, glowOpacity: { value: opacity } },
      vertexShader: `varying vec3 vNormal; varying vec3 vView;
        void main() { vec4 p = modelViewMatrix * vec4(position, 1.0);
          vNormal = normalize(normalMatrix * normal); vView = -p.xyz;
          gl_Position = projectionMatrix * p; }`,
      fragmentShader: `uniform vec3 glowColor; uniform float glowOpacity;
        varying vec3 vNormal; varying vec3 vView;
        void main() { float falloff = pow(abs(dot(normalize(vNormal), normalize(vView))), 3.0);
          gl_FragColor = vec4(glowColor, glowOpacity * falloff); }`,
      transparent: true,
      opacity,
      side: THREE.BackSide,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const atmosphere = new THREE.Mesh(geometry, material);
    atmosphere.name = "Atmosphere";
    return atmosphere;
  };

  const createPlanet = (entry, radius, type) => {
    const color = colorFor(entry.taskId || entry.title, type);
    const geometry = new THREE.SphereGeometry(radius, type === "child" ? 24 : 36, type === "child" ? 16 : 24);
    const emissive = color.clone().multiplyScalar(type === "core" ? 0.5 : 0.28);
    const material = new THREE.MeshStandardMaterial({
      color,
      emissive,
      emissiveIntensity: type === "core" ? 1.55 : (type === "child" ? 0.75 : 1.05),
      roughness: type === "child" ? 0.58 : 0.48,
      metalness: 0.12,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = `${type}:${entry.title}`;
    mesh.userData.entry = entry;
    mesh.userData.baseEmissiveIntensity = material.emissiveIntensity;
    mesh.userData.baseColor = color.clone();
    mesh.add(createAtmosphere(radius, color, type === "child" ? 0.08 : 0.12));
    const bodyKey = type === "core" ? "core" : `${type}:${entry.taskId}`;
    mesh.userData.entering = !state.seenBodies.has(bodyKey);
    state.seenBodies.add(bodyKey);
    mesh.userData.selected = Boolean(entry.taskId && entry.taskId === state.selectedTaskId);
    if (mesh.userData.selected) {
      mesh.scale.setScalar(1.14);
      mesh.material.emissiveIntensity = mesh.userData.baseEmissiveIntensity * 1.85;
    }
    state.interactiveMeshes.push(mesh);
    state.animatedMeshes.push({ mesh, speed: 0.00006 + ((hashString(entry.title) % 7) * 0.000008), type });
    entry.object = mesh;
    entry.color = color;
    if (entry.taskId) state.entries.set(entry.taskId, entry);
    return mesh;
  };

  const createConnection = (from, to, { child = false, active = false } = {}) => {
    const geometry = new THREE.BufferGeometry().setFromPoints([from, to]);
    const material = new THREE.LineBasicMaterial({
      color: active ? 0xdde7ff : (child ? 0x78d9c4 : 0x8faaff),
      transparent: true,
      opacity: active ? 0.86 : (child ? 0.46 : 0.34),
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const line = new THREE.Line(geometry, material);
    line.renderOrder = 1;
    return line;
  };

  const createOrbitRing = (radius, color) => {
    const geometry = new THREE.TorusGeometry(radius, 0.018, 6, 96);
    const material = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.16,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const ring = new THREE.Mesh(geometry, material);
    ring.rotation.x = Math.PI * 0.5;
    return ring;
  };

  const createLabel = (entry, object, type) => {
    const element = document.createElement("button");
    element.type = "button";
    element.className = `univ-webgl-label univ-webgl-label--${type}`;
    element.textContent = type === "core" ? "CORE" : entry.title;
    element.title = entry.title;
    element.style.setProperty("--label-accent", `#${entry.color.getHexString()}`);
    if (entry.taskId) element.dataset.taskId = entry.taskId;
    element.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      selectEntry(entry);
    });
    element.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectEntry(entry);
      }
    });
    state.labelLayer.appendChild(element);
    state.labels.set(entry.taskId || `__${type}__`, { element, object, entry, type });
  };

  const parentPosition = (index, total) => {
    const count = Math.max(1, total);
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));
    const normalized = (index + 0.5) / count;
    const y = 1 - (normalized * 2);
    const horizontal = Math.sqrt(Math.max(0, 1 - (y * y)));
    const theta = goldenAngle * index;
    const radius = count <= 4 ? 13.5 : (count <= 8 ? 16 : 18.5);
    return new THREE.Vector3(
      Math.cos(theta) * horizontal * radius,
      y * radius * 0.72,
      Math.sin(theta) * horizontal * radius,
    );
  };

  const childPosition = (index, total, seed) => {
    const angle = (-Math.PI / 2) + ((Math.PI * 2 * index) / Math.max(1, total));
    const radius = 3.8 + ((index % 2) * 0.8);
    const tilt = ((seed % 7) - 3) * 0.11;
    return new THREE.Vector3(
      Math.cos(angle) * radius,
      Math.sin(angle) * radius * 0.54,
      Math.sin(angle + tilt) * radius * 0.78,
    );
  };

  const rebuild = () => {
    if (!state.ready && !initialize()) return;
    if (!state.map?.isConnected) {
      state.map = document.querySelector("#constellation-grid");
      if (!state.map) return;
    }

    const previousSelection = state.selectedTaskId;
    const previousPositions = new Map();
    state.entries.forEach((entry, taskId) => {
      if (!entry?.object || !taskId) return;
      const position = new THREE.Vector3();
      entry.object.getWorldPosition(position);
      previousPositions.set(String(taskId), position);
    });
    clearUniverse();

    const coreEntry = {
      type: "core",
      taskId: "",
      title: "CORE",
      project: "PETIT",
      color: colorFor("PETIT CORE", "core"),
    };
    const core = createPlanet(coreEntry, 2.65, "core");
    core.position.set(0, 0, 0);
    state.sceneRoot.add(core);
    createLabel(coreEntry, core, "core");

    const models = readModel();
    models.forEach((model, index) => {
      const position = parentPosition(index, models.length);
      const group = new THREE.Group();
      group.name = `TaskSystem:${model.title}`;
      group.position.copy(position);
      state.sceneRoot.add(group);
      state.sceneRoot.add(createConnection(new THREE.Vector3(0, 0, 0), position));

      const parentMesh = createPlanet(model, 1.6, "parent");
      group.add(parentMesh);
      createLabel(model, parentMesh, "parent");

      if (model.children.length) {
        const ringRadius = 4.05 + (Math.min(model.children.length, 6) * 0.08);
        const ring = createOrbitRing(ringRadius, model.color);
        ring.rotation.z = ((hashString(model.title) % 13) - 6) * 0.035;
        group.add(ring);
      }

      model.children.forEach((child, childIndex) => {
        const localPosition = childPosition(childIndex, model.children.length, hashString(model.title));
        const childMesh = createPlanet(child, 0.62, "child");
        childMesh.position.copy(localPosition);
        group.add(childMesh);
        group.add(createConnection(new THREE.Vector3(0, 0, 0), localPosition, { child: true }));
        createLabel(child, childMesh, "child");
      });
    });

    state.selectedTaskId = previousSelection && state.entries.has(previousSelection) ? previousSelection : null;
    const layoutKey = models.map(model => `${model.taskId}:${model.children.length}`).join("|");
    const fitOverview = layoutKey !== state.overviewLayoutKey;
    state.overviewLayoutKey = layoutKey;
    state.sceneRoot.updateMatrixWorld(true);
    state.overviewPoints = [...state.labels.values()].map(({ object }) => ({
      position: object.getWorldPosition(new THREE.Vector3()),
      radius: (object.geometry.parameters.radius || 1) * 1.7,
    }));
    state.overviewRadius = 1; // Marks a loaded layout for responsive overview fitting.
    updateSelection();

    // Preserve spatial continuity across task mutations. Rebuilt bodies start
    // at their previous world-space position and only render while interpolating
    // toward the new layout. New bodies keep the existing entrance animation.
    if (!reducedMotion.matches && document.documentElement.dataset.petitPerformance !== "lite") {
      state.entries.forEach((entry, taskId) => {
        const previousWorld = previousPositions.get(String(taskId));
        const object = entry?.object;
        if (!previousWorld || !object?.parent) return;
        object.parent.updateMatrixWorld(true);
        const targetPosition = object.position.clone();
        const fromPosition = object.parent.worldToLocal(previousWorld.clone());
        if (fromPosition.distanceToSquared(targetPosition) < 0.0001) return;
        object.position.copy(fromPosition);
        const current = state.visualTweens.get(object) || {};
        state.visualTweens.set(object, {
          ...current,
          startedAt: performance.now(),
          duration: 520,
          fromPosition,
          toPosition: targetPosition,
        });
      });
    }
    clearStatus();
    document.body.classList.add("petit-univ-webgl-ready");
    if (fitOverview && !state.selectedTaskId) fitOverviewAutomatically();
    window.dispatchEvent(new CustomEvent("petit:univ-webgl-rendered", {
      detail: { systems: models.length, tasks: state.entries.size },
    }));
    requestRender();
  };

  const requestRebuild = (reason = "unspecified") => {
    const scheduler = window.PetitUniverseRenderScheduler;
    if (scheduler?.initialized) {
      if (!state.unregisterRenderJob) {
        state.unregisterRenderJob = scheduler.register(RENDER_JOB, rebuild);
      }
      scheduler.request(RENDER_JOB, reason);
      return;
    }
    if (state.rebuildFrame != null) return;
    state.rebuildFrame = window.requestAnimationFrame(() => {
      state.rebuildFrame = null;
      rebuild();
    });
  };

  const connectScheduler = () => {
    const scheduler = window.PetitUniverseRenderScheduler;
    if (!scheduler?.initialized || state.unregisterRenderJob) return;
    state.unregisterRenderJob = scheduler.register(RENDER_JOB, rebuild);
  };

  const updateSelection = () => {
    const workingTaskId = String(window.PetitUniverse?.workingTask?.() || "");
    state.animatedMeshes.forEach(({ mesh }, index) => {
      const selected = Boolean(mesh.userData.entry.taskId && mesh.userData.entry.taskId === state.selectedTaskId);
      const working = Boolean(workingTaskId && mesh.userData.entry.taskId === workingTaskId);
      const entering = mesh.userData.entering;
      const toScale = working ? 1.32 : selected ? 1.14 : 1;
      const dimmed = Boolean(workingTaskId && !working && !selected && mesh.userData.entry.taskId);
      const toGlow = mesh.userData.baseEmissiveIntensity * (working ? 4.6 : selected ? 1.85 : dimmed ? .45 : 1);
      // Retarget from the current frame when selections change rapidly.
      if (entering || mesh.userData.selected !== selected || mesh.userData.working !== working || mesh.userData.dimmed !== dimmed) {
        const atmosphere = mesh.getObjectByName("Atmosphere");
        state.visualTweens.set(mesh, {
          startedAt: performance.now() + (entering ? Math.min(index * 35, 175) : 0),
          duration: entering ? 640 : 420,
          fromScale: entering ? .72 : mesh.scale.x,
          toScale,
          fromGlow: entering ? 0 : mesh.material.emissiveIntensity,
          toGlow,
          pulse: entering || selected || working,
          atmosphere,
          fromOpacity: entering ? 0 : atmosphere.material.opacity,
          toOpacity: working ? 1.5 : selected ? .38 : dimmed ? .035 : mesh.userData.entry.type === "child" ? .08 : .12,
          fromBrightness: mesh.userData.brightness ?? 1,
          toBrightness: dimmed ? .5 : 1,
        });
        if (entering) {
          mesh.scale.setScalar(.72);
          mesh.material.emissiveIntensity = 0;
        }
      }
      mesh.userData.entering = false;
      mesh.userData.selected = selected;
      mesh.userData.working = working;
      mesh.userData.dimmed = dimmed;
    });
    state.labels.forEach(({ element, entry }) => {
      element.classList.toggle("is-selected", Boolean(entry.taskId && entry.taskId === state.selectedTaskId));
      element.classList.toggle("is-working", Boolean(workingTaskId && entry.taskId === workingTaskId));
    });
    requestRender({ updateLabels: true });
  };

  const startCameraTween = (position, target, duration = 720) => {
    state.controls.stop();
    state.cameraTween = {
      startedAt: performance.now(),
      duration: reducedMotion.matches ? 1 : duration,
      fromPosition: state.camera.position.clone(),
      toPosition: position.clone(),
      fromTarget: state.controls.target.clone(),
      toTarget: target.clone(),
    };
    requestRender();
  };

  const focusEntry = (entry) => {
    if (!entry?.object || !state.camera || !state.controls) return false;
    const target = new THREE.Vector3();
    state.scene.fog.density = .0115;
    entry.object.getWorldPosition(target);
    const direction = state.camera.position.clone().sub(state.controls.target);
    if (direction.lengthSq() < 0.001) direction.set(0, 0.2, 1);
    direction.normalize();
    const distance = entry.type === "child" ? 7.5 : (entry.type === "parent" ? 10.5 : 32);
    const position = target.clone().add(direction.multiplyScalar(distance));
    position.y += entry.type === "child" ? 1.1 : (entry.type === "parent" ? 1.8 : 8);
    startCameraTween(position, target, entry.type === "child" ? 620 : 760);
    return true;
  };

  const resetCamera = () => {
    state.userCameraMoved = false;
    state.selectedTaskId = null;
    updateSelection();
    document.body.classList.remove("petit-univ-manage-open");
    const vertical = THREE.MathUtils.degToRad(state.camera.fov / 2);
    const horizontal = Math.atan(Math.tan(vertical) * state.camera.aspect);
    const direction = new THREE.Vector3(0, .25, 1).normalize();
    const up = new THREE.Vector3(0, direction.z, -direction.y);
    // Fit body positions, reserving room for the work bar/HUD and labels.
    const distance = Math.max(32, ...(state.overviewPoints || []).map(({ position, radius }) =>
      direction.dot(position) + Math.max(Math.abs(position.x) / (Math.tan(horizontal) * .84), Math.abs(up.dot(position)) / (Math.tan(vertical) * .56)) + radius / Math.sin(Math.min(vertical, horizontal))
    ));
    state.controls.maxDistance = Math.max(72, distance * 1.8);
    state.camera.far = Math.max(240, distance * 2); state.camera.updateProjectionMatrix();
    state.scene.fog.density = Math.min(.0115, .6 / distance);
    startCameraTween(direction.multiplyScalar(distance), new THREE.Vector3(0, 0, 0), 760);
    window.PetitUnivSpace?.reset?.();
  };

  // Automatic (non-user) overview fit. Skipped while the user is operating the
  // camera or has moved it, so their rotation/zoom is never discarded.
  const fitOverviewAutomatically = () => {
    if (state.cameraInteracting || state.userCameraMoved) return false;
    resetCamera();
    return true;
  };

  const openDetail = () => {
    if (!state.selectedTaskId) return;
    window.requestAnimationFrame(() => {
      document.body.classList.add("petit-univ-manage-open");
      document.querySelector("#detail-panel")?.focus?.({ preventScroll: true });
    });
  };

  const selectEntry = (entry) => {
    if (!entry) return false;
    if (entry.type === "core") {
      resetCamera();
      return true;
    }
    if (!entry.taskId) return false;

    const isAlreadySelected = String(state.selectedTaskId) === String(entry.taskId);
    state.selectedTaskId = entry.taskId;
    updateSelection();

    // Keep selection/detail state synchronized without re-entering the hidden
    // DOM click path, which rebuilds the Universe and WebGL scene.
    const selectedByUniverse = window.PetitUniverse?.selectTask?.(entry.taskId);
    window.PetitUnivSpace?.focusTask?.(entry.taskId);
    if (!selectedByUniverse) {
      const domNode = entry.domNode?.isConnected
        ? entry.domNode
        : state.map?.querySelector(`[data-task-id="${escapeSelector(entry.taskId)}"]`);
      domNode?.click?.();
    }
    focusEntry(entry);
    if (isAlreadySelected) {
      openDetail();
    }
    return true;
  };

  const zoomBy = (factor) => {
    if (!state.camera || !state.controls) return;
    state.cameraTween = null;
    state.userCameraMoved = true;
    state.controls.dollyBy(factor);
    requestRender();
  };

  const raycastAt = (clientX, clientY) => {
    if (!state.renderer || !state.camera) return null;
    const rect = state.renderer.domElement.getBoundingClientRect();
    state.pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    state.pointer.y = -(((clientY - rect.top) / rect.height) * 2 - 1);
    state.raycaster.setFromCamera(state.pointer, state.camera);
    return state.raycaster.intersectObjects(state.interactiveMeshes, false)[0]?.object || null;
  };

  // Labels are hit-tested by their visible text only. The pill around the text
  // is nearly transparent on the dark sky, so a tap there read as "empty space"
  // yet selected the nearby planet. Faded (distant) labels are not targets.
  const LABEL_MIN_HIT_OPACITY = 0.5;
  const labelTextRange = document.createRange();
  const labelHitRect = (element, padding) => {
    const box = element.getBoundingClientRect();
    let left = box.left;
    let right = box.right;
    let top = box.top;
    let bottom = box.bottom;
    const textNode = element.firstChild;
    if (textNode?.nodeType === Node.TEXT_NODE) {
      labelTextRange.selectNodeContents(textNode);
      const textBox = labelTextRange.getBoundingClientRect();
      if (textBox.width && textBox.height) {
        left = Math.max(box.left, textBox.left);
        right = Math.min(box.right, textBox.right);
        top = Math.max(box.top, textBox.top);
        bottom = Math.min(box.bottom, textBox.bottom);
      }
    }
    return { left: left - padding, right: right + padding, top: top - padding, bottom: bottom + padding };
  };

  const findLabelAt = (clientX, clientY, pointerType = "mouse") => {
    let closestEntry = null;
    let closestDistSq = Infinity;
    const cameraPos = state.camera?.position;
    const padding = pointerType === "touch" ? 6 : 2;

    for (const { element, entry, object } of state.labels.values()) {
      if (!element || element.hidden || element.style.display === "none") continue;
      const opacity = Number.parseFloat(element.style.opacity || "1");
      if (!element.classList.contains("is-selected") && opacity < LABEL_MIN_HIT_OPACITY) continue;
      const rect = labelHitRect(element, padding);
      if (clientX < rect.left || clientX > rect.right || clientY < rect.top || clientY > rect.bottom) continue;
      if (!object || !cameraPos) return entry;
      const distSq = object.position.distanceToSquared(cameraPos);
      if (distSq < closestDistSq) {
        closestDistSq = distSq;
        closestEntry = entry;
      }
    }
    return closestEntry;
  };

  // Small satellites get a minimum touch radius around their projected center,
  // but only up to that radius: nothing farther away is ever picked.
  const TOUCH_MIN_TARGET_RADIUS = 16;
  const projectedCenter = new THREE.Vector3();
  const projectedEdge = new THREE.Vector3();
  const findSmallBodyNear = (clientX, clientY) => {
    if (!state.renderer || !state.camera) return null;
    const rect = state.renderer.domElement.getBoundingClientRect();
    let best = null;
    let bestDistance = Infinity;
    for (const mesh of state.interactiveMeshes) {
      if (!mesh.visible || !mesh.userData?.entry) continue;
      mesh.getWorldPosition(projectedCenter);
      const radius = (mesh.geometry?.parameters?.radius || 1) * mesh.scale.x;
      projectedEdge.copy(projectedCenter).addScaledVector(state.camera.up, radius);
      projectedCenter.project(state.camera);
      projectedEdge.project(state.camera);
      if (projectedCenter.z < -1 || projectedCenter.z > 1) continue;
      const x = rect.left + ((projectedCenter.x + 1) / 2) * rect.width;
      const y = rect.top + ((1 - projectedCenter.y) / 2) * rect.height;
      const screenRadius = Math.hypot((projectedEdge.x - projectedCenter.x) * rect.width / 2, (projectedEdge.y - projectedCenter.y) * rect.height / 2);
      if (screenRadius >= TOUCH_MIN_TARGET_RADIUS) continue;
      const distance = Math.hypot(clientX - x, clientY - y);
      if (distance <= TOUCH_MIN_TARGET_RADIUS && distance < bestDistance) {
        best = mesh;
        bestDistance = distance;
      }
    }
    return best;
  };

  const pickEntryAt = (clientX, clientY, pointerType = "mouse") => {
    const labelEntry = findLabelAt(clientX, clientY, pointerType);
    if (labelEntry) return labelEntry;
    const object = raycastAt(clientX, clientY)
      || (pointerType === "touch" ? findSmallBodyNear(clientX, clientY) : null);
    return object?.userData?.entry || null;
  };

  const installPointerInteraction = () => {
    const input = state.inputSurface;

    input.addEventListener("pointerdown", (event) => {
      // Keep pointer events owned by WebGL canvas instead of bubbling to CSS fallback.
      event.stopPropagation();
    });
    // Tap = one pointer, released within the slop and time limit, with no
    // second finger at any point. The camera controller decides; anything
    // else is a camera gesture and never selects a planet.
    state.controls.addEventListener("tap", ({ clientX, clientY, pointerType }) => {
      const entry = pickEntryAt(clientX, clientY, pointerType);
      if (entry) selectEntry(entry);
    });
    input.addEventListener("pointermove", (event) => {
      if (event.pointerType !== "mouse" || state.controls.interacting) return;
      const labelEntry = findLabelAt(event.clientX, event.clientY, "mouse");
      const object = labelEntry ? null : raycastAt(event.clientX, event.clientY);
      input.style.cursor = (labelEntry || object) ? "pointer" : "grab";
      for (const { element, entry } of state.labels.values()) {
        if (!element) continue;
        element.classList.toggle("is-hovered", Boolean(labelEntry && entry === labelEntry));
      }
    }, { passive: true });
    input.addEventListener("wheel", (event) => {
      // Keep the wheel owned by the camera controller instead of the hidden CSS camera.
      event.stopPropagation();
    }, { passive: true });
    input.addEventListener("auxclick", (event) => { if (event.button === 1) event.preventDefault(); });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape" || event.key === "0") resetCamera();
      if (event.key === "+" || event.key === "=") zoomBy(0.84);
      if (event.key === "-") zoomBy(1.18);
    });
  };

  const updateCameraTween = (time) => {
    const tween = state.cameraTween;
    if (!tween) return false;
    // Never let a tween fight an active drag/pinch.
    if (state.cameraInteracting) {
      state.cameraTween = null;
      return false;
    }
    const progress = reducedMotion.matches ? 1 : clamp((time - tween.startedAt) / tween.duration, 0, 1);
    const eased = progress < 0.5
      ? 4 * progress * progress * progress
      : 1 - Math.pow(-2 * progress + 2, 3) / 2;
    state.camera.position.lerpVectors(tween.fromPosition, tween.toPosition, eased);
    state.controls.target.lerpVectors(tween.fromTarget, tween.toTarget, eased);
    if (progress >= 1) state.cameraTween = null;
    return state.cameraTween != null;
  };

  const updateVisualTweens = (time) => {
    const instant = reducedMotion.matches || document.documentElement.dataset.petitPerformance === "lite";
    state.visualTweens.forEach((tween, mesh) => {
      const progress = instant ? 1 : clamp((time - tween.startedAt) / tween.duration, 0, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      if (Number.isFinite(tween.fromScale) && Number.isFinite(tween.toScale)) {
        mesh.scale.setScalar(tween.fromScale + (tween.toScale - tween.fromScale) * eased);
      }
      if (Number.isFinite(tween.fromGlow) && Number.isFinite(tween.toGlow)) {
        mesh.material.emissiveIntensity = tween.fromGlow + (tween.toGlow - tween.fromGlow) * eased;
      }
      if (Number.isFinite(tween.fromBrightness)) {
        mesh.userData.brightness = tween.fromBrightness + (tween.toBrightness - tween.fromBrightness) * eased;
        mesh.material.color.copy(mesh.userData.baseColor).multiplyScalar(mesh.userData.brightness);
      }
      if (tween.fromPosition && tween.toPosition) {
        mesh.position.lerpVectors(tween.fromPosition, tween.toPosition, eased);
        state.labelsNeedUpdate = true;
      }
      const pulse = tween.pulse && !instant ? Math.sin(progress * Math.PI) : 0;
      if (tween.atmosphere) {
        tween.atmosphere.scale.setScalar(1 + pulse * .22);
        const opacity = Number.isFinite(tween.fromOpacity)
          ? tween.fromOpacity + (tween.toOpacity - tween.fromOpacity) * eased
          : (tween.baseOpacity ?? tween.atmosphere.material.opacity);
        tween.atmosphere.material.opacity = opacity + pulse * .14;
        tween.atmosphere.material.uniforms.glowOpacity.value = tween.atmosphere.material.opacity;
      }
      if (progress >= 1) {
        state.visualTweens.delete(mesh);
        tween.onComplete?.();
      }
    });
    return state.visualTweens.size > 0;
  };

  const labelForward = new THREE.Vector3();
  const labelWorld = new THREE.Vector3();
  const labelToObject = new THREE.Vector3();
  const labelProjected = new THREE.Vector3();

  const updateLabels = () => {
    if (!state.camera || !state.viewport) return;
    const width = state.viewport.clientWidth;
    const height = state.viewport.clientHeight;
    state.camera.getWorldDirection(labelForward);

    const occupied = [];
    const priority = ({ entry, type }) => entry.taskId === state.selectedTaskId ? 0 : type === "child" ? 3 : type === "parent" ? 1 : 2;
    [...state.labels.values()].sort((a, b) => priority(a) - priority(b)).forEach(({ element, object, entry, type }) => {
      if (!object?.visible) {
        element.hidden = true;
        return;
      }
      object.getWorldPosition(labelWorld);
      labelToObject.copy(labelWorld).sub(state.camera.position);
      const inFront = labelForward.dot(labelToObject) > 0;
      labelProjected.copy(labelWorld).project(state.camera);
      const withinFrustum = labelProjected.z > -1 && labelProjected.z < 1
        && labelProjected.x > -1.18 && labelProjected.x < 1.18
        && labelProjected.y > -1.18 && labelProjected.y < 1.18;
      const distance = state.camera.position.distanceTo(labelWorld);
      const maxDistance = type === "child" ? 38 : Math.max(82, state.controls.maxDistance);
      const selected = Boolean(entry.taskId && entry.taskId === state.selectedTaskId);
      const working = Boolean(entry.taskId && entry.taskId === String(window.PetitUniverse?.workingTask?.() || ""));
      const visible = inFront && withinFrustum && (selected || working || distance < maxDistance);
      element.hidden = !visible;
      if (!visible) return;
      element.style.left = `${((labelProjected.x * 0.5) + 0.5) * width}px`;
      element.style.top = `${((-labelProjected.y * 0.5) + 0.5) * height}px`;
      const fadeStart = maxDistance * 0.6;
      const opacity = selected || working ? 1 : clamp(1 - ((distance - fadeStart) / (maxDistance - fadeStart)), 0.22, 1);
      element.style.opacity = opacity.toFixed(3);
      element.style.zIndex = String(Math.round((1 - labelProjected.z) * 500));
      const rect = element.getBoundingClientRect();
      const overlap = occupied.some(other => rect.left < other.right + 6 && rect.right > other.left - 6 && rect.top < other.bottom + 6 && rect.bottom > other.top - 6);
      if (type === "child" && !selected && !working && overlap) element.hidden = true;
      else occupied.push(rect);
    });
  };

  function requestRender({ updateLabels: shouldUpdateLabels = true } = {}) {
    if (shouldUpdateLabels) state.labelsNeedUpdate = true;
    if (state.renderFrame != null) return;
    state.renderFrame = window.requestAnimationFrame(render);
  }

  function render(time) {
    state.renderFrame = null;
    if (!state.ready || !isPanelActive() || document.hidden) return;
    const cameraMoving = updateCameraTween(time);
    const bodiesMoving = updateVisualTweens(time);
    const controlsMoving = state.controls.update(time);
    const tweening = cameraMoving || bodiesMoving || controlsMoving;
    const liteMode = document.documentElement.dataset.petitPerformance === "lite";
    if (!liteMode && !reducedMotion.matches) {
      const delta = state.lastRenderTime ? Math.min(32, time - state.lastRenderTime) : 0;
      state.animatedMeshes.forEach(({ mesh, speed, type }) => {
        mesh.rotation.y += delta * speed;
        if (type === "child") mesh.rotation.x = Math.sin(mesh.rotation.y * 0.7) * 0.08;
      });
    }
    state.lastRenderTime = time;
    if (state.labelsNeedUpdate) {
      state.labelsNeedUpdate = false;
      updateLabels();
    }
    state.renderer.render(state.scene, state.camera);
    if (tweening) requestRender();
  }

  const initialize = () => {
    if (state.ready) return true;
    if (!ensureMount()) return false;
    try {
      createRenderer();
    } catch (error) {
      console.error("PETIT Univ WebGL initialization failed", error);
      showStatus("WebGLを初期化できなかったため、従来表示を使用しています。");
      return false;
    }

    connectScheduler();
    state.ready = true;
    publicApi.initialized = true;
    publicApi.active = () => state.ready && document.body.classList.contains("petit-univ-webgl-ready");
    publicApi.rebuild = () => requestRebuild("public-api");
    publicApi.reset = resetCamera;
    publicApi.focusTask = (taskId) => {
      const entry = state.entries.get(String(taskId || ""));
      return entry ? focusEntry(entry) : false;
    };
    publicApi.selectTask = (taskId) => {
      const entry = state.entries.get(String(taskId || ""));
      return entry ? selectEntry(entry) : false;
    };
    publicApi.animateTaskExit = (taskId) => {
      const entry = state.entries.get(String(taskId || ""));
      const mesh = entry?.object;
      if (!mesh) return Promise.resolve(false);
      const label = state.labels.get(String(taskId || ""))?.element;
      if (label) label.hidden = true;
      state.interactiveMeshes = state.interactiveMeshes.filter((candidate) => candidate !== mesh);
      const instant = reducedMotion.matches || document.documentElement.dataset.petitPerformance === "lite";
      if (instant) {
        mesh.visible = false;
        requestRender();
        return Promise.resolve(true);
      }
      return new Promise((resolve) => {
        const atmosphere = mesh.getObjectByName("Atmosphere");
        state.visualTweens.set(mesh, {
          startedAt: performance.now(),
          duration: 280,
          fromScale: mesh.scale.x,
          toScale: 0.06,
          fromGlow: mesh.material.emissiveIntensity,
          toGlow: 0,
          pulse: true,
          atmosphere,
          baseOpacity: entry.type === "child" ? .08 : .12,
          onComplete: () => {
            mesh.visible = false;
            resolve(true);
          },
        });
        requestRender();
      });
    };
    publicApi.zoomIn = () => zoomBy(0.84);
    publicApi.zoomOut = () => zoomBy(1.18);

    requestRebuild("initialize");
    return true;
  };

  window.addEventListener("petit:render-scheduler-ready", () => {
    connectScheduler();
    requestRebuild("scheduler-ready");
  });
  window.addEventListener("petit:universe-rendered", () => requestRebuild("universe-rendered"));
  document.addEventListener("petit:working-task", () => { if (state.ready) updateSelection(); });
  document.addEventListener("petit:tasks-updated", () => requestRebuild("tasks-updated"));
  window.addEventListener("petit:panel-change", () => {
    resize();
    requestRebuild("panel-change");
  });
  window.addEventListener("petit:performance-change", () => requestRender({ updateLabels: false }));
  reducedMotion.addEventListener("change", () => requestRender());
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) requestRender();
  });
  window.addEventListener("petit:area-change", () => {
    resize();
    requestRebuild("area-change");
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      initialize();
      window.setTimeout(() => requestRebuild("dom-ready"), 250);
    }, { once: true });
  } else {
    initialize();
    window.setTimeout(() => requestRebuild("module-ready"), 250);
  }
})();
