// PETIT Life map: Layout Core planet, parent task planets, and child satellites into an interconnected celestial map.
(() => {
  const MAP_SELECTOR = "#constellation-grid";
  const SVG_NS = "http://www.w3.org/2000/svg";
  const mobileQuery = window.matchMedia("(max-width: 640px)");
  let decorating = false;
  let scheduled = false;

  const getPlanetSystems = (map) => Array.from(map.children)
    .filter((el) => el.classList?.contains("univ-task-system"));

  const createSvgElement = (name, attributes = {}) => {
    const element = document.createElementNS(SVG_NS, name);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  };

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

  const ensureLines = (map) => {
    let svg = map.querySelector(":scope > .life-map__lines");
    if (svg) return svg;
    svg = createSvgElement("svg", {
      class: "life-map__lines",
      viewBox: "0 0 100 100",
      preserveAspectRatio: "none",
      "aria-hidden": "true",
    });
    map.prepend(svg);
    return svg;
  };

  const desktopLayout = (count) => {
    if (count === 1) return [{ x: 50, y: 24, z: 150, scale: 1.06 }];
    const radiusX = count <= 4 ? 34 : (count <= 7 ? 38 : 42);
    const radiusY = count <= 4 ? 29 : (count <= 7 ? 34 : 38);
    return Array.from({ length: count }, (_, index) => {
      const angle = (-Math.PI / 2) + ((Math.PI * 2 * index) / count);
      const ringFactor = count > 6 && index % 2 === 1 ? 0.78 : 1;
      const depthBand = [170, -150, 95, -80, 35, -30][index % 6];
      const wave = Math.sin(angle * 1.5) * 45;
      return {
        x: 50 + Math.cos(angle) * radiusX * ringFactor,
        y: 50 + Math.sin(angle) * radiusY * ringFactor,
        z: Math.round(depthBand + wave),
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
      z: (index % 2 === 0 ? 55 : -55),
      scale: index === 0 ? 1.02 : 0.96,
    }));
  };

  const layoutFor = (count) => mobileQuery.matches ? mobileLayout(count) : desktopLayout(count);
  const corePosition = () => mobileQuery.matches ? { x: 50, y: 8 } : { x: 50, y: 50 };

  const addConnection = (svg, from, to, active = false, secondary = false, child = false) => {
    const line = createSvgElement("line", {
      x1: from.x,
      y1: from.y,
      x2: to.x,
      y2: to.y,
      class: [
        "life-map__connection",
        active ? "is-active" : "",
        secondary ? "is-secondary" : "",
        child ? "is-child" : "",
      ].filter(Boolean).join(" "),
      "vector-effect": "non-scaling-stroke",
    });
    svg.appendChild(line);
  };

  const arrangeSatellites = (systemNode, index, svg, systemPosition) => {
    const satelliteList = systemNode.querySelector(".universe-task-list");
    if (!satelliteList) return;
    const satellites = Array.from(satelliteList.querySelectorAll(":scope > .univ-satellite"));
    const count = satellites.length;
    satellites.forEach((sat, satIndex) => {
      const angleDeg = -90 + ((360 / Math.max(1, count)) * satIndex);
      const angle = angleDeg * Math.PI / 180;
      const radius = 82 + ((satIndex % 2) * 20);
      const satZ = Math.round(Math.sin((satIndex / Math.max(1, count)) * Math.PI * 2) * 54);
      sat.style.setProperty("--satellite-angle", `${angleDeg}deg`);
      sat.style.setProperty("--satellite-radius", `${radius}px`);
      sat.style.setProperty("--satellite-z", `${satZ}px`);
      sat.style.setProperty("--satellite-delay", `${(index * 50) + (satIndex * 40)}ms`);
      if (sat.dataset.taskId) sat.dataset.motionKey = `task-${sat.dataset.taskId}`;

      const xOffset = Math.cos(angle) * (radius / 12);
      const yOffset = Math.sin(angle) * (radius / 12);
      addConnection(
        svg,
        systemPosition,
        { x: systemPosition.x + xOffset, y: systemPosition.y + yOffset },
        sat.classList.contains("is-selected"),
        false,
        true,
      );
    });
  };

  const decorate = () => {
    const map = document.querySelector(MAP_SELECTOR);
    if (!map || decorating) return;
    decorating = true;
    try {
      const systems = getPlanetSystems(map);
      map.classList.toggle("life-cosmos-map", systems.length > 0);
      if (!systems.length) return;

      const mapHeight = mobileQuery.matches
        ? Math.max(800, 200 + (systems.length * 120))
        : (systems.length > 8 ? 860 : 720);
      map.style.minHeight = `${mapHeight}px`;
      map.style.setProperty("--life-project-count", String(systems.length));

      const core = ensureCore(map);
      const svg = ensureLines(map);
      const positions = layoutFor(systems.length);
      const center = corePosition();

      core.style.setProperty("--life-x", `${center.x}%`);
      core.style.setProperty("--life-y", `${center.y}%`);
      svg.replaceChildren();

      systems.forEach((system, index) => {
        const position = positions[index];
        const selected = system.classList.contains("is-selected");

        system.style.setProperty("--life-x", `${position.x}%`);
        system.style.setProperty("--life-y", `${position.y}%`);
        system.style.setProperty("--life-z", `${position.z}px`);
        system.style.setProperty("--life-scale", String(position.scale));
        system.style.setProperty("--life-delay", `${index * 60}ms`);

        addConnection(svg, center, position, selected);
        arrangeSatellites(system, index, svg, position);
      });

      window.PetitMotion?.refresh?.();
    } finally {
      decorating = false;
    }
  };

  const scheduleDecorate = () => {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(() => {
      scheduled = false;
      decorate();
    });
  };

  const initialize = () => {
    const map = document.querySelector(MAP_SELECTOR);
    if (!map || map.dataset.lifeMapReady === "true") return;
    map.dataset.lifeMapReady = "true";
    window.addEventListener("petit:universe-rendered", scheduleDecorate);
    mobileQuery.addEventListener?.("change", scheduleDecorate);
    window.addEventListener("resize", scheduleDecorate, { passive: true });
    scheduleDecorate();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
