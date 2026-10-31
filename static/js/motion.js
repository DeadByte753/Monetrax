(() => {
  "use strict";

  const root = document.documentElement;
  const motionOK = () => !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- Arcade score reels ----------
  // Every digit spins like a slot reel, then locks in left to right. Digits in VT323 are all the same
  // width, so nothing shifts while it spins. The real text is restored when the reel stops.
  const running = new Set();
  const randDigit = () => String(Math.floor(Math.random() * 10));

  function reel(el, delay) {
    const original = el.textContent;
    if (!/\d/.test(original) || el.dataset.reeling) {
      el.classList.add("is-counted");
      return;
    }
    el.dataset.reeling = "1";
    el.classList.add("is-counted");
    el.setAttribute("aria-label", original.trim());
    const wrap = document.createElement("span");
    wrap.className = "mx-reel";
    wrap.setAttribute("aria-hidden", "true");
    const cells = [];
    for (const ch of original) {
      if (/\d/.test(ch)) {
        const d = document.createElement("span");
        d.className = "mx-reel-d is-spinning";
        d.textContent = randDigit();
        d.dataset.final = ch;
        wrap.appendChild(d);
        cells.push(d);
      } else {
        wrap.appendChild(document.createTextNode(ch));
      }
    }
    el.textContent = "";
    el.appendChild(wrap);

    const job = { done: false };
    const finish = () => {
      if (job.done) return;
      job.done = true;
      el.textContent = original;
      el.removeAttribute("aria-label");
      delete el.dataset.reeling;
      running.delete(job);
    };
    job.finish = finish;
    running.add(job);

    const t0 = performance.now() + delay;
    const step = Math.max(45, Math.min(80, 520 / cells.length));
    const lockAt = cells.map((_, i) => t0 + 300 + i * step);
    const endAt = lockAt[lockAt.length - 1] + 260;
    // A 55ms timer (not requestAnimationFrame) gives the stepped arcade cadence and keeps running in
    // background tabs; the deadline below guarantees the real amount is always restored.
    const tick = () => {
      if (job.done) return;
      const now = performance.now();
      cells.forEach((d, i) => {
        if (!d.classList.contains("is-spinning")) return;
        if (now >= lockAt[i]) {
          d.textContent = d.dataset.final;
          d.classList.remove("is-spinning");
          d.classList.add("is-locked");
        } else if (now >= t0 - 120) {
          d.textContent = randDigit();
        }
      });
      if (now >= endAt) finish();
      else setTimeout(tick, 55);
    };
    setTimeout(tick, 55);
    setTimeout(finish, Math.max(0, endAt - performance.now()) + 1200);
  }

  function initCounters() {
    const els = Array.from(document.querySelectorAll("[data-count]"));
    if (!els.length) return;
    if (!motionOK() || !root.classList.contains("mx-motion")) {
      els.forEach((el) => el.classList.add("is-counted"));
      return;
    }
    const vh = window.innerHeight || document.documentElement.clientHeight;
    const later = [];
    let n = 0;
    els.forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.bottom > 0 && r.top < vh && r.width > 0) reel(el, 180 + (n++) * 90);
      else { el.classList.add("is-counted"); later.push(el); }
    });
    if (later.length && "IntersectionObserver" in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          io.unobserve(entry.target);
          reel(entry.target, 60);
        });
      }, { threshold: 0.6 });
      later.forEach((el) => io.observe(el));
    }
    const finishAll = () => running.forEach((job) => job.finish());
    window.addEventListener("beforeprint", finishAll);
    window.addEventListener("pagehide", finishAll);
  }

  // ---------- Terminal type-on page titles ----------
  function initTypeOn() {
    if (!motionOK() || !root.classList.contains("mx-motion")) return;
    const h = document.querySelector(".mx-app-main h1");
    if (!h || h.children.length || !h.textContent.trim()) return;
    const text = h.textContent.trim();
    const n = Math.max(text.length, 1);
    const dur = Math.min(900, Math.max(280, n * 38));
    const type = document.createElement("span");
    type.className = "mx-type";
    type.textContent = text;
    type.style.setProperty("--n", String(n));
    type.style.setProperty("--type-dur", dur + "ms");
    const caret = document.createElement("span");
    caret.className = "mx-caret";
    caret.setAttribute("aria-hidden", "true");
    caret.style.setProperty("--caret-off", (dur + 1900) + "ms");
    h.textContent = "";
    h.append(type, caret);
  }

  // ---------- Success pays out pixel coins ----------
  function coinBurst(from) {
    const r = from.getBoundingClientRect();
    if (!r.width) return;
    const cx = r.left + r.width / 2 - 5;
    const cy = r.top + r.height / 2 - 5;
    for (let i = 0; i < 9; i++) {
      const c = document.createElement("span");
      c.className = "mx-coin";
      c.setAttribute("aria-hidden", "true");
      const angle = (-150 + (120 / 8) * i + (Math.random() * 10 - 5)) * Math.PI / 180;
      const dist = 46 + Math.random() * 34;
      c.style.left = cx + "px";
      c.style.top = cy + "px";
      c.style.setProperty("--dx", (Math.cos(angle) * dist).toFixed(1) + "px");
      c.style.setProperty("--dy", (Math.sin(angle) * dist).toFixed(1) + "px");
      c.style.animationDelay = (i % 3) * 30 + "ms";
      c.addEventListener("animationend", () => c.remove());
      setTimeout(() => c.remove(), 1400);
      document.body.appendChild(c);
    }
  }

  function initCoins() {
    if (!motionOK() || !root.classList.contains("mx-motion")) return;
    document.querySelectorAll(".mx-alert-success").forEach((alert, i) => {
      setTimeout(() => {
        const icon = alert.querySelector("svg, i") || alert;
        coinBurst(icon);
      }, 380 + i * 160);
    });
  }

  function initBoot() {
    if (!root.classList.contains("mx-booting")) return;
    setTimeout(() => root.classList.remove("mx-booting"), 800);
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
  const crossPageTransitions = "onpagereveal" in window && typeof CSSViewTransitionRule !== "undefined";

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
          // With cross-page view transitions the old page is snapshotted, so don't dim it first.
          if (motionOK() && !crossPageTransitions) root.classList.add("mx-leaving");
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

  window.MonetraxMotion = { closeDialog, dismissAlert, motionOK, coinBurst };

  document.addEventListener("DOMContentLoaded", () => {
    initBoot();
    initTypeOn();
    initCounters();
    initParallax();
    initNavigationFeedback();
    initAlerts();
    initDialogs();
    initCoins();
  });
})();
