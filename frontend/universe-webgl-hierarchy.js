// Normalize the hidden DOM bridge into root-task systems before the WebGL scene reads it.
(() => {
  if (window.PetitUnivWebGLHierarchy?.initialized) return;

  const SOURCE = "webgl-hierarchy";
  const DONE_STATUSES = new Set(["done", "canceled", "cancelled", "chancel", "完了"]);
  let latestTasks = [];
  let scheduled = false;
  let normalizing = false;
  let actionBridge = null;

  const text = (value, fallback = "") => String(value ?? "").trim() || fallback;
  const taskKey = (task, index = 0) => String(task?.id || task?.external_id || task?.url || `task-${index}`);
  const isDone = (task) => DONE_STATUSES.has(text(task?.status, "Ready").toLowerCase());
  const isRoot = (task) => task?.hierarchy_role === "root"
    || (!task?.parent_task_id && !task?.parent_external_id);

  const ensureActionBridge = () => {
    if (actionBridge?.isConnected) return actionBridge;
    actionBridge = document.querySelector("#univ-webgl-action-bridge");
    if (!actionBridge) {
      actionBridge = document.createElement("div");
      actionBridge.id = "univ-webgl-action-bridge";
      actionBridge.hidden = true;
      actionBridge.setAttribute("aria-hidden", "true");
      document.body.appendChild(actionBridge);
    }
    return actionBridge;
  };

  const aliasesOf = (task, index = 0) => {
    const aliases = new Set([taskKey(task, index)]);
    [task?.id, task?.external_id, task?.root_task_id].forEach((value) => {
      const normalized = text(value);
      if (normalized) aliases.add(normalized);
    });
    return aliases;
  };

  const parentAliasesOf = (task) => [
    task?.parent_task_id,
    task?.parent_external_id,
    task?.root_task_id,
  ].map((value) => text(value)).filter(Boolean);

  const createHeading = (task) => {
    const headingWrap = document.createElement("span");
    headingWrap.className = "constellation-card__heading";
    const eyebrow = document.createElement("span");
    eyebrow.className = "eyebrow";
    eyebrow.textContent = text(task.project_title || task.root_title, "Task");
    const heading = document.createElement("strong");
    heading.textContent = text(task.title, "名称未設定");
    headingWrap.append(eyebrow, heading);
    return headingWrap;
  };

  const bindAction = (clone, original, taskId) => {
    clone.dataset.taskId = taskId;
    clone.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      original?.click?.();
    });
  };

  const createParentNode = (root, original, taskId, childCount) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "univ-task-planet";
    button.setAttribute("aria-label", `${text(root.title, "親タスク")}へFocus`);
    button.setAttribute("aria-pressed", "false");
    bindAction(button, original, taskId);
    const counts = document.createElement("span");
    counts.className = "constellation-card__counts";
    counts.textContent = `${childCount} satellite${childCount === 1 ? "" : "s"}`;
    button.append(createHeading(root), counts);
    return button;
  };

  const createChildNode = (task, original, taskId) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "universe-task univ-satellite";
    button.setAttribute("aria-label", `${text(task.title, "子タスク")}へFocus`);
    button.setAttribute("aria-pressed", "false");
    bindAction(button, original, taskId);
    const title = document.createElement("span");
    title.className = "universe-task__title";
    title.textContent = text(task.title, "名称未設定");
    button.appendChild(title);
    return button;
  };

  const mapActions = (nodes) => {
    const originals = new Map();
    nodes.forEach((node) => {
      const taskId = text(node.dataset.taskId);
      if (taskId && !originals.has(taskId)) originals.set(taskId, node);
    });
    return originals;
  };

  const collectOriginalActions = (grid) => {
    const nodes = Array.from(grid.querySelectorAll("[data-task-id]"));
    const originals = mapActions(nodes);
    const bridge = ensureActionBridge();
    bridge.replaceChildren(...nodes);
    return originals;
  };

  const existingOriginalActions = () => mapActions(
    Array.from(ensureActionBridge().querySelectorAll("[data-task-id]")),
  );

  const resolveTasks = () => {
    const shared = window.PetitUniverse?.tasks?.();
    const tasks = Array.isArray(shared) && shared.length ? shared : latestTasks;
    return tasks.filter((task) => !isDone(task));
  };

  const buildHierarchy = (tasks) => {
    const roots = tasks.filter(isRoot);
    const children = tasks.filter((task) => !isRoot(task));
    const rootByAlias = new Map();
    const rootByTitle = new Map();

    roots.forEach((root, index) => {
      aliasesOf(root, index).forEach((alias) => rootByAlias.set(alias, root));
      [root.title, root.root_title, root.project_title].map((value) => text(value)).filter(Boolean)
        .forEach((title) => {
          if (!rootByTitle.has(title)) rootByTitle.set(title, root);
        });
    });

    const childrenByRoot = new Map(roots.map((root) => [root, []]));
    const ungrouped = [];
    children.forEach((child) => {
      const root = parentAliasesOf(child).map((alias) => rootByAlias.get(alias)).find(Boolean)
        || rootByTitle.get(text(child.root_title))
        || rootByTitle.get(text(child.parent_title))
        || null;
      if (root) childrenByRoot.get(root)?.push(child);
      else ungrouped.push(child);
    });

    ungrouped.forEach((task) => {
      roots.push(task);
      childrenByRoot.set(task, []);
    });
    return roots.map((root) => ({ root, children: childrenByRoot.get(root) || [] }));
  };

  const normalize = () => {
    scheduled = false;
    if (normalizing || new URLSearchParams(window.location.search).get("renderer") === "css") return;
    const grid = document.querySelector("#constellation-grid");
    if (!grid) return;
    const tasks = resolveTasks();
    if (!tasks.length) return;

    normalizing = true;
    try {
      const alreadyNormalized = Boolean(
        grid.querySelector(':scope > .univ-task-system[data-webgl-normalized="true"]'),
      );
      const originals = alreadyNormalized ? existingOriginalActions() : collectOriginalActions(grid);
      const systems = buildHierarchy(tasks);
      const fragment = document.createDocumentFragment();

      systems.forEach(({ root, children }, index) => {
        const rootId = taskKey(root, tasks.indexOf(root));
        const system = document.createElement("div");
        system.className = "univ-task-system";
        system.dataset.webglNormalized = "true";
        system.dataset.rootTaskId = rootId;
        system.dataset.univProject = text(root.project_title || root.root_title || root.title, "Task");
        system.dataset.univVariant = String(index % 5);
        system.dataset.area = text(root.area, "unsorted").toLowerCase();

        const originalRoot = originals.get(rootId)
          || originals.get(text(root.external_id))
          || null;
        system.appendChild(createParentNode(root, originalRoot, rootId, children.length));

        const list = document.createElement("div");
        list.className = "universe-task-list";
        children.forEach((child) => {
          const childId = taskKey(child, tasks.indexOf(child));
          const originalChild = originals.get(childId)
            || originals.get(text(child.external_id))
            || null;
          list.appendChild(createChildNode(child, originalChild, childId));
        });
        system.appendChild(list);
        fragment.appendChild(system);
      });

      grid.replaceChildren(fragment);
      grid.dataset.webglHierarchyReady = "true";
      window.dispatchEvent(new CustomEvent("petit:universe-rendered", {
        detail: { source: SOURCE, systems: systems.length, tasks: tasks.length },
      }));
    } finally {
      normalizing = false;
    }
  };

  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(normalize);
  };

  document.addEventListener("petit:tasks-updated", (event) => {
    if (Array.isArray(event.detail?.tasks)) latestTasks = event.detail.tasks;
    schedule();
  });
  window.addEventListener("petit:universe-rendered", (event) => {
    if (event.detail?.source === SOURCE) return;
    schedule();
  });
  window.addEventListener("petit:panel-change", schedule);

  window.PetitUnivWebGLHierarchy = {
    initialized: true,
    normalize,
    schedule,
    buildHierarchy,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      schedule();
      window.setTimeout(schedule, 280);
    }, { once: true });
  } else {
    schedule();
    window.setTimeout(schedule, 280);
  }
})();
