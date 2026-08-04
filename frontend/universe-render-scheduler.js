// Shared render scheduler for PETIT Universe modules.
(() => {
  if (window.PetitUniverseRenderScheduler?.initialized) return;

  const jobs = new Map();
  const pending = new Map();
  let frameId = null;
  let flushing = false;

  const normalizeName = (value) => String(value || "").trim();
  const normalizeReason = (value) => {
    if (typeof value === "string" && value.trim()) return value.trim();
    if (value?.type) return String(value.type);
    return "unspecified";
  };

  const scheduleFrame = () => {
    if (frameId != null || flushing || !pending.size) return;
    frameId = window.requestAnimationFrame(flush);
  };

  function flush() {
    frameId = null;
    if (flushing || !pending.size) return;
    flushing = true;

    const batch = Array.from(pending.entries()).map(([name, reasons]) => ({
      name,
      reasons: Array.from(reasons),
      job: jobs.get(name),
    }));
    pending.clear();

    try {
      batch.forEach(({ name, reasons, job }) => {
        if (typeof job !== "function") return;
        try {
          job({ name, reasons });
        } catch (error) {
          console.error(`PETIT Universe render job failed: ${name}`, error);
        }
      });
    } finally {
      flushing = false;
      scheduleFrame();
    }
  }

  const register = (name, job) => {
    const key = normalizeName(name);
    if (!key || typeof job !== "function") return () => {};
    jobs.set(key, job);
    return () => {
      if (jobs.get(key) === job) jobs.delete(key);
      pending.delete(key);
    };
  };

  const request = (name, reason = "unspecified") => {
    const key = normalizeName(name);
    if (!key) return;
    const reasons = pending.get(key) || new Set();
    reasons.add(normalizeReason(reason));
    pending.set(key, reasons);
    scheduleFrame();
  };

  const requestAll = (reason = "unspecified") => {
    jobs.forEach((_job, name) => request(name, reason));
  };

  const cancel = (name) => {
    const key = normalizeName(name);
    if (key) pending.delete(key);
  };

  window.PetitUniverseRenderScheduler = {
    initialized: true,
    register,
    request,
    requestAll,
    cancel,
    flush,
    state: () => ({
      jobs: Array.from(jobs.keys()),
      pending: Array.from(pending.keys()),
      scheduled: frameId != null,
      flushing,
    }),
  };

  window.dispatchEvent(new CustomEvent("petit:render-scheduler-ready"));
})();
