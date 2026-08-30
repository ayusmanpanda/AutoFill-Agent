// AutoFill Agent — apply a fill plan to the live DOM (Phase 6).
//
// Human-in-the-loop by design: this writes values into fields but NEVER submits
// the form. It fills only records the backend marked action "fill" (which
// includes generated answers, via "generated"), and refuses anything sensitive
// as defense in depth — secrets are always left for manual entry.
//
// The mutation core is isolated and framework-agnostic so it can be unit-tested
// with a fake element in Node, without a browser.

// A record is auto-fillable only if the backend said "fill", it isn't a secret,
// and it actually carries a value. manual_entry / unmapped / generate never fill.
export function isFillable(rec) {
  return (
    !!rec &&
    rec.action === "fill" &&
    rec.sensitivity !== "SECRET" &&
    rec.sensitive !== true &&
    rec.value != null &&
    String(rec.value) !== ""
  );
}

// Controlled React/Vue inputs ignore `el.value = x` because the framework holds
// its own copy of the value. Call the native prototype setter and reset React's
// internal value tracker so its onChange fires on the following input event.
export function setNativeValue(el, value) {
  const proto = Object.getPrototypeOf(el) || {};
  const protoDesc = Object.getOwnPropertyDescriptor(proto, "value");
  const ownDesc = Object.getOwnPropertyDescriptor(el, "value");
  const protoSetter = protoDesc && protoDesc.set;
  const ownSetter = ownDesc && ownDesc.set;
  const prev = el.value;

  if (protoSetter && ownSetter !== protoSetter) {
    protoSetter.call(el, value);
  } else if (ownSetter) {
    ownSetter.call(el, value);
  } else {
    el.value = value;
  }

  // React attaches a _valueTracker; nudging it with the previous value makes
  // React notice the change and dispatch its synthetic onChange.
  if (el._valueTracker && typeof el._valueTracker.setValue === "function") {
    el._valueTracker.setValue(prev);
  }
}

function fire(el, type) {
  el.dispatchEvent(new Event(type, { bubbles: true }));
}

// Apply one plan record against a DOM root. Returns a status string:
// "filled" | "skipped" | "not_found" | "no_option".
export function applyField(rec, root) {
  root = root || (typeof document !== "undefined" ? document : null);
  if (!isFillable(rec)) return "skipped";
  if (!root || !rec.selector) return "not_found";

  const nodes = root.querySelectorAll(rec.selector);
  if (!nodes || nodes.length === 0) return "not_found";

  const type = rec.type;
  const value = String(rec.value);

  // Radio / checkbox groups: check the option whose value matches.
  if (type === "radio" || type === "checkbox") {
    let hit = null;
    nodes.forEach(function (n) {
      if (String(n.value) === value) hit = n;
    });
    if (!hit) return "no_option";
    if (!hit.checked) {
      hit.checked = true;
      fire(hit, "input");
      fire(hit, "change");
      fire(hit, "click");
    }
    return "filled";
  }

  const el = nodes[0];

  // Selects: match by option value, else by visible label.
  if (type === "select") {
    let matched = value;
    const opts = Array.prototype.slice.call(el.options || []);
    const hasValue = opts.some(function (o) {
      return String(o.value) === value;
    });
    if (!hasValue) {
      const byLabel = opts.find(function (o) {
        return (o.textContent || "").trim() === value;
      });
      if (byLabel) matched = byLabel.value;
      else return "no_option";
    }
    setNativeValue(el, matched);
    fire(el, "input");
    fire(el, "change");
    return "filled";
  }

  // Text-like: text / email / tel / url / number / date / textarea.
  setNativeValue(el, value);
  fire(el, "input");
  fire(el, "change");
  fire(el, "blur");
  return "filled";
}

// Apply a whole plan. Returns a report of what happened, so the popup can show
// the user exactly which fields were written and which were left alone.
export function applyPlan(plan, root) {
  const report = { filled: [], skipped: [], not_found: [], no_option: [] };
  const fields = (plan && plan.fields) || [];

  for (const rec of fields) {
    if (!isFillable(rec)) {
      report.skipped.push(rec.field_id);
      continue;
    }
    let status;
    try {
      status = applyField(rec, root);
    } catch (e) {
      status = "not_found";
    }
    if (status === "filled") report.filled.push(rec.field_id);
    else if (status === "no_option") report.no_option.push(rec.field_id);
    else if (status === "not_found") report.not_found.push(rec.field_id);
    else report.skipped.push(rec.field_id);
  }

  report.counts = {
    filled: report.filled.length,
    skipped: report.skipped.length,
    not_found: report.not_found.length,
    no_option: report.no_option.length,
  };
  return report;
}
