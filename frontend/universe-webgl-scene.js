// PETIT Univ WebGL scene: real 3D planets, connections, camera, and crisp DOM labels.
(async () => {
  if (window.PetitUnivWebGL?.initialized) return;

  const THREE_VERSION = "0.185.1";
  const THREE_URL = `https://esm.sh/three@${THREE_VERSION}`;
  const ORBIT_CONTROLS_URL = `https://esm.sh/three@${THREE_VERSION}/examples/jsm/controls/OrbitControls.js`;
  const RENDER_JOB = "webgl-scene";
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  const publicApi = {
    initialized: false,
    active: () => false,
    rebuild: () => {},
    reset: () => {},
    focusTask: () => false,
    selectTask: () => false,
    zoomIn: () => {},
    zoomOut: () => {},
  };
  window.PetitUnivWebGL = publicApi;

  let THREE;
  let OrbitControls;
  try {
    [THREE, { OrbitControls }] = await Promise.all([
      import(THREE_URL),
      import(ORBIT_CONTROLS_URL),
    ]);
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
    selectedTaskId: null,
    pointerDown: null,
    cameraTween: null,
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

    state.camera = new THREE.PerspectiveCamera(46, 1, 0.1, 240);
    state.camera.position.set(0, 10, 34);

    state.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    state.renderer.setClearColor(0x000000, 0);
    state.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    state.renderer.outputColorSpace = THREE.SRGBColorSpace;
    state.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    state.renderer.toneMappingExposure = 1.08;
    state.renderer.domElement.tabIndex = 0;
    state.renderer.domElement.setAttribute("aria-label", "PETIT Univ 3Dビュー");
    state.stage.replaceChildren(state.renderer.domElement);

    state.controls = new OrbitControls(state.camera, state.renderer.domElement);
    state.controls.target.set(0, 0, 0);
    state.controls.enableDamping = !reducedMotion.matches;
    state.controls.dampingFactor = 0.065;
    state.controls.enablePan = true;
    state.controls.screenSpacePanning = true;
    state.controls.minDistance = 8;
    state.controls.maxDistance = 72;
    state.controls.maxPolarAngle = Math.PI * 0.92;
    state.controls.minPolarAngle = Math.PI * 0.08;
    state.controls.zoomToCursor = true;
    state.controls.update();
    state.controls.addEventListener("start", () => { state.cameraTween = null; });

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
    state.renderer.setAnimationLoop(animate);
  };

  const seededRandom = (() => {
    let seed = 0x51f15e;
    return () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 0xffffffff;
    };
  })();

  const createStarField = () => {
    const count = window.matchMedia("(max-width: 640px)").matches ? 420 : 900;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    for (let index = 0; index < count; index += 1) {
      const radius = 62 + seededRandom() * 92;
      const theta = seededRandom() * Math.PI * 2;
      const phi = Math.acos((seededRandom() * 2) - 1);
      positions[index * 3] = radius * Math.sin(phi) * Math.cos(theta);
      positions[index * 3 + 1] = radius * Math.cos(phi);
      positions[index * 3 + 2] = radius * Math.sin(phi) * Math.sin(theta);
      const brightness = 0.55 + seededRandom() * 0.45;
      colors[index * 3] = brightness * 0.82;
      colors[index * 3 + 1] = brightness * 0.88;
      colors[index * 3 + 2] = brightness;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    const material = new THREE.PointsMaterial({
      size: 0.24,
      sizeAttenuation: true,
      transparent: true,
      opacity: 0.76,
      vertexColors: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
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
    const geometry = new THREE.SphereGeometry(radius * 1.09, 24, 16);
    const material = new THREE.MeshBasicMaterial({
      color,
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
    mesh.add(createAtmosphere(radius, color, type === "child" ? 0.08 : 0.12));
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
    updateSelection();
    clearStatus();
    document.body.classList.add("petit-univ-webgl-ready");
    window.dispatchEvent(new CustomEvent("petit:univ-webgl-rendered", {
      detail: { systems: models.length, tasks: state.entries.size },
    }));
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
    state.entries.forEach((entry, taskId) => {
      const selected = taskId === state.selectedTaskId;
      const material = entry.object?.material;
      if (material?.isMeshStandardMaterial) {
        material.emissiveIntensity = entry.object.userData.baseEmissiveIntensity * (selected ? 1.85 : 1);
      }
      entry.object?.scale?.setScalar(selected ? 1.14 : 1);
    });
    state.labels.forEach(({ element, entry }) => {
      element.classList.toggle("is-selected", Boolean(entry.taskId && entry.taskId === state.selectedTaskId));
    });
  };

  const startCameraTween = (position, target, duration = 720) => {
    state.cameraTween = {
      startedAt: performance.now(),
      duration: reducedMotion.matches ? 1 : duration,
      fromPosition: state.camera.position.clone(),
      toPosition: position.clone(),
      fromTarget: state.controls.target.clone(),
      toTarget: target.clone(),
    };
  };

  const focusEntry = (entry) => {
    if (!entry?.object || !state.camera || !state.controls) return false;
    const target = new THREE.Vector3();
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
    state.selectedTaskId = null;
    updateSelection();
    document.body.classList.remove("petit-univ-manage-open");
    startCameraTween(new THREE.Vector3(0, 10, 34), new THREE.Vector3(0, 0, 0), 760);
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

    const domNode = entry.domNode?.isConnected
      ? entry.domNode
      : state.map?.querySelector(`[data-task-id="${escapeSelector(entry.taskId)}"]`);
    domNode?.click?.();
    focusEntry(entry);
    if (isAlreadySelected) {
      openDetail();
    }
    return true;
  };

  const zoomBy = (factor) => {
    if (!state.camera || !state.controls) return;
    state.cameraTween = null;
    const offset = state.camera.position.clone().sub(state.controls.target);
    const nextDistance = clamp(offset.length() * factor, state.controls.minDistance, state.controls.maxDistance);
    offset.setLength(nextDistance);
    state.camera.position.copy(state.controls.target).add(offset);
    state.controls.update();
  };

  const raycastAt = (clientX, clientY) => {
    if (!state.renderer || !state.camera) return null;
    const rect = state.renderer.domElement.getBoundingClientRect();
    state.pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    state.pointer.y = -(((clientY - rect.top) / rect.height) * 2 - 1);
    state.raycaster.setFromCamera(state.pointer, state.camera);
    return state.raycaster.intersectObjects(state.interactiveMeshes, false)[0]?.object || null;
  };

  const installPointerInteraction = () => {
    const canvas = state.renderer.domElement;
    canvas.addEventListener("pointerdown", (event) => {
      state.pointerDown = { x: event.clientX, y: event.clientY, time: performance.now() };
    });
    canvas.addEventListener("pointerup", (event) => {
      const start = state.pointerDown;
      state.pointerDown = null;
      if (!start) return;
      const distance = Math.hypot(event.clientX - start.x, event.clientY - start.y);
      if (distance > 6 || performance.now() - start.time > 700) return;
      const object = raycastAt(event.clientX, event.clientY);
      if (object?.userData?.entry) selectEntry(object.userData.entry);
    });
    canvas.addEventListener("pointermove", (event) => {
      if (state.pointerDown) return;
      const object = raycastAt(event.clientX, event.clientY);
      canvas.style.cursor = object ? "pointer" : "grab";
    }, { passive: true });
    canvas.addEventListener("keydown", (event) => {
      if (event.key === "Escape" || event.key === "0") resetCamera();
      if (event.key === "+" || event.key === "=") zoomBy(0.84);
      if (event.key === "-") zoomBy(1.18);
    });
  };

  const updateCameraTween = (time) => {
    const tween = state.cameraTween;
    if (!tween) return;
    const progress = clamp((time - tween.startedAt) / tween.duration, 0, 1);
    const eased = progress < 0.5
      ? 4 * progress * progress * progress
      : 1 - Math.pow(-2 * progress + 2, 3) / 2;
    state.camera.position.lerpVectors(tween.fromPosition, tween.toPosition, eased);
    state.controls.target.lerpVectors(tween.fromTarget, tween.toTarget, eased);
    if (progress >= 1) state.cameraTween = null;
  };

  const updateLabels = () => {
    if (!state.camera || !state.viewport) return;
    const width = state.viewport.clientWidth;
    const height = state.viewport.clientHeight;
    const forward = new THREE.Vector3();
    state.camera.getWorldDirection(forward);

    state.labels.forEach(({ element, object, entry, type }) => {
      if (!object?.visible) {
        element.hidden = true;
        return;
      }
      const world = new THREE.Vector3();
      object.getWorldPosition(world);
      const toObject = world.clone().sub(state.camera.position);
      const inFront = forward.dot(toObject) > 0;
      const projected = world.clone().project(state.camera);
      const withinFrustum = projected.z > -1 && projected.z < 1
        && projected.x > -1.18 && projected.x < 1.18
        && projected.y > -1.18 && projected.y < 1.18;
      const distance = state.camera.position.distanceTo(world);
      const maxDistance = type === "child" ? 38 : 82;
      const selected = Boolean(entry.taskId && entry.taskId === state.selectedTaskId);
      const visible = inFront && withinFrustum && (selected || distance < maxDistance);
      element.hidden = !visible;
      if (!visible) return;
      element.style.left = `${((projected.x * 0.5) + 0.5) * width}px`;
      element.style.top = `${((-projected.y * 0.5) + 0.5) * height}px`;
      const fadeStart = maxDistance * 0.6;
      const opacity = selected ? 1 : clamp(1 - ((distance - fadeStart) / (maxDistance - fadeStart)), 0.22, 1);
      element.style.opacity = opacity.toFixed(3);
      element.style.zIndex = String(Math.round((1 - projected.z) * 500));
    });
  };

  const animate = (time) => {
    if (!state.ready || !isPanelActive()) return;
    updateCameraTween(time);
    state.controls.update();
    if (!reducedMotion.matches) {
      state.animatedMeshes.forEach(({ mesh, speed, type }) => {
        mesh.rotation.y = time * speed;
        if (type === "child") mesh.rotation.x = Math.sin(time * speed * 0.7) * 0.08;
      });
    }
    updateLabels();
    state.renderer.render(state.scene, state.camera);
  };

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
  document.addEventListener("petit:tasks-updated", () => requestRebuild("tasks-updated"));
  window.addEventListener("petit:panel-change", () => {
    resize();
    requestRebuild("panel-change");
  });
  window.addEventListener("petit:area-change", () => {
    resize();
    requestRebuild("area-change");
  });
  reducedMotion.addEventListener?.("change", () => {
    if (state.controls) state.controls.enableDamping = !reducedMotion.matches;
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
