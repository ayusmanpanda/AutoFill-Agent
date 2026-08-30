// Offline unit tests for lib/perceive.js — the pure, DOM-free helpers.
// Run with: node webext/tests/perceive.test.mjs
//
// perceiveForm() itself needs a page, so it isn't tested here; we cover the
// helpers that decide types and (critically) which fields are secrets.
import assert from "node:assert";
import {
  clean,
  humanize,
  normalizeType,
  classifySensitive,
} from "../lib/perceive.js";

let passed = 0;
const test = (name, fn) => {
  fn();
  passed++;
  console.log("  ok -", name);
};

const isSecret = (o) => classifySensitive(o).sensitive;

// ---------------------------------------------------------------------------
test("clean collapses whitespace and trims", () => {
  assert.strictEqual(clean("  a\n  b\t c "), "a b c");
  assert.strictEqual(clean(null), "");
});

test("humanize splits snake_case and camelCase and title-cases", () => {
  assert.strictEqual(humanize("first_name"), "First Name");
  assert.strictEqual(humanize("userEmail"), "User Email");
  assert.strictEqual(humanize("home-city"), "Home City");
});

test("normalizeType maps tags/types and skips non-input types", () => {
  assert.strictEqual(normalizeType("select", null), "select");
  assert.strictEqual(normalizeType("textarea", null), "textarea");
  assert.strictEqual(normalizeType("input", "password"), "password");
  assert.strictEqual(normalizeType("input", "range"), "number");
  assert.strictEqual(normalizeType("input", "datetime-local"), "date");
  assert.strictEqual(normalizeType("input", "search"), "text");
  assert.strictEqual(normalizeType("input", "hidden"), null);
  assert.strictEqual(normalizeType("input", "submit"), null);
});

test("classifySensitive flags password by input type", () => {
  assert.strictEqual(isSecret({ type: "password" }), true);
});

test("classifySensitive flags payment/OTP autocomplete tokens", () => {
  assert.strictEqual(isSecret({ autocomplete: "cc-number" }), true);
  assert.strictEqual(isSecret({ autocomplete: "one-time-code" }), true);
});

test("classifySensitive flags OTP via snake_case and camelCase names", () => {
  assert.strictEqual(isSecret({ name: "user_otp" }), true);
  assert.strictEqual(isSecret({ name: "userOtp" }), true);
  assert.strictEqual(isSecret({ label: "Verification code" }), true);
});

test("classifySensitive flags card, CVV, SSN and bank fields", () => {
  assert.strictEqual(isSecret({ name: "card_number" }), true);
  assert.strictEqual(isSecret({ label: "CVV" }), true);
  assert.strictEqual(isSecret({ name: "ssn" }), true);
  assert.strictEqual(isSecret({ label: "Social Security Number" }), true);
  assert.strictEqual(isSecret({ label: "Routing number" }), true);
  assert.strictEqual(isSecret({ name: "iban" }), true);
});

test("classifySensitive flags a bare PIN but not a postal 'PIN code'", () => {
  assert.strictEqual(isSecret({ label: "ATM PIN" }), true);
  assert.strictEqual(isSecret({ name: "userPin" }), true);
  // Guarded: "PIN code" / "pincode" are postal codes, not secrets.
  assert.strictEqual(isSecret({ label: "PIN code" }), false);
  assert.strictEqual(isSecret({ name: "pincode" }), false);
});

test("classifySensitive leaves ordinary fields alone", () => {
  assert.strictEqual(isSecret({ type: "email", label: "Email" }), false);
  assert.strictEqual(isSecret({ name: "first_name", label: "First name" }), false);
  assert.strictEqual(isSecret({ name: "phone", label: "Phone" }), false);
});

console.log(`\nperceive.js: ${passed} passed`);
