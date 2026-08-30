import { useEffect, useState } from "react";
import {
  getToken,
  saveToken,
  health,
  llmTest,
  postForm,
  sendToPage,
  listProfiles,
  activateProfile,
  openOptionsPage,
  type ProfileMeta,
} from "../../lib/api";

type Status = { msg: string; ok: boolean } | null;

// ---- plain render helpers (mirror the legacy popup, kept as strings) ----
function preview(v: unknown, n = 80): string {
  const s = v == null ? "" : String(v);
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function summarizeForm(form: any): string {
  const fields = form.fields || [];
  const sens = fields.filter((f: any) => f.sensitive);
  const lines = [
    `${fields.length} field(s) on this page` +
      (form.title ? ` — ${preview(form.title, 60)}` : ""),
  ];
  if (sens.length) {
    lines.push(
      `${sens.length} sensitive (manual only): ` +
        sens
          .map((f: any) => `${f.label || f.name || f.field_id} [${f.sensitive_reason}]`)
          .slice(0, 6)
          .join(", "),
    );
  }
  return lines.join("\n");
}

function renderPlan(plan: any): string {
  const fields = plan.fields || [];
  const s = plan.summary || {};
  const head =
    `Plan: ${s.fill ?? 0} fill · ${s.manual_entry ?? 0} manual · ` +
    `${s.generate ?? 0} to draft · ${s.unmapped ?? 0} unmapped` +
    (plan.generated ? ` · ${plan.generated} drafted` : "");
  const rows = fields.map((f: any) => {
    const label = f.label || f.field_id;
    if (f.action === "fill") {
      const mark = f.via === "generated" ? "✎" : f.via === "llm" ? "~" : "=";
      return `  ✓ ${label} → ${mark} ${preview(f.value, 80)}`;
    }
    if (f.action === "manual_entry")
      return `  🔒 ${label} — manual (${f.reason || "sensitive"})`;
    if (f.action === "generate")
      return `  ✎ ${label} — write answer (Draft answers)`;
    return `  · ${label} — ${f.reason || "no match"}`;
  });
  return [head, "", ...rows].join("\n");
}

function renderReport(report: any, plan: any): string {
  const labelOf: Record<string, string> = {};
  (plan.fields || []).forEach((f: any) => {
    labelOf[f.field_id] = f.label || f.field_id;
  });
  const c = report.counts || {};
  const lines = [
    `Filled ${c.filled ?? 0} · skipped ${c.skipped ?? 0} · ` +
      `not found ${c.not_found ?? 0} · no option ${c.no_option ?? 0}`,
    "",
    "Review every field before submitting — nothing was submitted.",
  ];
  if ((report.filled || []).length) {
    lines.push("", "Filled:");
    report.filled.forEach((id: string) => lines.push(`  ✓ ${labelOf[id] || id}`));
  }
  if ((report.not_found || []).length) {
    lines.push("", "Not found on page (re-scan if the form changed):");
    report.not_found.forEach((id: string) => lines.push(`  · ${labelOf[id] || id}`));
  }
  if ((report.no_option || []).length) {
    lines.push("", "No matching option:");
    report.no_option.forEach((id: string) => lines.push(`  · ${labelOf[id] || id}`));
  }
  return lines.join("\n");
}

function renderLearned(r: any): string {
  const learned = r.learned || [];
  const skipped = r.skipped || [];
  const lines: string[] = [];
  if (learned.length) {
    lines.push("Learned & saved to your profile:");
    learned.forEach((l: any) =>
      lines.push(`  + ${l.label || l.key}: ${preview(l.value, 60)}`),
    );
  } else {
    lines.push("Nothing new to learn — the profile already has these.");
  }
  const secret = r.counts?.refused_secret || 0;
  if (secret) lines.push("", `${secret} secret field(s) ignored — never read or stored.`);
  const already = skipped.filter((s: any) => /already set/.test(s.reason || "")).length;
  if (already) lines.push("", `${already} field(s) already in your profile (kept existing).`);
  return lines.join("\n");
}

export function App() {
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<Status>(null);
  const [out, setOut] = useState("");
  const [plan, setPlan] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [profiles, setProfiles] = useState<ProfileMeta[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);

  useEffect(() => {
    getToken().then(setToken);
  }, []);

  // Load the profile list so the user can "select who they are" on open.
  async function loadProfiles() {
    try {
      const list = await listProfiles();
      setProfiles(list);
      const active = list.find((p) => p.active);
      setActiveId(active ? active.id : null);
    } catch {
      /* backend not up / token missing — the picker just stays empty */
    }
  }

  useEffect(() => {
    getToken().then((t) => {
      if (t) loadProfiles();
    });
  }, []);

  const say = (msg: string, ok = true) => setStatus({ msg, ok });

  const onSelectProfile = (id: number) =>
    run("Switch profile", async () => {
      await activateProfile(id);
      setActiveId(id);
      const p = profiles.find((x) => x.id === id);
      setPlan(null); // a different person's data — force a fresh preview
      say(`Using profile: ${p?.name ?? id} ✔`);
    });

  // Read the current tab's form via the content script.
  async function perceive(): Promise<any> {
    const res = await sendToPage({ type: "AUTOFILL_PERCEIVE" });
    if (!res || !res.ok) throw new Error(res?.error || "No response from page.");
    return res.form;
  }

  async function run<T>(label: string, fn: () => Promise<T>) {
    if (busy) return;
    setBusy(true);
    say(label + "…");
    try {
      await fn();
    } catch (e: any) {
      say(`${label} failed: ${e.message}`, false);
    } finally {
      setBusy(false);
    }
  }

  const onSaveToken = () =>
    run("Save token", async () => {
      await saveToken(token);
      say("Token saved ✔");
    });

  const onCheck = () =>
    run("Check backend", async () => {
      const j = await health();
      say(`Backend OK ✔ (${j.status || "ready"})`);
    });

  const onLlm = () =>
    run("Test LLM", async () => {
      const j = await llmTest();
      say("LLM OK ✔");
      setOut(preview(j.reply || j.text || JSON.stringify(j), 400));
    });

  const onScan = () =>
    run("Scan", async () => {
      const form = await perceive();
      const priv = await postForm("/privacy/plan", form);
      say(`Scanned ${form.fields.length} field(s) ✔`);
      setOut(summarizeForm(form) + "\n\n" + renderPlan(priv));
      setPlan(null); // scan is read-only; require an explicit Preview/Draft before Fill
    });

  const onPreview = () =>
    run("Preview autofill", async () => {
      const form = await perceive();
      const p = await postForm("/fill/plan", form);
      setPlan(p);
      say(`Planned ${p.summary?.fill ?? 0} fill ✔`);
      setOut(renderPlan(p));
    });

  const onDraft = () =>
    run("Draft answers", async () => {
      const form = await perceive();
      const p = await postForm("/generate/answers", form);
      setPlan(p);
      say(`Drafted ${p.generated ?? 0} answer(s) ✔`);
      setOut(renderPlan(p));
    });

  // Read back non-secret values on the page and persist any that fill an empty
  // profile slot. Non-fatal by design: if learning fails, the fill still stands.
  async function silentLearn(): Promise<any[]> {
    try {
      const res = await sendToPage({ type: "AUTOFILL_READ_VALUES" });
      if (!res || !res.ok) return [];
      const r = await postForm("/profile/learn", res.form);
      return r.learned || [];
    } catch {
      return [];
    }
  }

  // The one new mutation path: apply the last plan into the page. Secrets,
  // unmapped and manual-entry records are skipped by lib/fill.js; never submits.
  const onFill = () =>
    run("Fill page", async () => {
      if (!plan) {
        say("Preview or draft a plan first.", false);
        return;
      }
      const res = await sendToPage({ type: "AUTOFILL_APPLY", plan });
      if (!res || !res.ok) throw new Error(res?.error || "No response from page.");
      const c = res.report.counts || {};
      setOut(renderReport(res.report, plan));
      // Silently learn anything the user typed that we couldn't fill (e.g. a
      // LinkedIn URL missing from the profile) so it fills automatically next time.
      const learned = await silentLearn();
      if (learned.length) {
        const names = learned.map((l: any) => l.label || l.key).join(", ");
        say(
          `Filled ${c.filled ?? 0} · learned ${learned.length} (${preview(names, 40)}) ✔ — review, then submit yourself`,
        );
        setOut(renderReport(res.report, plan) + "\n\n" + renderLearned({ learned }));
      } else {
        say(`Filled ${c.filled ?? 0} · skipped ${c.skipped ?? 0} ✔ — review, then submit yourself`);
      }
    });

  // Explicit "learn" — capture what's currently typed on the page into the
  // profile (empty slots only). Same path the fill uses silently.
  const onLearn = () =>
    run("Learn from page", async () => {
      const res = await sendToPage({ type: "AUTOFILL_READ_VALUES" });
      if (!res || !res.ok) throw new Error(res?.error || "No response from page.");
      const r = await postForm("/profile/learn", res.form);
      const n = r.counts?.learned ?? 0;
      say(n ? `Learned ${n} field(s) ✔ saved to your profile` : "Nothing new to learn.");
      setOut(renderLearned(r));
    });

  return (
    <div>
      <h3>AutoFill Agent</h3>
      <small>Local-first · secrets stay manual · never auto-submits</small>

      <input
        type="password"
        placeholder="Local token"
        value={token}
        onChange={(e) => setToken(e.target.value)}
      />
      <div className="row">
        <button onClick={onSaveToken} disabled={busy}>
          Save token
        </button>
        <button onClick={onCheck} disabled={busy}>
          Check backend
        </button>
      </div>
      <button onClick={onLlm} disabled={busy}>
        Test LLM
      </button>

      <hr />

      <label className="pf-label">
        Profile (who are you?)
        <div className="row">
          <select
            value={activeId ?? ""}
            disabled={busy || profiles.length === 0}
            onChange={(e) => onSelectProfile(Number(e.target.value))}
          >
            {profiles.length === 0 && <option value="">— no profiles —</option>}
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <button onClick={() => openOptionsPage()} disabled={busy} title="Add, edit, or import profiles">
            Manage
          </button>
        </div>
      </label>

      <hr />

      <button onClick={onScan} disabled={busy}>
        Scan this page
      </button>
      <button className="primary" onClick={onPreview} disabled={busy}>
        Preview autofill
      </button>
      <button className="generate" onClick={onDraft} disabled={busy}>
        Draft answers
      </button>
      <button className="apply" onClick={onFill} disabled={busy || !plan}>
        Fill page
      </button>
      <button onClick={onLearn} disabled={busy} title="Save non-secret values you've typed into your profile">
        Learn from page
      </button>

      {status && (
        <div className={"status " + (status.ok ? "ok" : "err")}>{status.msg}</div>
      )}
      {out && <pre>{out}</pre>}
    </div>
  );
}
