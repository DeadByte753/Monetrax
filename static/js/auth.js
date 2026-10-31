(() => {
  "use strict";

  const EMAIL_RE = /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$/;
  const SCHOOL_RE = /(^|\.)edu(\.[a-z]{2})?$/i;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const renderIcons = () => window.lucide && window.lucide.createIcons();

  const rules = {
    email(value, form) {
      const v = value.trim().toLowerCase();
      if (!v) return "Enter your email address.";
      if (v.length > 254 || !EMAIL_RE.test(v)) return "Enter a valid email address, like name@school.edu.ph.";
      if (form.dataset.authForm === "register" && form.dataset.requireSchool === "true" &&
          !SCHOOL_RE.test(v.split("@").pop())) {
        return "Use your school email (it usually ends in .edu or .edu.ph).";
      }
      return "";
    },
    password(value, form) {
      if (form.dataset.authForm === "login") return value ? "" : "Enter your password.";
      if (!value) return "Create a password.";
      if (value.length < 8) return "Use at least 8 characters.";
      if (value.length > 128) return "Use at most 128 characters.";
      if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) return "Include at least one letter and one number.";
      return "";
    },
    confirm_password(value, form) {
      const pw = form.querySelector("#f-password").value;
      if (!value) return "Re-enter your password.";
      if (value !== pw) return "Passwords don't match.";
      return "";
    },
    full_name(value) {
      const v = value.trim().replace(/\s+/g, " ");
      if (!v) return "Enter your full name.";
      if (v.length < 2 || !/[A-Za-z]/.test(v)) return "Enter your full name as it appears on your school ID.";
      if (v.length > 80) return "Keep your name under 80 characters.";
      return "";
    },
    terms(_v, _f, input) {
      return input.checked ? "" : "Please accept the Terms and Conditions to continue.";
    }
  };

  const fieldOf = (input) => input.closest(".mx-field");

  function setError(input, message) {
    const field = fieldOf(input);
    if (!field) return;
    const errorEl = field.querySelector(".mx-error");
    const textEl = errorEl && errorEl.querySelector("[data-error-text]");
    field.classList.toggle("has-error", !!message);
    input.setAttribute("aria-invalid", message ? "true" : "false");
    if (errorEl && textEl) {
      textEl.textContent = message || "";
      errorEl.hidden = !message;
    }
  }

  function validateInput(input, form, { showValid = false } = {}) {
    const rule = rules[input.name];
    if (!rule) return true;
    const value = input.type === "checkbox" ? "" : input.value;
    const message = rule(value, form, input);
    setError(input, message);
    const field = fieldOf(input);
    if (field && input.type !== "checkbox") {
      field.classList.toggle("is-valid", showValid && !message && value !== "");
    }
    return !message;
  }

  function initPasswordToggles(root) {
    root.querySelectorAll("[data-toggle-password]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const input = document.getElementById(btn.dataset.togglePassword);
        if (!input) return;
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        btn.setAttribute("aria-pressed", String(show));
        btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
        btn.querySelector('[data-eye="show"]').hidden = show;
        btn.querySelector('[data-eye="hide"]').hidden = !show;

        const pos = input.value.length;
        input.focus();
        try { input.setSelectionRange(pos, pos); } catch (_) {}
      });
    });
  }

  function initStrength(form) {
    const meterWrap = form.querySelector("[data-strength-for]");
    if (!meterWrap) return;
    const input = document.getElementById(meterWrap.dataset.strengthFor);
    const meter = meterWrap.querySelector(".mx-meter");
    const label = meterWrap.querySelector("[data-strength-label]");
    const reqs = {
      length: meterWrap.querySelector('[data-rule="length"]'),
      number: meterWrap.querySelector('[data-rule="number"]'),
      case: meterWrap.querySelector('[data-rule="case"]')
    };
    const names = ["", "Weak", "Fair", "Good", "Strong"];

    const update = () => {
      const v = input.value;
      meterWrap.hidden = v.length === 0;
      const checks = {
        length: v.length >= 8,
        number: /\d/.test(v),
        case: /[a-z]/.test(v) && /[A-Z]/.test(v)
      };
      Object.entries(checks).forEach(([k, ok]) => reqs[k].classList.toggle("is-met", ok));
      let score = Object.values(checks).filter(Boolean).length + (/[^A-Za-z0-9]/.test(v) ? 1 : 0);
      if (v.length > 0 && score === 0) score = 1;
      if (v.length >= 12 && score >= 3) score = 4;
      score = Math.min(score, 4);
      meter.dataset.level = String(score);
      label.textContent = v ? `Strength: ${names[score]}` : "";
    };
    input.addEventListener("input", update);
    update();
  }

  function initMatchHint(form) {
    const confirm = form.querySelector("[data-match]");
    if (!confirm) return;
    const source = document.getElementById(confirm.dataset.match);
    const hint = fieldOf(confirm).querySelector(".mx-hint");
    const update = () => {
      if (!hint) return;
      const ok = confirm.value !== "" && confirm.value === source.value;
      hint.classList.toggle("is-ok", ok);
      hint.textContent = ok ? "Passwords match." : hint.dataset.hintDefault;
    };
    confirm.addEventListener("input", update);
    source.addEventListener("input", update);
    update();
  }

  function setLoading(button, loading) {
    if (!button) return;
    button.setAttribute("aria-busy", loading ? "true" : "false");
    button.disabled = loading;
    button.querySelector(".mx-btn-idle").hidden = loading;
    button.querySelector(".mx-btn-busy").hidden = !loading;
  }

  function initForm(form) {
    const inputs = Array.from(form.querySelectorAll("input")).filter((el) => rules[el.name]);
    const submit = form.querySelector('button[type="submit"]');
    let attempted = false;

    if (form.querySelector(".mx-field.has-error")) attempted = true;

    inputs.forEach((input) => {
      const evt = input.type === "checkbox" ? "change" : "input";
      input.addEventListener(evt, () => {
        const field = fieldOf(input);
        if (attempted || (field && field.classList.contains("has-error"))) {
          validateInput(input, form, { showValid: true });
        }

        if (input.name === "password") {
          const confirm = form.querySelector('[name="confirm_password"]');
          if (confirm && confirm.value && (attempted || fieldOf(confirm).classList.contains("has-error"))) {
            validateInput(confirm, form, { showValid: true });
          }
        }

        const formAlert = form.parentElement.querySelector(".mx-alert-error");
        if (formAlert && input.type !== "checkbox") formAlert.remove();
      });
      if (input.type !== "checkbox") {
        input.addEventListener("blur", () => {
          if (input.value.trim() !== "") validateInput(input, form, { showValid: true });
        });
      }
    });

    form.addEventListener("submit", (event) => {
      attempted = true;
      if (submit && submit.getAttribute("aria-busy") === "true") {
        event.preventDefault();
        return;
      }
      const invalid = inputs.filter((input) => !validateInput(input, form, { showValid: true }));
      if (invalid.length) {
        event.preventDefault();
        invalid[0].focus();
        const card = form.closest(".mx-card");
        if (card && !reduceMotion) {
          card.classList.remove("is-shaking");
          void card.offsetWidth;
          card.classList.add("is-shaking");
        }
        return;
      }
      setLoading(submit, true);
    });

    initStrength(form);
    initMatchHint(form);
  }

  function initTransitions() {
    const panel = document.querySelector(".mx-panel");
    document.querySelectorAll("a[data-transition]").forEach((link) => {
      link.addEventListener("click", (event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
        let href = link.href;

        if (link.hasAttribute("data-carry-email")) {
          const email = document.querySelector('#f-email');
          if (email && email.value.trim()) {
            const url = new URL(href);
            url.searchParams.set("email", email.value.trim());
            href = url.toString();
          }
        }

        if (reduceMotion || !panel) {
          if (href !== link.href) { event.preventDefault(); window.location.href = href; }
          return;
        }
        event.preventDefault();
        const tabs = document.querySelector(".mx-tabs");
        if (tabs && link.dataset.tab) tabs.dataset.active = link.dataset.tab;
        panel.classList.add("is-leaving");
        window.setTimeout(() => { window.location.href = href; }, tabs && link.dataset.tab ? 240 : 180);
      });
    });

    window.addEventListener("pageshow", (event) => {
      if (!event.persisted) return;
      if (panel) panel.classList.remove("is-leaving");
      document.querySelectorAll('.mx-btn[aria-busy="true"]').forEach((b) => setLoading(b, false));
      const tabs = document.querySelector(".mx-tabs");
      const current = document.querySelector(".mx-tab[aria-current='page']");
      if (tabs && current) tabs.dataset.active = current.dataset.tab;
    });
  }

  const closeDialog = (d) => (window.MonetraxMotion ? window.MonetraxMotion.closeDialog(d) : d.close());

  function initDialog() {
    document.querySelectorAll("[data-open-dialog]").forEach((btn) => {
      const dialog = document.getElementById(btn.dataset.openDialog);
      if (!dialog || typeof dialog.showModal !== "function") return;
      btn.addEventListener("click", () => dialog.showModal());
    });
    document.querySelectorAll("dialog").forEach((dialog) => {
      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) closeDialog(dialog);
      });
      dialog.querySelectorAll("[data-close-dialog]").forEach((b) => b.addEventListener("click", () => closeDialog(dialog)));
      const accept = dialog.querySelector("[data-accept-terms]");
      if (accept) {
        accept.addEventListener("click", () => {
          const terms = document.getElementById("f-terms");
          if (terms) {
            terms.checked = true;
            terms.dispatchEvent(new Event("change", { bubbles: true }));
            validateInput(terms, terms.form);
          }
          if (terms) dialog.addEventListener("close", () => terms.focus(), { once: true });
          closeDialog(dialog);
        });
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    renderIcons();
    initPasswordToggles(document);
    document.querySelectorAll("form[data-auth-form]").forEach(initForm);
    initTransitions();
    initDialog();

    const firstError = document.querySelector('.mx-field.has-error input');
    if (firstError) firstError.focus();
  });
})();
