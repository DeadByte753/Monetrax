(() => {
  "use strict";

  const root = document.documentElement;
  const motionOK = () => !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const NUMBER_RE = /^([−\-+]?)(\D*?)(\d[\d,]*)(\.\d+)?(\D*)$/;

  function parseAmount(text) {
    const m = text.trim().match(NUMBER_RE);
    if (!m) return null;
    const value = parseFloat(m[3].replace(/,/g, "") + (m[4] || ""));
    if (!isFinite(value)) return null;
    return {
      sign: m[1], prefix: m[2], suffix: m[5], value,
      decimals: m[4] ? m[4].length - 1 : 0,
      grouping: m[3].indexOf(",") !== -1
    };
  }

  function formatAmount(p, v) {
    const n = v.toLocaleString("en-US", {
      minimumFractionDigits: p.decimals, maximumFractionDigits: p.decimals, useGrouping: p.grouping
    });
    return p.sign + p.prefix + n + p.suffix;
  }

  const easeOutExpo = (t) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));
  const running = new Set();

  function countUp(el) {
    const original = el.textContent;
    const parsed = parseAmount(original);
    if (!parsed || parsed.value === 0) {
      el.classList.add("is-counted");
      return;
    }
    const delay = parseInt(el.dataset.countDelay || "250", 10);
    const duration = Math.min(1600, 900 + Math.log10(parsed.value + 1) * 120);
    const job = { el, original, done: false };
    running.add(job);
    const finish = () => {
      if (job.done) return;
      job.done = true;
      el.textContent = original;
      running.delete(job);
    };
    job.finish = finish;
    try {
      el.textContent = formatAmount(parsed, 0);
    } catch (_) {
      finish();
      el.classList.add("is-counted");
      return;
    }
    el.classList.add("is-counted");
    let start = null;
    const step = (now) => {
      if (job.done) return;
      if (start === null) start = now + delay;
      const t = Math.max(0, (now - start) / duration);
      if (t >= 1) {
        finish();
        return;
      }
      try {
        el.textContent = formatAmount(parsed, parsed.value * easeOutExpo(t));
      } catch (_) {
        finish();
        return;
      }
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function initCounters() {
    const els = Array.from(document.querySelectorAll("[data-count]"));
    if (!els.length) return;
    if (!motionOK() || !root.classList.contains("mx-motion")) {
      els.forEach((el) => el.classList.add("is-counted"));
      return;
    }
    const vh = window.innerHeight || document.documentElement.clientHeight;
    els.forEach((el) => {
      const r = el.getBoundingClientRect();
      const visible = r.bottom > 0 && r.top < vh && r.width > 0;
      if (visible) countUp(el);
      else el.classList.add("is-counted");
    });
    const finishAll = () => running.forEach((job) => job.finish());
    window.addEventListener("beforeprint", finishAll);
    window.addEventListener("pagehide", finishAll);
  }

  function initParallax() {
    const stage = document.querySelector(".mx-brand");
    if (!stage || !motionOK() || !window.matchMedia("(pointer: fine)").matches) return;
    const layers = Array.from(stage.querySelectorAll("[data-depth]"));
    if (!layers.length) return;
    let frame = 0;
    let px = 0;
    let py = 0;
    const paint = () => {
      frame = 0;
      layers.forEach((el) => {
        const d = parseFloat(el.dataset.depth) || 0;
        el.style.translate = `${(px * d).toFixed(2)}px ${(py * d).toFixed(2)}px`;
      });
    };
    stage.addEventListener("pointermove", (e) => {
      const r = stage.getBoundingClientRect();
      px = ((e.clientX - r.left) / r.width - 0.5) * 2;
      py = ((e.clientY - r.top) / r.height - 0.5) * 2;
      if (!frame) frame = requestAnimationFrame(paint);
    });
    stage.addEventListener("pointerleave", () => {
      px = 0;
      py = 0;
      if (!frame) frame = requestAnimationFrame(paint);
    });
  }

  const loadbar = () => document.querySelector(".mx-loadbar");

  function startLoading() {
    const bar = loadbar();
    if (!bar) return;
    bar.classList.remove("is-loading");
    void bar.offsetWidth;
    bar.classList.add("is-loading");
  }

  function resetLoading() {
    const bar = loadbar();
    if (bar) bar.classList.remove("is-loading");
    root.classList.remove("mx-leaving");
    document.querySelectorAll(".is-busy").forEach((b) => {
      b.classList.remove("is-busy");
      b.removeAttribute("aria-busy");
    });
    document.querySelectorAll("form[data-submitting]").forEach((f) => delete f.dataset.submitting);
    document.querySelectorAll("form[data-confirmed]").forEach((f) => delete f.dataset.confirmed);
  }

  function isNavigationLink(a, e) {
    if (!a || !a.href) return false;
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return false;
    if (a.target && a.target !== "_self") return false;
    if (a.hasAttribute("download")) return false;
    let url;
    try { url = new URL(a.href, location.href); } catch (_) { return false; }
    if (url.origin !== location.origin) return false;
    if (url.pathname === location.pathname && url.search === location.search && url.hash) return false;
    if (!/^https?:$/.test(url.protocol)) return false;
    return true;
  }

  function initNavigationFeedback() {
    document.addEventListener("click", (e) => {
      const a = e.target.closest("a[href]");
      if (!isNavigationLink(a, e)) return;
      setTimeout(() => {
        if (!e.defaultPrevented || a.hasAttribute("data-transition")) {
          startLoading();
          if (motionOK()) root.classList.add("mx-leaving");
        }
      }, 0);
    });

    document.addEventListener("submit", (e) => {
      const form = e.target;
      if (form.dataset.submitting) {
        e.preventDefault();
        return;
      }
      setTimeout(() => {
        if (e.defaultPrevented) return;
        form.dataset.submitting = "1";
        startLoading();
        if (form.matches("[data-auth-form]")) return;
        const btn = e.submitter || form.querySelector('button[type="submit"], button:not([type])');
        if (btn && !btn.classList.contains("mx-icon-btn-sm") && !btn.closest(".mx-notif-link")) {
          btn.classList.add("is-busy");
          btn.setAttribute("aria-busy", "true");
        }
      }, 0);
    });

    window.addEventListener("pageshow", (e) => {
      if (e.persisted) resetLoading();
    });
  }

  function dismissAlert(alert) {
    if (!alert || alert.dataset.leaving) return;
    alert.dataset.leaving = "1";
    const container = alert.parentElement;
    const cleanup = () => {
      alert.remove();
      if (container && container.children.length === 0 && container.matches(".space-y-3, .mb-6")) container.remove();
    };
    if (!motionOK()) {
      cleanup();
      return;
    }
    alert.style.height = alert.offsetHeight + "px";
    void alert.offsetHeight;
    alert.classList.add("is-leaving");
    alert.style.height = "0px";
    alert.style.paddingTop = "0px";
    alert.style.paddingBottom = "0px";
    alert.style.marginTop = "0px";
    alert.style.borderWidth = "0px";
    setTimeout(cleanup, 380);
  }

  function initAlerts() {
    document.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-dismiss-alert]");
      if (btn) dismissAlert(btn.closest(".mx-alert"));
    });
    if (!motionOK()) return;
    document.querySelectorAll(".mx-alert-success").forEach((alert) => {
      alert.classList.add("is-timed");
      alert.addEventListener("animationend", (e) => {
        if (e.animationName === "mx-timer") dismissAlert(alert);
      });
    });
  }

  function closeDialog(dialog) {
    if (!dialog || !dialog.open) return;
    if (!motionOK()) {
      dialog.close();
      return;
    }
    if (dialog.classList.contains("is-closing")) return;
    dialog.classList.add("is-closing");
    let finished = false;
    const done = () => {
      if (finished) return;
      finished = true;
      dialog.classList.remove("is-closing");
      dialog.close();
    };
    dialog.addEventListener("animationend", function handler(e) {
      if (e.target !== dialog) return;
      dialog.removeEventListener("animationend", handler);
      done();
    });
    setTimeout(done, 260);
  }

  function initDialogs() {
    document.addEventListener("cancel", (e) => {
      const d = e.target;
      if (d instanceof HTMLDialogElement && d.classList.contains("mx-dialog") && motionOK()) {
        e.preventDefault();
        closeDialog(d);
      }
    }, true);
  }

  window.MonetraxMotion = { closeDialog, dismissAlert, motionOK };

  document.addEventListener("DOMContentLoaded", () => {
    initCounters();
    initParallax();
    initNavigationFeedback();
    initAlerts();
    initDialogs();
  });
})();
