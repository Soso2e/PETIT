// PETIT Life map: decorate the existing Project / Task DOM as a connected constellation.
(() => {
  const MAP_SELECTOR = "#constellation-grid";
  const SVG_NS = "http://www.w3.org/2000/svg";
  const mobileQuery = window.matchMedia("(max-width: 640px)");
  let decorating = false;
  let scheduled = false;

  const projectCards = (map) => Array.from(map.children)
    .filter((element) => element.classList?.contains("constellation-card"));

  const createSvgElement = (name, attributes = {}) => {
    const element = document.createElementNS(SVG_NS, name);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  };

  const ensureCore = (map) => {
    let core = map.querySelector(":scope > .life-map__core");
    if (core) return core;
    core = document.createElement("div");
    core.className = "life-map__core";
    core.setAttribute("aria-hidden", "true");
    core.innerHTML = '<span class="eyebrow">YOUR LIFE</span><strong>LIFE</strong><small>星を選んでFocusへ</small>';
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
    if (count === 1) return [{ x: 50, y: 22, scale: 1.08 }];
    const radiusX = count <= 4 ? 34 : 39;
    const radiusY = count <= 4 ? 30 : 36;
    return Array.from({ length: count }, (_, index) => {
      const angle = (-Math.PI / 2) + ((Math.PI * 2 * index) / count);
      const ringFactor = count > 7 && index % 2 ? 0.76 : 1;
      return {
        x: 50 + Math.cos(angle) * radiusX * ringFactor,
        y: 50 + Math.sin(angle) * radiusY * ringFactor,
        scale: index === 0 ? 1.08 : 1,
      };
    });
  };

  const mobileLayout = (count) => {
    if (count === 1) return [{ x: 50, y: 31, scale: 1.04 }];
    const startY = 25;
    const endY = 91;
    const step = (endY - startY) / Math.max(1, count - 1);
    return Array.from({ length: count }, (_, index) => ({
      x: index % 2 === 0 ? 29 : 71,
      y: startY + (step * index),
      scale: index === 0 ? 1.04 : 0.96,
    }));
  };

  const layoutFor = (count) => mobileQuery.matches ? mobileLayout(count) : desktopLayout(count);
  const corePosition = () => mobileQuery.matches ? { x: 50, y: 9 } : { x: 50, y: 50 };

  const addConnection = (svg, from, to, active = false, secondary = false) => {
    const line = createSvgElement("line", {
      x1: from.x,
      y1: from.y,
      x2: to.x,
      y2: to.y,
      class: [
        "life-map__connection",
        active ? "is-active" : "",
        secondary ? "is-secondary" : "",
      ].filter(Boolean).join(" "),
      "vector-effect": "non-scaling-stroke",
    });
    svg.appendChild(line);
  };

  const decorateTaskStars = (card, index) => {
    const taskList = card.querySelector(".universe-task-list");
    if (!taskList) return;
    const tasks = Array.from(taskList.querySelectorAll(":scope > .universe-task"));
    taskList.style.setProperty("--life-task-count", String(tasks.length));
    tasks.forEach((task, taskIndex) => {
      const angle = (-90 + ((360 / Math.max(1, Math.min(tasks.length, 6))) * taskIndex));
      const radius = taskIndex % 2 === 0 ? 91 : 108;
      task.classList.add("life-task-star");
      task.style.setProperty("--task-angle", `${angle}deg`);
      task.style.setProperty("--task-radius", `${radius}px`);
      task.style.setProperty("--task-delay", `${(index * 45) + (taskIndex * 55)}ms`);
      if (taskIndex >= 6) task.classList.add("life-task-star--overflow");
      const title = task.querySelector(".universe-task__title")?.textContent?.trim();
      if (title) task.setAttribute("aria-label", `${title}をFocusで開く`);
    });
  };

  const decorate = () => {
    const map = document.querySelector(MAP_SELECTOR);
    if (!map || decorating) return;
    decorating = true;
    try {
      const cards = projectCards(map);
      map.classList.toggle("life-cosmos-map", cards.length > 0);
      if (!cards.length) return;

      map.style.setProperty("--life-project-count", String(cards.length));
      const core = ensureCore(map);
      const svg = ensureLines(map);
      const positions = layoutFor(cards.length);
      const center = corePosition();
      core.style.setProperty("--life-x", `${center.x}%`);
      core.style.setProperty("--life-y", `${center.y}%`);
      svg.replaceChildren();

      cards.forEach((card, index) => {
        const position = positions[index];
        const selected = card.classList.contains("is-selected");
        card.classList.add("life-star-system");
        card.style.setProperty("--life-x", `${position.x}%`);
        card.style.setProperty("--life-y", `${position.y}%`);
        card.style.setProperty("--life-scale", String(position.scale));
        card.style.setProperty("--life-delay", `${index * 70}ms`);

        const header = card.querySelector(".constellation-card__header");
        const projectName = card.querySelector(".constellation-card__heading strong")?.textContent?.trim();
        if (header && projectName) {
          header.setAttribute("aria-label", `${projectName}へフォーカス`);
          header.title = `${projectName}を開く`;
        }

        decorateTaskStars(card, index);
        addConnection(svg, center, position, selected);
        if (!mobileQuery.matches && cards.length > 2) {
          const next = positions[(index + 1) % positions.length];
          addConnection(svg, position, next, false, true);
        }
      });
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
    const observer = new MutationObserver(scheduleDecorate);
    observer.observe(map, { childList: true });
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
