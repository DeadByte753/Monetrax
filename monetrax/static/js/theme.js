(() => {
  "use strict";

  const root = document.documentElement;
  const media = window.matchMedia("(prefers-color-scheme: dark)");

  const getPref = () => root.dataset.themePref || "system";
  const isDark = (pref) => pref === "dark" || (pref === "system" && media.matches);

  function apply(pref, { animate = true } = {}) {
    root.dataset.themePref = pref;
    const dark = isDark(pref);
    if (dark === root.classList.contains("dark")) return syncControls();
    if (animate && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      root.classList.add("mx-theme-anim");
      window.setTimeout(() => root.classList.remove("mx-theme-anim"), 350);
    }
    root.classList.toggle("dark", dark);
    syncControls();
    document.dispatchEvent(new CustomEvent("mx-theme-change", { detail: { dark, pref } }));
  }

  function save(pref) {
    try { localStorage.setItem("mx-theme", pref); } catch (_) {}
    const endpoint = document.body.dataset.themeEndpoint;
    const token = document.querySelector('meta[name="csrf-token"]');
    if (!endpoint) return;
    const body = new URLSearchParams({ theme: pref });
    fetch(endpoint, {
      method: "POST",
      headers: { "X-CSRF-Token": token ? token.content : "", "X-Requested-With": "fetch" },
      body
    }).catch(() => {});
  }

  const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function originOf(el) {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }

  function setPref(pref, origin) {
    const switching = isDark(pref) !== root.classList.contains("dark");
    if (!switching || reducedMotion() || typeof document.startViewTransition !== "function") {
      apply(pref);
      save(pref);
      return;
    }
    const w = window.innerWidth;
    const h = window.innerHeight;
    const x = origin ? origin.x : w - 40;
    const y = origin ? origin.y : 32;
    const radius = Math.hypot(Math.max(x, w - x), Math.max(y, h - y));
    root.classList.add("mx-theme-vt");
    let transition;
    try {
      transition = document.startViewTransition(() => apply(pref, { animate: false }));
    } catch (_) {
      root.classList.remove("mx-theme-vt");
      apply(pref);
      save(pref);
      return;
    }
    transition.ready.then(() => {
      root.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
        { duration: 720, easing: "steps(12, end)", pseudoElement: "::view-transition-new(root)" }
      );
    }).catch(() => {});
    const cleanup = () => root.classList.remove("mx-theme-vt");
    transition.finished.then(cleanup, cleanup);
    transition.updateCallbackDone.catch(() => apply(pref, { animate: false }));
    save(pref);
  }

  function syncControls() {
    const dark = root.classList.contains("dark");
    document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
      btn.setAttribute("aria-pressed", String(dark));
      btn.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
      btn.title = dark ? "Light mode" : "Dark mode";
    });
    document.querySelectorAll('input[name="theme"]').forEach((r) => { r.checked = r.value === getPref(); });
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-theme-toggle]");
    if (btn) setPref(root.classList.contains("dark") ? "light" : "dark", originOf(btn));
  });

  document.addEventListener("change", (e) => {
    if (e.target.matches('input[name="theme"][data-theme-live]')) {
      setPref(e.target.value, originOf(e.target.closest("label")));
    }
  });

  media.addEventListener("change", () => { if (getPref() === "system") apply("system"); });

  window.addEventListener("storage", (e) => {
    if (e.key === "mx-theme" && e.newValue) apply(e.newValue);
  });

  document.addEventListener("DOMContentLoaded", syncControls);
  window.MonetraxTheme = { setPref, isDark: () => root.classList.contains("dark") };
})();
