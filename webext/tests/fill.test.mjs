// Offline unit tests for lib/fill.js — the DOM-mutation core.
// Run with: node webext/tests/fill.test.mjs   (no browser, no deps)
//
// We fake just enough of a DOM element to exercise the React-controlled-input
// path (native prototype setter + _valueTracker nudge) and event dispatch.
import assert from "node:assert";
import {
  isFillable,
  setNativeValue,
  applyField,
  applyPlan,
} from "../lib/fill.js";

let passed = 0;
const test = (name, fn) => {
  fn();
  passed++;
  console.log("  ok -", name);
};

// A text/select element whose `value` lives on the prototype (like a real
// HTMLInputElement), so setNativeValue must go through the prototype setter.
class FakeInput {
  constructor({ value = "", options = null } = {}) {
    this._value = String(value);
    this.events = [];
    this.trackerCalls = [];
    this._valueTracker = { setValue: (v) => this.trackerCalls.push(v) };
    if (options) this.options = options;
  }
  get value() {
    return this._value;
  }
  set value(v) {
    this._value = String(v);
  }
  dispatchEvent(ev) {
    this.events.push(ev.type);
    return true;
  }
}

function radioNode(value) {
  return {
    value,
    checked: false,
    events: [],
    dispatchEvent(ev) {
      this.events.push(ev.type);
      return true;
    },
  };
}

function rootWith(map) {
  return {
    querySelectorAll(sel) {
      return map[sel] ? map[sel].slice() : [];
    },
  };
}

// ---------------------------------------------------------------------------
test("isFillable accepts a plain SAFE fill record", () => {
  assert.strictEqual(
    isFillable({ action: "fill", sensitivity: "SAFE", value: "Ada" }),
    true,
  );
});

test("isFillable rejects secrets, manual/generate/unmapped, and empties", () => {
  assert.strictEqual(
    isFillable({ action: "fill", sensitivity: "SECRET", value: "hunter2" }),
    false,
    "SECRET must never fill",
  );
  assert.strictEqual(
    isFillable({ action: "fill", sensitive: true, value: "x" }),
    false,
    "sensitive:true must never fill",
  );
  assert.strictEqual(isFillable({ action: "manual_entry", value: "x" }), false);
  assert.strictEqual(isFillable({ action: "generate", value: "x" }), false);
  assert.strictEqual(isFillable({ action: "unmapped" }), false);
  assert.strictEqual(isFillable({ action: "fill", value: "" }), false);
  assert.strictEqual(isFillable({ action: "fill", value: null }), false);
  assert.strictEqual(isFillable(null), false);
});

test("setNativeValue uses the prototype setter and nudges _valueTracker", () => {
  const el = new FakeInput({ value: "old" });
  setNativeValue(el, "new");
  assert.strictEqual(el.value, "new", "value set through prototype setter");
  assert.deepStrictEqual(
    el.trackerCalls,
    ["old"],
    "React _valueTracker nudged with the previous value",
  );
});

test("applyField fills a text input and fires input/change/blur", () => {
  const el = new FakeInput({ value: "" });
  const root = rootWith({ "#name": [el] });
  const status = applyField(
    { action: "fill", sensitivity: "SAFE", type: "text", selector: "#name", value: "Ada Lovelace" },
    root,
  );
  assert.strictEqual(status, "filled");
  assert.strictEqual(el.value, "Ada Lovelace");
  assert.deepStrictEqual(el.events, ["input", "change", "blur"]);
});

test("applyField select matches by option value", () => {
  const el = new FakeInput({
    value: "",
    options: [
      { value: "us", textContent: "United States" },
      { value: "gb", textContent: "United Kingdom" },
    ],
  });
  const root = rootWith({ "#country": [el] });
  const status = applyField(
    { action: "fill", sensitivity: "SAFE", type: "select", selector: "#country", value: "gb" },
    root,
  );
  assert.strictEqual(status, "filled");
  assert.strictEqual(el.value, "gb");
  assert.deepStrictEqual(el.events, ["input", "change"]);
});

