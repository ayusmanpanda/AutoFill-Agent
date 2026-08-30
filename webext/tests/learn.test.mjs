// Offline unit tests for the "learn from page" privacy filter in lib/perceive.js.
// Run with: node webext/tests/learn.test.mjs   (no browser, no deps)
//
// learnEntry() is the pure gate that decides whether a field's typed value may
// be captured. The security-critical guarantee it enforces: SECRET and password
// fields are NEVER turned into a payload, so their value can't be stored or sent.
import assert from "node:assert";
import { learnEntry } from "../lib/perceive.js";

let passed = 0;
const test = (name, fn) => {
  fn();
  passed++;
  console.log("  ok -", name);
};

const field = (over = {}) => ({
  field_id: "f1",
  label: "LinkedIn URL",
  name: "linkedin",
  autocomplete: null,
  placeholder: null,
  group: null,
  type: "url",
  sensitive: false,
  ...over,
});

// --- the privacy gate ---
test("secret field is never learned (returns null)", () => {
  assert.strictEqual(
    learnEntry(field({ sensitive: true, label: "CVV" }), "123"),
    null,
  );
});

test("password-type field is never learned even if not flagged", () => {
  assert.strictEqual(
    learnEntry(field({ type: "password", label: "Password" }), "hunter2"),
    null,
  );
});

test("empty value is skipped", () => {
  assert.strictEqual(learnEntry(field(), ""), null);
});

test("whitespace-only value is skipped", () => {
  assert.strictEqual(learnEntry(field(), "   "), null);
});

test("null / undefined value is skipped", () => {
  assert.strictEqual(learnEntry(field(), null), null);
  assert.strictEqual(learnEntry(field(), undefined), null);
});

test("missing field is skipped", () => {
  assert.strictEqual(learnEntry(null, "x"), null);
});

// --- the happy path ---
test("normal field produces a trimmed payload with sensitive:false", () => {
  const e = learnEntry(field(), "  https://linkedin.com/in/jo  ");
  assert.ok(e, "should return a payload");
  assert.strictEqual(e.value, "https://linkedin.com/in/jo");
  assert.strictEqual(e.sensitive, false);
  assert.strictEqual(e.label, "LinkedIn URL");
  assert.strictEqual(e.name, "linkedin");
  assert.strictEqual(e.type, "url");
});

test("carries the metadata the backend resolver needs", () => {
  const e = learnEntry(
    field({ autocomplete: "url", placeholder: "https://", group: "Links" }),
    "example.com",
  );
  assert.strictEqual(e.autocomplete, "url");
  assert.strictEqual(e.placeholder, "https://");
  assert.strictEqual(e.group, "Links");
  assert.strictEqual(e.field_id, "f1");
});

test("non-string value is coerced to a string", () => {
  const e = learnEntry(field({ type: "number", label: "Years" }), 12);
  assert.strictEqual(e.value, "12");
});

console.log(`\n${passed} learn-filter tests passed`);
