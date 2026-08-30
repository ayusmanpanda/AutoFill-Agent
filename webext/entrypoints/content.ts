// Content script: the page-side agent. It never acts on its own — it only
// responds to messages from the popup:
//   AUTOFILL_PERCEIVE     -> read the form structure (never reads values)
//   AUTOFILL_APPLY        -> write a fill plan into the page (never submits)
//   AUTOFILL_READ_VALUES  -> read NON-SECRET values back for the "learn" feature
//
// Registered on all pages but idempotent: re-injection (the popup's fallback)
// won't attach a second listener.
import { perceiveForm, readValues } from "../lib/perceive.js";
import { applyPlan } from "../lib/fill.js";

export default defineContentScript({
  matches: ["<all_urls>"],
  runAt: "document_idle",
  main() {
    const w = window as unknown as { __autofillWired?: boolean };
    if (w.__autofillWired) return;
    w.__autofillWired = true;

    browser.runtime.onMessage.addListener((msg: any) => {
      if (!msg || !msg.type) return;
      if (msg.type === "AUTOFILL_PERCEIVE") {
        try {
          return Promise.resolve({ ok: true, form: perceiveForm() });
        } catch (e: any) {
          return Promise.resolve({ ok: false, error: String(e?.message || e) });
        }
      }
      if (msg.type === "AUTOFILL_APPLY") {
        try {
          return Promise.resolve({ ok: true, report: applyPlan(msg.plan) });
        } catch (e: any) {
          return Promise.resolve({ ok: false, error: String(e?.message || e) });
        }
      }
      if (msg.type === "AUTOFILL_READ_VALUES") {
        try {
          return Promise.resolve({ ok: true, form: readValues() });
        } catch (e: any) {
          return Promise.resolve({ ok: false, error: String(e?.message || e) });
        }
      }
      // other messages: ignore (return undefined = no response)
    });
  },
});
