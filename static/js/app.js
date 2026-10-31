(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const closeDialog = (d) => (window.MonetraxMotion ? window.MonetraxMotion.closeDialog(d) : d.close());

  function initSidebar() {
    const sidebar = $("#sidebar");
    const scrim = $("[data-sidebar-scrim]");
    const openBtn = $("[data-sidebar-open]");
    if (!sidebar || !openBtn) return;

    const setOpen = (open) => {
      sidebar.classList.toggle("is-open", open);
      scrim.hidden = !open;
      openBtn.setAttribute("aria-expanded", String(open));
      document.body.style.overflow = open ? "hidden" : "";
      if (open) { const first = sidebar.querySelector("a, button"); if (first) first.focus(); }
      else openBtn.focus();
    };
    openBtn.addEventListener("click", () => setOpen(true));
    $$("[data-sidebar-close]").forEach((b) => b.addEventListener("click", () => setOpen(false)));
    scrim.addEventListener("click", () => setOpen(false));
    sidebar.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && sidebar.classList.contains("is-open")) setOpen(false);
    });
    window.matchMedia("(min-width: 1024px)").addEventListener("change", (e) => {
      if (e.matches && sidebar.classList.contains("is-open")) {
        sidebar.classList.remove("is-open"); scrim.hidden = true; document.body.style.overflow = "";
      }
    });
  }

  function initConfirm() {
    const dialog = $("#confirm-dialog");
    if (!dialog || typeof dialog.showModal !== "function") return;
    let pending = null;
    document.addEventListener("submit", (e) => {
      const form = e.target;
      if (!form.matches("form[data-confirm]") || form.dataset.confirmed === "1") return;
      e.preventDefault();
      pending = form;
      $("[data-confirm-title]", dialog).textContent = form.dataset.confirmTitle || "Are you sure?";
      $("[data-confirm-text]", dialog).textContent = form.dataset.confirm;
      $("[data-confirm-ok]", dialog).textContent = form.dataset.confirmOk || "Delete";
      dialog.showModal();
      $("[data-confirm-cancel]", dialog).focus();
    });
    $("[data-confirm-ok]", dialog).addEventListener("click", () => {
      if (!pending) return;
      const form = pending;
      form.dataset.confirmed = "1";
      closeDialog(dialog);
      form.requestSubmit ? form.requestSubmit() : form.submit();
    });
    $("[data-confirm-cancel]", dialog).addEventListener("click", () => closeDialog(dialog));
    dialog.addEventListener("click", (e) => { if (e.target === dialog) closeDialog(dialog); });
    dialog.addEventListener("close", () => { pending = null; });
  }

  function initAutoSubmit() {
    $$("form[data-autosubmit]").forEach((form) => {
      form.addEventListener("change", (e) => {
        if (e.target.matches("select, input[type=date]")) form.requestSubmit ? form.requestSubmit() : form.submit();
      });
    });
    const range = $("form[data-range-form]");
    if (range) {
      const custom = $("[data-custom-range]", range);
      range.addEventListener("change", (e) => {
        if (e.target.name !== "range") return;
        if (e.target.value === "custom") { custom.hidden = false; $("input", custom).focus(); return; }
        custom.hidden = true;
        $$("input[type=date]", custom).forEach((i) => { i.disabled = true; });
        range.submit();
      });
    }
    $$("[data-print]").forEach((b) => b.addEventListener("click", () => window.print()));
  }

  function initTransactionForm() {
    const form = $("form[data-tx-form]");
    if (!form) return;
    const select = $("[data-category-select]", form);
    const radios = $$('input[name="type"]', form);
    const sync = () => {
      const type = (radios.find((r) => r.checked) || {}).value;
      let selectedStillValid = false;
      $$("option", select).forEach((opt) => {
        if (!opt.value) return;
        const match = opt.dataset.type === type;
        opt.hidden = !match;
        opt.disabled = !match;
        if (match && opt.selected) selectedStillValid = true;
      });
      if (!selectedStillValid) select.value = "";
    };
    const walletLabel = $("#wallet-label", form);
    const syncLabel = () => {
      if (!walletLabel) return;
      const type = (radios.find((r) => r.checked) || {}).value;
      walletLabel.textContent = type === "income" ? walletLabel.dataset.labelIncome : walletLabel.dataset.labelExpense;
    };
    radios.forEach((r) => r.addEventListener("change", () => { sync(); syncLabel(); }));
    sync();
    syncLabel();
  }

  function initWalletForm() {
    const form = $("form[data-wallet-form]");
    if (!form) return;
    const name = $("[data-wallet-name]", form);
    const color = $("[data-wallet-color]", form);
    // Picking a type (on add or edit) fills the name; the saved name is only replaced when the type is changed.
    let colorTouched = false;
    if (color) color.addEventListener("input", () => { colorTouched = true; });
    $$('input[name="type"]', form).forEach((r) => r.addEventListener("change", () => {
      if (!r.checked) return;
      if (name && r.dataset.defaultName) {
        name.value = r.dataset.defaultName;
        name.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (color && !colorTouched && r.dataset.color) color.value = r.dataset.color;
    }));
  }

  function initMoney() {
    $$("input[data-money]").forEach((input) => {
      input.addEventListener("input", () => {
        const clean = input.value.replace(/[^\d.,]/g, "");
        if (clean !== input.value) input.value = clean;
      });
      input.addEventListener("blur", () => {
        const n = parseFloat(input.value.replace(/,/g, ""));
        if (!Number.isNaN(n) && n > 0) input.value = n.toFixed(2);
      });
    });
  }

  let COLORS = {};
  function readColors() {
    const css = getComputedStyle(document.documentElement);
    const v = (name) => css.getPropertyValue(name).trim();
    COLORS = { income: v("--chart-income"), expense: v("--chart-expense"), line: v("--chart-line"),
               grid: v("--chart-grid"), ink: v("--chart-tick"), tooltip: v("--chart-tooltip"), surface: v("--surface"),
               frame: v("--px-line") || v("--chart-expense") };
  }

  function money(v) {
    const sym = document.body.dataset.currency || "₱";
    return sym + Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  let animateCharts = !reduceMotion;

  function baseOptions(extra = {}) {
    return Object.assign({
      responsive: true,
      maintainAspectRatio: false,
      animation: animateCharts ? { duration: 900, easing: "easeOutQuart" } : false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: COLORS.tooltip, padding: 12, cornerRadius: 0, titleFont: { weight: "400", size: 18 },
          bodyFont: { size: 17 }, borderColor: COLORS.income, borderWidth: 2,
          caretSize: 6, displayColors: true, boxPadding: 4, usePointStyle: true,
          animation: { duration: 180, easing: "easeOutQuad" },
          callbacks: { label: (ctx) => ` ${ctx.dataset.label || ctx.label}: ${money(ctx.parsed.y ?? ctx.parsed)}` }
        }
      },
      scales: {
        x: { grid: { display: false }, border: { color: COLORS.frame, width: 3 },
             ticks: { color: COLORS.ink, maxRotation: 0, autoSkipPadding: 12 } },
        y: { beginAtZero: true, grid: { color: COLORS.grid, lineWidth: 2 }, border: { display: false, dash: [4, 4] },
             ticks: { color: COLORS.ink, callback: (v) => money(v), maxTicksLimit: 6 } }
      }
    }, extra);
  }

  const staggered = (step, perDataset) => (ctx) =>
    ctx.type === "data" && ctx.mode === "default" ? ctx.dataIndex * step + ctx.datasetIndex * perDataset : 0;

  const builders = {
    incomeExpense: (d) => ({
      type: "bar",
      data: { labels: d.labels, datasets: [
        { label: "Income", data: d.income, backgroundColor: COLORS.income, borderRadius: 0, maxBarThickness: 28,
          borderColor: COLORS.frame, borderWidth: 2, borderSkipped: "bottom", hoverBackgroundColor: COLORS.line,
          pointStyle: "rect" },
        { label: "Expenses", data: d.expense, backgroundColor: COLORS.expense, borderRadius: 0, maxBarThickness: 28,
          borderColor: COLORS.frame, borderWidth: 2, borderSkipped: "bottom", pointStyle: "rect" }
      ] },
      options: baseOptions({
        animation: animateCharts
          ? { duration: 900, easing: "easeOutBack", delay: staggered(Math.max(24, 420 / Math.max(d.labels.length, 1)), 90) }
          : false
      })
    }),
    flow: (d) => builders.incomeExpense(d),
    trend: (d, canvas) => {
      const ctx = canvas.getContext("2d");
      const grad = ctx.createLinearGradient(0, 0, 0, canvas.parentElement.clientHeight || 240);
      grad.addColorStop(0, "rgba(16,185,129,.28)");
      grad.addColorStop(1, "rgba(16,185,129,0)");
      const step = Math.max(8, 700 / Math.max(d.values.length, 1));
      return {
        type: "line",
        data: { labels: d.labels, datasets: [{
          label: "Spent", data: d.values, borderColor: COLORS.line, backgroundColor: grad, fill: true,
          stepped: "middle", tension: 0, borderWidth: 3, pointRadius: 0, pointStyle: "rect", pointHoverRadius: 6,
          pointHoverBackgroundColor: COLORS.line, pointHoverBorderColor: COLORS.frame, pointHoverBorderWidth: 2
        }] },
        options: baseOptions({
          animation: animateCharts ? { duration: 800, easing: "easeOutCubic", delay: staggered(step, 0) } : false
        })
      };
    },
    hbar: (d, label) => {
      const opts = baseOptions({
        indexAxis: "y",
        animation: animateCharts
          ? { duration: 800, easing: "easeOutQuart", delay: staggered(Math.max(40, 400 / Math.max(d.labels.length, 1)), 0) }
          : false
      });
      opts.interaction = { mode: "nearest", axis: "y", intersect: false };
      opts.scales = {
        x: { beginAtZero: true, grid: { color: COLORS.grid, lineWidth: 2 }, border: { display: false },
             ticks: { color: COLORS.ink, callback: (v) => money(v), maxTicksLimit: 5 } },
        y: { grid: { display: false }, border: { color: COLORS.frame, width: 3 }, ticks: { color: COLORS.ink } }
      };
      opts.plugins.tooltip.callbacks = { label: (ctx) => ` ${label}: ${money(ctx.parsed.x)}` };
      return {
        type: "bar",
        data: { labels: d.labels, datasets: [{ label, data: d.values, backgroundColor: d.colors, borderColor: COLORS.frame,
                                              borderWidth: 2, borderRadius: 0, maxBarThickness: 26, pointStyle: "rect" }] },
        options: opts
      };
    },
    wallets: (d) => builders.hbar(d, "Balance"),
    topCategories: (d) => builders.hbar(d, "Spent"),
    savings: (d) => {
      const gold = getComputedStyle(document.documentElement).getPropertyValue("--gold").trim() || "#E0A100";
      return {
        type: "bar",
        data: { labels: d.labels, datasets: [
          { type: "bar", label: "Net saved", data: d.net, order: 2, borderRadius: 0, maxBarThickness: 28,
            backgroundColor: d.net.map((v) => (v < 0 ? COLORS.expense : COLORS.income)),
            borderColor: COLORS.frame, borderWidth: 2, pointStyle: "rect" },
          { type: "line", label: "In savings goals", data: d.goal_total, order: 1, borderColor: gold,
            backgroundColor: gold, borderWidth: 3, stepped: "middle", pointRadius: 3, pointStyle: "rect",
            pointHoverRadius: 6, tension: 0 }
        ] },
        options: baseOptions({
          animation: animateCharts
            ? { duration: 900, easing: "easeOutQuart", delay: staggered(Math.max(30, 420 / Math.max(d.labels.length, 1)), 120) }
            : false
        })
      };
    },
    categories: (d) => ({
      type: "doughnut",
      data: { labels: d.labels, datasets: [{ data: d.values, backgroundColor: d.colors, borderWidth: 0,
                                            hoverOffset: 6, borderRadius: 0, spacing: 0 }] },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: "64%", devicePixelRatio: 0.25,
        animation: animateCharts
          ? { duration: 1200, easing: "easeOutQuart", animateRotate: true, animateScale: true }
          : false,
        plugins: { legend: { display: false },
          tooltip: { enabled: false, backgroundColor: COLORS.tooltip, padding: 12, cornerRadius: 0,
                     titleFont: { weight: "400", size: 18 }, bodyFont: { size: 17 },
                     animation: { duration: 180, easing: "easeOutQuad" },
                     callbacks: { label: (ctx) => ` ${ctx.label}: ${money(ctx.parsed)}` } } }
      }
    })
  };

  const charts = new Map();
  let chartData = null;

  function readChartData() {
    const cache = {};
    $$("canvas[data-chart]").forEach((canvas) => {
      const src = canvas.dataset.source;
      if (cache[src] !== undefined) return;
      const el = document.getElementById(src);
      try { cache[src] = el ? JSON.parse(el.textContent) : {}; } catch (_) { cache[src] = {}; }
    });
    return cache;
  }

  function drawChart(canvas) {
    if (!window.Chart || charts.has(canvas)) return;
    const data = (chartData[canvas.dataset.source] || {})[canvas.dataset.chart];
    const build = builders[canvas.dataset.chart];
    if (!data || !build) return;
    if (canvas.dataset.chart === "categories") canvas.classList.add("px-chunky");
    charts.set(canvas, new Chart(canvas, build(data, canvas)));
    canvas.classList.add("is-ready");
  }

  function setupChartDefaults() {
    Chart.defaults.font.family = 'VT323, ui-monospace, monospace';
    Chart.defaults.font.size = 16;
    readColors();
    Chart.defaults.color = COLORS.ink;
  }

  function initCharts() {
    if (!window.Chart) return;
    setupChartDefaults();
    chartData = readChartData();
    const canvases = $$("canvas[data-chart]");
    if (!("IntersectionObserver" in window) || !animateCharts) {
      canvases.forEach(drawChart);
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        io.unobserve(entry.target);
        drawChart(entry.target);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.15 });
    canvases.forEach((c) => io.observe(c));
    window.addEventListener("beforeprint", () => {
      const was = animateCharts;
      animateCharts = false;
      canvases.forEach(drawChart);
      animateCharts = was;
    });
  }

  function redrawCharts() {
    if (!window.Chart || !chartData) return;
    const was = animateCharts;
    animateCharts = false;
    setupChartDefaults();
    Array.from(charts.keys()).forEach((canvas) => {
      charts.get(canvas).destroy();
      charts.delete(canvas);
      drawChart(canvas);
    });
    animateCharts = was;
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (window.lucide) window.lucide.createIcons();
    initSidebar();
    initConfirm();
    initAutoSubmit();
    initTransactionForm();
    initWalletForm();
    initMoney();
    initCharts();
  });

  document.addEventListener("mx-theme-change", redrawCharts);
})();