test("applyField select falls back to matching by visible label", () => {
  const el = new FakeInput({
    value: "",
    options: [
      { value: "us", textContent: "United States" },
      { value: "gb", textContent: "United Kingdom" },
    ],
  });
  const root = rootWith({ "#country": [el] });
  const status = applyField(
    { action: "fill", sensitivity: "SAFE", type: "select", selector: "#country", value: "United Kingdom" },
    root,
  );
  assert.strictEqual(status, "filled");
  assert.strictEqual(el.value, "gb", "label 'United Kingdom' resolved to value 'gb'");
});

test("applyField select returns no_option when nothing matches", () => {
  const el = new FakeInput({
    value: "",
    options: [{ value: "us", textContent: "United States" }],
  });
  const root = rootWith({ "#country": [el] });
  const status = applyField(
    { action: "fill", sensitivity: "SAFE", type: "select", selector: "#country", value: "Atlantis" },
    root,
  );
  assert.strictEqual(status, "no_option");
});

test("applyField radio checks the matching option and fires events", () => {
  const yes = radioNode("yes");
  const no = radioNode("no");
  const root = rootWith({ 'input[name="auth"]': [yes, no] });
  const status = applyField(
    { action: "fill", sensitivity: "SAFE", type: "radio", selector: 'input[name="auth"]', value: "yes" },
    root,
  );
  assert.strictEqual(status, "filled");
  assert.strictEqual(yes.checked, true);
  assert.strictEqual(no.checked, false);
  assert.deepStrictEqual(yes.events, ["input", "change", "click"]);
});

test("applyField radio returns no_option when no value matches", () => {
  const a = radioNode("a");
  const root = rootWith({ 'input[name="pick"]': [a] });
  const status = applyField(
    { action: "fill", sensitivity: "SAFE", type: "radio", selector: 'input[name="pick"]', value: "z" },
    root,
  );
  assert.strictEqual(status, "no_option");
});

test("applyField skips sensitive/secret/manual records without touching the DOM", () => {
  const el = new FakeInput({ value: "" });
  const root = rootWith({ "#pw": [el] });
  const secret = applyField(
    { action: "fill", sensitivity: "SECRET", type: "password", selector: "#pw", value: "hunter2" },
    root,
  );
  assert.strictEqual(secret, "skipped");
  assert.strictEqual(el.value, "", "secret value must never be written");
  assert.deepStrictEqual(el.events, [], "no events fired for a secret");
});

test("applyField returns not_found for a missing selector or missing node", () => {
  const root = rootWith({});
  assert.strictEqual(
    applyField({ action: "fill", sensitivity: "SAFE", type: "text", selector: "#nope", value: "x" }, root),
    "not_found",
  );
  assert.strictEqual(
    applyField({ action: "fill", sensitivity: "SAFE", type: "text", value: "x" }, root),
    "not_found",
    "no selector -> not_found",
  );
});

test("applyPlan aggregates a report and never fills secrets", () => {
  const name = new FakeInput({ value: "" });
  const pw = new FakeInput({ value: "" });
  const root = rootWith({ "#name": [name], "#pw": [pw] });
  const plan = {
    fields: [
      { field_id: "f1", action: "fill", sensitivity: "SAFE", type: "text", selector: "#name", value: "Ada" },
      { field_id: "f2", action: "manual_entry", sensitivity: "SECRET", type: "password", selector: "#pw", value: "" },
      { field_id: "f3", action: "fill", sensitivity: "SAFE", type: "text", selector: "#missing", value: "x" },
      { field_id: "f4", action: "unmapped" },
    ],
  };
  const report = applyPlan(plan, root);
  assert.deepStrictEqual(report.filled, ["f1"]);
  assert.deepStrictEqual(report.not_found, ["f3"]);
  assert.ok(report.skipped.includes("f2") && report.skipped.includes("f4"));
  assert.deepStrictEqual(report.counts, { filled: 1, skipped: 2, not_found: 1, no_option: 0 });
  assert.strictEqual(pw.value, "", "secret field left untouched");
});

console.log(`\nfill.js: ${passed} passed`);
