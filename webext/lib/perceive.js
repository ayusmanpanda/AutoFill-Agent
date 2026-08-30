// AutoFill Agent — form perception (ported to an ESM module for the WXT build).
//
// Reads the page's form controls into a normalized structure. It NEVER reads the
// value of any field, and flags secrets (password, OTP, CVV, card, PIN, SSN,
// bank) as sensitive so later steps leave them for manual entry.
//
// Kept as plain JS (not TS) so the pure helpers can be unit-tested with Node
// offline. The DOM-dependent code only runs inside a page.

// ---------- pure helpers (unit-testable, no DOM) ----------
export function clean(s) {
  return (s == null ? "" : String(s)).replace(/\s+/g, " ").trim();
}

export function humanize(s) {
  if (!s) return "";
  return String(s)
    .replace(/[_\-.]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2") // splitCamelCase
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, function (c) {
      return c.toUpperCase();
    });
}

export function normalizeType(tag, type) {
  tag = (tag || "").toLowerCase();
  if (tag === "select") return "select";
  if (tag === "textarea") return "textarea";
  type = (type || "text").toLowerCase();
  var SKIP = { hidden: 1, submit: 1, button: 1, image: 1, reset: 1 };
  if (SKIP[type]) return null;
  var MAP = {
    password: "password", email: "email", tel: "tel", url: "url",
    number: "number", range: "number",
    date: "date", "datetime-local": "date", month: "date", week: "date", time: "date",
    checkbox: "checkbox", radio: "radio", file: "file",
    search: "text", text: "text",
  };
  return MAP[type] || "text";
}

var SENSITIVE_RULES = [
  { re: /pass(word|wd|phrase)|\bpwd\b/i, reason: "password" },
  { re: /\botp\b|one[\s-]?time|2fa|mfa|auth(entication)?[\s-]?code|verification[\s-]?code|security[\s-]?code/i, reason: "OTP / verification code" },
  { re: /\bcvv2?\b|\bcvc\b|\bcsc\b|card[\s-]?verification/i, reason: "card security code" },
  { re: /card[\s-]?number|cardnumber|credit[\s-]?card|\bcc[\s-]?num/i, reason: "card number" },
  { re: /\bpin\b(?![\s-]?code)/i, reason: "PIN" },
  { re: /\bssn\b|social[\s-]?security/i, reason: "SSN" },
  { re: /routing[\s-]?number|account[\s-]?number|\biban\b|\bswift\b|sort[\s-]?code/i, reason: "bank account" },
];

export function classifySensitive(o) {
  o = o || {};
  if ((o.type || "") === "password") return { sensitive: true, reason: "password" };
  var ac = (o.autocomplete || "").toLowerCase();
  if (ac.indexOf("cc-") === 0 || ac === "one-time-code") {
    return { sensitive: true, reason: "payment/OTP autocomplete" };
  }
  var hay = [o.name, o.id, o.label, o.placeholder, o.autocomplete]
    .filter(Boolean)
    .join(" ")
    // Normalize snake_case/camelCase so word-anchored rules (\botp\b, \bpin\b,
    // \bssn\b) fire on names like user_otp / userOtp. Mirrors the backend.
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ");
  for (var i = 0; i < SENSITIVE_RULES.length; i++) {
    if (SENSITIVE_RULES[i].re.test(hay)) {
      return { sensitive: true, reason: SENSITIVE_RULES[i].reason };
    }
  }
  return { sensitive: false, reason: null };
}

