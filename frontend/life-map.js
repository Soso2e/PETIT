// PETIT Life map: Core, parent task planets, child satellites, and 3D connections.
(() => {
  const MAP_SELECTOR = "#constellation-grid";
  const RENDER_JOB = "life-map";
  const mobileQuery = window.matchMedia("(max-width: 640px)");
  let decorating = false;
  let unregisterRenderJob = null;

  const systemsOf = (map) => Array.from(map.children)
    .filter((node) => node.classList?.contains("univ-task-system"));

  const ensureCore = (map) => {
    let core = map.querySelector(":scope > .life-map__core");
    if (core) return core;
    core = document.createElement("div");
    core.className = "life-map__core univ-core-planet";
    core.setAttribute("role", "button");
    core.setAttribute("tabindex", "0");
    core.setAttribute("aria-label", "Core overviewへ戻る");
    core.innerHTML = '<span class="eyebrow">YOUR CORE</span><strong>CORE</strong><small>Core Overview</small>';
    map.prepend(core);
    return core;
  };

  const ensureConnectionLayer = (map) => {
    let layer = map.querySelector(":scope > .univ-connection-layer");
    if (layer) return layer;
    layer = document.createElement("div");
    layer.className = "univ-connection-layer";
    map.prepend(layer);
    return layer;
  };

  const desktopLayout = (count) => {
    if (count === 1) return [{ x: 50, y: 24, z: 150, scale: 1.06 }];
    const radiusX = count <= 4 ? 34 : (count <= 7 ? 38 : 42);
    const radiusY = count <= 4 ? 29 : (count <= 7 ? 34 : 38);
    return Array.from({ length: count }, (_, index) => {
      const angle = (-Math.PI / 2) + ((Math.PI * 2 * index) / count);
      const ringFactor = count > 6 && index % 2 === 1 ? 0.78 : 1;
      const depthBand = [170, -150, 95, -80, 35, -30][index % 6];
      return {
        x: 50 + Math.cos(angle) * radiusX * ringFactor,
        y: 50 + Math.sin(angle) * radiusY * ringFactor,
        z: Math.round(depthBand + (Math.sin(angle * 1.5) * 45)),
        scale: index === 0 ? 1.06 : (index % 3 === 1 ? 0.94 : 1),
      };
    });
  };

  const mobileLayout = (count) => {
    if (count === 1) return [{ x: 50, y: 30, z: 45, scale: 1.02 }];
    const startY = 18;
    const endY = 92;
    const step = (endY - startY) / Math.max(1, count - 1);
    return Array.from({ length: count }, (_, index) => ({
      x: index % 2 === 0 ? 28 : 72,
      y: startY + (step * index),
      z: index % 2 === 0 ? 55 : -55,
      scale: index === 0 ? 1.02 : 0.96,
    }));
  };

  const layoutFor = (count) => mobileQuery.matches ? mobileLayout(count) : desktopLayout(count);
  const corePosition = () => mobileQuery.matches
    ? { x: 50, y: 8, z: 210 }
    : { x: 50, y: 50, z: 210 };

  const toPixels = (map, point) => ({
    x: (point.x / 100) * map.clientWidth,
    y: (point.y / 100) * map.clientHeight,
    z: point.z || 0,
  });

  const add3dConnection = (layer, from, to, { child = false, active = false } = {}) => {
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const dz = to.z - from.z;
    const horizontal = Math.hypot(dx, dz);
    const length = Math.hypot(horizontal, dy);
    if (!Number.isFinite(length) || length < 1) return;

    const yaw = Math.atan2(dz, dx) * 180 / Math.PI;
    const pitch = Math.atan2(dy, horizontal) * 180 / Math.PI;
    const line = document.createElement("span");
    line.className = [
      "univ-connection-3d",
      child ? "is-child" : "is-core",
      active ? "is-active" : "",
    ].filter(Boolean).join(" ");
    line.style.setProperty("--connection-x", `${from.x}px`);
    line.style.setProperty("--connection-y", `${from.y}px`);
    line.style.setProperty("--connection-z", `${from.z}px`);
    line.style.setProperty("--connection-length", `${length}px`);
    line.style.setProperty("--connection-yaw", `${-yaw}deg`);
    line.style.setProperty("--connection-pitch", `${pitch}deg`);
    layer.appendChild(line);
  };

  const arrangeSatellites = (map, system, systemIndex, layer, systemPosition) => {
    const list = system.querySelector(".universe-task-list");
    if (!list) return;
    const satellites = Array.from(list.querySelectorAll(":scope > .univ-satellite"));
    const count = satellites.length;
    const origin = toPixels(map, systemPosition);

    satellites.forEach((satellite, index) => {
      const angleDeg = -90 + ((360 / Math.max(1, count)) * index);
      const angle = angleDeg * Math.PI / 180;
      const radius = 82 + ((index % 2) * 20);
      const satelliteZ = Math.round(Math.sin((index / Math.max(1, count)) * Math.PI * 2) * 54);
      satellite.style.setProperty("--satellite-angle", `${angleDeg}deg`);
      satellite.style.setProperty("--satellite-radius", `${radius}px`);
      satellite.style.setProperty("--satellite-z", `${satelliteZ}px`);
      satellite.style.setProperty("--satellite-delay", `${(systemIndex * 50) + (index * 40)}ms`);
      if (satellite.dataset.taskId) satellite.dataset.motionKey = `task-${satellite.dataset.taskId}`;

      add3dConnection(layer, origin, {
        x: origin.x + (Math.cos(angle) * radius),
        y: origin.y + (Math.sin(angle) * radius),
        z: systemPosition.z + 82 + 30 + satelliteZ,
      }, {
        child: true,
        active: satellite.classList.contains("is-selected"),
      });
    });
  };

  const decorate = () => {
    const map = document.querySelector(MAP_SELECTOR);
    if (!map || decorating) return;
    decorating = true;
    try {
      const systems = systemsOf(map);
      map.classList.toggle("life-cosmos-map", systems.length > 0);
      if (!systems.length) return;

      const mapHeight = mobileQuery.matches
        ? Math.max(800, 200 + (systems.length * 120))
        : (systems.length > 8 ? 860 : 720);
      map.style.minHeight = `${mapHeight}px`;
      map.style.setProperty("--life-project-count", String(systems.length));

      const core = ensureCore(map);
      const layer = ensureConnectionLayer(map);
      const positions = layoutFor(systems.length);
      const center = corePosition();
      core.style.setProperty("--life-x", `${center.x}%`);
      core.style.setProperty("--life-y", `${center.y}%`);
      layer.replaceChildren();

      const corePx = toPixels(map, center);
      systems.forEach((system, index) => {
        const position = positions[index];
        system.style.setProperty("--life-x", `${position.x}%`);
        system.style.setProperty("--life-y", `${position.y}%`);
        system.style.setProperty("--life-z", `${position.z}px`);
        system.style.setProperty("--life-scale", String(position.scale));
        system.style.setProperty("--life-delay", `${index * 60}ms`);

        const taskPx = toPixels(map, { ...position, z: position.z + 82 });
        add3dConnection(layer, corePx, taskPx, {
          active: system.classList.contains("is-selected"),
        });
        arrangeSatellites(map, system, index, layer, position);
      });

      window.PetitMotion?.refresh?.();
    } finally {
      decorating = false;
    }
  };

  const requestRender = (reason) => {
    const scheduler = window.PetitUniverseRenderScheduler;
    if (scheduler?.initialized) {
      scheduler.request(RENDER_JOB, reason);
      return;
    }
    window.requestAnimationFrame(decorate);
  };

  const registerRenderJob = () => {
    if (unregisterRenderJob || !window.PetitUniverseRenderScheduler?.initialized) return;
    unregisterRenderJob = window.PetitUniverseRenderScheduler.register(RENDER_JOB, decorate);
    requestRender("register");
  };

  const initialize = () => {
    const map = document.querySelector(MAP_SELECTOR);
    if (!map || map.dataset.lifeMapReady === "true") return;
    map.dataset.lifeMapReady = "true";

    registerRenderJob();
    window.addEventListener("petit:render-scheduler-ready", registerRenderJob, { once: true });
    window.addEventListener("petit:universe-rendered", () => requestRender("universe-rendered"));
    document.addEventListener("petit:tasks-updated", () => requestRender("tasks-updated"));
    mobileQuery.addEventListener?.("change", () => requestRender("responsive-change"));
    window.addEventListener("resize", () => requestRender("resize"), { passive: true });
    requestRender("initialize");
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