// ---------- DOM-dependent (page only) ----------
function cssEscape(s) {
  if (typeof window !== "undefined" && window.CSS && window.CSS.escape) {
    return window.CSS.escape(s);
  }
  return String(s).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

function selectorFor(el) {
  if (el.id && document.querySelectorAll("#" + cssEscape(el.id)).length === 1) {
    return "#" + cssEscape(el.id);
  }
  var name = el.getAttribute("name");
  var tag = el.tagName.toLowerCase();
  if (name) return tag + '[name="' + cssEscape(name) + '"]';

  var parts = [];
  var node = el;
  while (node && node.nodeType === 1 && parts.length < 6) {
    if (node.id) {
      parts.unshift("#" + cssEscape(node.id));
      break;
    }
    var part = node.tagName.toLowerCase();
    var parent = node.parentElement;
    if (parent) {
      var sibs = Array.prototype.filter.call(parent.children, function (c) {
        return c.tagName === node.tagName;
      });
      if (sibs.length > 1) part += ":nth-of-type(" + (sibs.indexOf(node) + 1) + ")";
    }
    parts.unshift(part);
    node = node.parentElement;
  }
  return parts.join(" > ");
}

function labelTextExcludingControls(labelEl) {
  var clone = labelEl.cloneNode(true);
  clone.querySelectorAll("input, select, textarea, button").forEach(function (n) {
    n.remove();
  });
  return clean(clone.textContent);
}

function resolveLabel(el) {
  var alb = el.getAttribute("aria-labelledby");
  if (alb) {
    var t = alb
      .split(/\s+/)
      .map(function (id) {
        var e = document.getElementById(id);
        return e ? clean(e.textContent) : "";
      })
      .filter(Boolean)
      .join(" ");
    if (t) return { label: clean(t), source: "aria-labelledby" };
  }
  var al = el.getAttribute("aria-label");
  if (al && al.trim()) return { label: clean(al), source: "aria-label" };

  if (el.id) {
    var lf = document.querySelector('label[for="' + cssEscape(el.id) + '"]');
    if (lf && clean(lf.textContent)) return { label: clean(lf.textContent), source: "label[for]" };
  }
  var wrap = el.closest ? el.closest("label") : null;
  if (wrap) {
    var wt = labelTextExcludingControls(wrap);
    if (wt) return { label: wt, source: "wrapping-label" };
  }
  var ph = el.getAttribute("placeholder");
  if (ph && ph.trim()) return { label: clean(ph), source: "placeholder" };
  var ti = el.getAttribute("title");
  if (ti && ti.trim()) return { label: clean(ti), source: "title" };
  var base = el.getAttribute("name") || el.id;
  if (base) return { label: humanize(base), source: "name-fallback" };
  return { label: null, source: null };
}

function groupLabel(el) {
  var fs = el.closest ? el.closest("fieldset") : null;
  if (fs) {
    var lg = fs.querySelector("legend");
    if (lg && clean(lg.textContent)) return clean(lg.textContent);
  }
  return null;
}

function optionLabel(el) {
  var l = resolveLabel(el);
  return l.label || humanize(el.value || "");
}

function selectOptions(el) {
  return Array.prototype.map
    .call(el.options || [], function (o) {
      return { value: o.value, label: clean(o.textContent) };
    })
    .filter(function (o) {
      return o.value !== "" || o.label !== "";
    });
}

function maxLen(el) {
  var m = el.maxLength;
  return typeof m === "number" && m > 0 ? m : null;
}

export function perceiveForm() {
  var controls = Array.prototype.slice.call(
    document.querySelectorAll("input, select, textarea"),
  );

  // Pre-count checkbox names so shared-name checkboxes can be grouped.
  var cbNames = {};
  controls.forEach(function (el) {
    if (el.tagName === "INPUT" && (el.getAttribute("type") || "").toLowerCase() === "checkbox") {
      var n = el.getAttribute("name");
      if (n) cbNames[n] = (cbNames[n] || 0) + 1;
    }
  });

  var fields = [];
  var groupIndex = {};
  var counter = 0;

  controls.forEach(function (el) {
    var ntype = normalizeType(el.tagName, el.getAttribute("type"));
    if (!ntype) return;

    var name = el.getAttribute("name") || null;
    var domId = el.id || null;
    var autocomplete = el.getAttribute("autocomplete") || null;
    var placeholder = el.getAttribute("placeholder") || null;
    var lab = resolveLabel(el);
    var required = el.required === true || el.getAttribute("aria-required") === "true";
    var grp = groupLabel(el);

    var grouped = name && (ntype === "radio" || (ntype === "checkbox" && cbNames[name] > 1));
    if (grouped) {
      var key = ntype + "::" + name;
      if (Object.prototype.hasOwnProperty.call(groupIndex, key)) {
        var g = fields[groupIndex[key]];
        g.options.push({ value: el.value, label: optionLabel(el) });
        if (required) g.required = true;
        return;
      }
      var gsens = classifySensitive({
        type: ntype, name: name, id: domId,
        label: grp || lab.label, placeholder: placeholder, autocomplete: autocomplete,
      });
      var gfield = {
        field_id: "f" + ++counter,
        selector: el.tagName.toLowerCase() + '[name="' + cssEscape(name) + '"]',
        type: ntype,
        label: grp || lab.label || humanize(name),
        label_source: grp ? "fieldset-legend" : lab.source,
        name: name, dom_id: domId, autocomplete: autocomplete, placeholder: placeholder,
        required: required,
        group: grp,
        options: [{ value: el.value, label: optionLabel(el) }],
        sensitive: gsens.sensitive, sensitive_reason: gsens.reason,
      };
      groupIndex[key] = fields.length;
      fields.push(gfield);
      return;
    }

    var sens = classifySensitive({
      type: ntype, name: name, id: domId,
      label: lab.label, placeholder: placeholder, autocomplete: autocomplete,
    });
    fields.push({
      field_id: "f" + ++counter,
      selector: selectorFor(el),
      type: ntype,
      label: lab.label,
      label_source: lab.source,
      name: name, dom_id: domId, autocomplete: autocomplete, placeholder: placeholder,
      required: required,
      group: grp,
      options: ntype === "select" ? selectOptions(el) : [],
      max_length: maxLen(el),
      sensitive: sens.sensitive, sensitive_reason: sens.reason,
    });
  });

  return { url: location.href, title: document.title || null, fields: fields };
}

// ---------- "learn from page" value reading (SEPARATE from perceiveForm) ----------
// perceiveForm NEVER reads a value. The learn feature does — but only for
// NON-SECRET fields, and the result is used purely locally (mapped to profile
// keys on the backend, no LLM). These two paths are kept apart on purpose.

// Pure decision helper (unit-testable, no DOM): given a perceived field and the
// value read from it, return the payload to send, or null to SKIP. Secrets and
// password inputs are always skipped, so their value never leaves the page.
export function learnEntry(field, value) {
  if (!field) return null;
  if (field.sensitive) return null;         // classified secret — never learn
  if (field.type === "password") return null; // belt-and-suspenders
  var v = value == null ? "" : String(value).trim();
  if (!v) return null;                      // nothing typed
  return {
    field_id: field.field_id,
    label: field.label,
    name: field.name,
    autocomplete: field.autocomplete,
    placeholder: field.placeholder,
    group: field.group,
    type: field.type,
    sensitive: false,
    value: v,
  };
}

function readFieldValue(f) {
  // Grouped radio/checkbox: value(s) of the checked option(s).
  if ((f.type === "radio" || f.type === "checkbox") && f.name) {
    var nodes = document.querySelectorAll(
      'input[name="' + cssEscape(f.name) + '"]',
    );
    if (nodes.length) {
      var vals = [];
      Array.prototype.forEach.call(nodes, function (n) {
        if (n.checked) vals.push(n.value);
      });
      return vals.join(", ");
    }
  }
  var el = f.selector ? document.querySelector(f.selector) : null;
  if (!el) return "";
  if (el.type === "checkbox") return el.checked ? el.value || "on" : "";
  return el.value == null ? "" : String(el.value);
}

// Read the current NON-SECRET values on the page for the learn feature. Secret
// fields are filtered out by learnEntry, so readFieldValue is never even called
// on them here.
export function readValues() {
  var form = perceiveForm();
  var out = [];
  (form.fields || []).forEach(function (f) {
    if (f.sensitive || f.type === "password") return; // don't touch secrets
    var entry = learnEntry(f, readFieldValue(f));
    if (entry) out.push(entry);
  });
  return { url: form.url, title: form.title, fields: out };
}
