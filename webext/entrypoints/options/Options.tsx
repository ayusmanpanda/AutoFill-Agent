import { useEffect, useState } from "react";
import {
  getToken,
  saveToken,
  listProfiles,
  createProfile,
  activateProfile,
  renameProfile,
  deleteProfile,
  getProfile,
  saveProfile,
  importResume,
  type ProfileMeta,
} from "../../lib/api";

type Status = { msg: string; ok: boolean } | null;

// Scalar fields, driven by dotted paths into the profile document (mirrors the
// backend Pydantic schema and the legacy /static/editor.html).
type Scalar = { path: string; label: string; ph?: string; type?: "bool" | "textarea" };

const BASICS: Scalar[] = [
  { path: "basics.name", label: "Full name" },
  { path: "basics.headline", label: "Headline", ph: "Backend Engineer" },
  { path: "basics.email", label: "Email" },
  { path: "basics.phone", label: "Phone" },
  { path: "basics.website", label: "Website" },
  { path: "basics.location.country", label: "Country" },
  { path: "basics.location.city", label: "City" },
  { path: "basics.location.region", label: "Region / State" },
  { path: "basics.location.postal_code", label: "Postal code" },
  { path: "basics.location.address", label: "Address" },
  { path: "basics.summary", label: "Summary", type: "textarea" },
];

const PREFS: Scalar[] = [
  { path: "job_preferences.work_authorization", label: "Work authorization", ph: "Indian citizen" },
  { path: "job_preferences.requires_sponsorship", label: "Requires sponsorship?", type: "bool" },
  { path: "job_preferences.desired_salary", label: "Desired salary" },
  { path: "job_preferences.salary_currency", label: "Salary currency", ph: "INR / USD" },
  { path: "job_preferences.notice_period", label: "Notice period" },
  { path: "job_preferences.earliest_start_date", label: "Earliest start date" },
  { path: "job_preferences.willing_to_relocate", label: "Willing to relocate?", type: "bool" },
  { path: "job_preferences.work_mode", label: "Work mode", ph: "remote / hybrid / onsite" },
  { path: "job_preferences.linkedin", label: "LinkedIn" },
  { path: "job_preferences.github", label: "GitHub" },
  { path: "job_preferences.portfolio", label: "Portfolio" },
];

const VOLUNTARY: Scalar[] = [
  { path: "voluntary.gender", label: "Gender" },
  { path: "voluntary.race_ethnicity", label: "Race / ethnicity" },
  { path: "voluntary.hispanic_latino", label: "Hispanic / Latino" },
  { path: "voluntary.veteran_status", label: "Veteran status" },
  { path: "voluntary.disability_status", label: "Disability status" },
];

// List/structured sections edited as JSON (same as the legacy editor).
const JSON_SECTIONS: { path: string; label: string; hint: string }[] = [
  { path: "basics.profiles", label: "Social profiles",
    hint: 'JSON array. Each item: {"network":"LinkedIn","username":"you","url":"https://…"}' },
  { path: "work", label: "Work experience",
    hint: "JSON array. Keys: company, position, location, start_date, end_date, summary, highlights[]" },
  { path: "education", label: "Education",
    hint: "JSON array. Keys: institution, area, study_type, start_date, end_date, score, courses[]" },
  { path: "skills", label: "Skills", hint: "JSON array. Keys: name, level, keywords[]" },
  { path: "projects", label: "Projects", hint: "JSON array. Keys: name, description, url, highlights[]" },
  { path: "job_preferences.preferred_locations", label: "Preferred locations",
    hint: "JSON array of strings" },
];

function getPath(obj: any, path: string): any {
  return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

function setPath(obj: any, path: string, value: any): void {
  const keys = path.split(".");
  let cur = obj;
  for (const k of keys.slice(0, -1)) {
    if (cur[k] == null || typeof cur[k] !== "object") cur[k] = {};
    cur = cur[k];
  }
  cur[keys[keys.length - 1]] = value;
}

export function Options() {
  const [token, setToken] = useState("");
  const [profiles, setProfiles] = useState<ProfileMeta[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [profile, setProfile] = useState<any>(null);
  const [jsonText, setJsonText] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<Status>(null);
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");

  const say = (msg: string, ok = true) => setStatus({ msg, ok });

  async function run(label: string, fn: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
    } catch (e: any) {
      say(`${label} failed: ${e.message}`, false);
    } finally {
      setBusy(false);
    }
  }

  // Load token first; if present, load profiles + the active profile document.
  useEffect(() => {
    (async () => {
      const t = await getToken();
      setToken(t);
      if (t) {
        try {
          await refreshProfiles();
          await loadProfile();
        } catch {
          say("Enter your token, then Reload.", false);
        }
      }
    })();
  }, []);

  async function refreshProfiles() {
    const list = await listProfiles();
    setProfiles(list);
    const active = list.find((p) => p.active);
    setActiveId(active ? active.id : null);
  }

  // Pull the ACTIVE profile document into the form + JSON textareas.
  async function loadProfile() {
    const p = await getProfile();
    setProfile(p);
    const jt: Record<string, string> = {};
    for (const s of JSON_SECTIONS) {
      const v = getPath(p, s.path);
      jt[s.path] = JSON.stringify(v ?? [], null, 2);
    }
    setJsonText(jt);
  }

  const onSaveToken = () =>
    run("Save token", async () => {
      await saveToken(token);
      await refreshProfiles();
      await loadProfile();
      say("Token saved ✔");
    });

  const onSwitch = (id: number) =>
    run("Switch profile", async () => {
      await activateProfile(id);
      await refreshProfiles();
      await loadProfile();
      say("Switched profile ✔");
    });

  const onCreate = () =>
    run("Create profile", async () => {
      const name = newName.trim();
      if (!name) return say("Enter a name for the new profile.", false);
      await createProfile(name); // created + activated by the backend
      setNewName("");
      await refreshProfiles();
      await loadProfile();
      say(`Created “${name}” ✔ (now active)`);
    });

  const onRename = (id: number, current: string) =>
    run("Rename profile", async () => {
      const name = window.prompt("New name for this profile:", current);
      if (name == null || !name.trim()) return;
      await renameProfile(id, name.trim());
      await refreshProfiles();
      say("Renamed ✔");
    });

  const onDelete = (id: number, name: string) =>
    run("Delete profile", async () => {
      if (!window.confirm(`Delete profile “${name}”? This can't be undone.`)) return;
      await deleteProfile(id);
      await refreshProfiles();
      await loadProfile();
      say("Deleted ✔");
    });

  // Scalar field edits mutate a shallow clone so React re-renders.
  const setScalar = (path: string, value: string, isBool = false) => {
    setProfile((prev: any) => {
      const next = structuredClone(prev ?? {});
      let out: any = value;
      if (isBool) out = value === "" ? null : value === "true";
      else if (value === "") out = null;
      setPath(next, path, out);
      return next;
    });
  };

  const scalarVal = (path: string, isBool = false): string => {
    const v = getPath(profile, path);
    if (v == null) return "";
    return isBool ? String(v) : String(v);
  };

  const onSave = () =>
    run("Save profile", async () => {
      const next = structuredClone(profile ?? {});
      // Fold the JSON textareas back in, validating each.
      for (const s of JSON_SECTIONS) {
        const raw = (jsonText[s.path] ?? "").trim();
        try {
          setPath(next, s.path, raw === "" ? [] : JSON.parse(raw));
        } catch {
          return say(`“${s.label}” isn't valid JSON — fix it and save again.`, false);
        }
      }
      await saveProfile(next);
      setProfile(next);
      await refreshProfiles();
      say("Profile saved ✔");
    });

  const onResume = (file: File | null) => {
    if (!file) return;
    run("Import resume", async () => {
      const r = await importResume(file);
      await loadProfile();
      const c = r.counts || {};
      const names = (r.imported || []).map((i: any) => i.label || i.key).join(", ");
      say(
        c.imported
          ? `Imported ${c.imported} field(s): ${names} ✔ (empty slots only — review below)`
          : `No new fields found to import (found ${c.found ?? 0}).`,
        true,
      );
    });
  };

  const activeName = profiles.find((p) => p.id === activeId)?.name ?? "—";

  return (
    <>
      <header>
        <h1>AutoFill Agent — Profiles</h1>
        <span className="pill">Active: {activeName}</span>
        <button onClick={() => run("Reload", loadProfile)} disabled={busy}>Reload</button>
        <button className="primary" onClick={onSave} disabled={busy || !profile}>Save</button>
        {status && <span className={"status " + (status.ok ? "ok" : "err")}>{status.msg}</span>}
      </header>

      <main>
        <fieldset>
          <legend>Local token</legend>
          <div className="row">
            <input type="password" placeholder="paste your local token" autoComplete="off"
              value={token} onChange={(e) => setToken(e.target.value)} style={{ flex: 1 }} />
            <button onClick={onSaveToken} disabled={busy}>Remember</button>
          </div>
          <p className="hint">Stored only in this browser; sent as the <code>X-Local-Token</code> header.</p>
        </fieldset>

        <fieldset>
          <legend>Profiles (one per person)</legend>
          <p className="hint">Pick who you are — everything (fill, PDF, learn) uses the active profile.</p>
          {profiles.map((p) => (
            <div className="row" key={p.id} style={{ padding: "4px 0" }}>
              <input type="radio" name="active" checked={p.id === activeId}
                onChange={() => onSwitch(p.id)} disabled={busy} />
              <b style={{ minWidth: 160 }}>{p.name}</b>
              <span className="pill">updated {(p.updated_at || "").slice(0, 10)}</span>
              <span className="spacer" />
              <button onClick={() => onRename(p.id, p.name)} disabled={busy}>Rename</button>
              <button className="danger" onClick={() => onDelete(p.id, p.name)}
                disabled={busy || profiles.length <= 1}>Delete</button>
            </div>
          ))}
          <div className="row" style={{ marginTop: 10 }}>
            <input placeholder="New profile name (e.g. a friend's)" value={newName}
              onChange={(e) => setNewName(e.target.value)} style={{ flex: 1 }} />
            <button onClick={onCreate} disabled={busy}>Add profile</button>
          </div>
        </fieldset>

        <fieldset>
          <legend>Import from resume</legend>
          <p className="hint">Upload a PDF or text resume to fill empty fields of the active profile.
            100% local — no upload to any server or LLM. Secrets are never read. Work history &amp;
            education are left for you to add below.</p>
          <input type="file" accept=".pdf,.txt,.md,application/pdf,text/plain"
            disabled={busy} onChange={(e) => onResume(e.target.files?.[0] ?? null)} />
        </fieldset>

        {!profile && <p className="hint">Enter your token and click Remember to load your profile.</p>}
        {profile && (
          <>
            <fieldset>
              <legend>Basics</legend>
              <div className="grid">{BASICS.map((f) => renderScalar(f))}</div>
            </fieldset>
            <fieldset>
              <legend>Job preferences</legend>
              <div className="grid">{PREFS.map((f) => renderScalar(f))}</div>
            </fieldset>
            {JSON_SECTIONS.map((s) => (
              <fieldset key={s.path}>
                <legend>{s.label}</legend>
                <p className="hint">{s.hint}</p>
                <textarea className="json" value={jsonText[s.path] ?? ""}
                  onChange={(e) => setJsonText((prev) => ({ ...prev, [s.path]: e.target.value }))} />
              </fieldset>
            ))}
            <fieldset>
              <legend>Voluntary disclosures (optional)</legend>
              <p className="hint">Optional EEO fields — leave blank if you prefer not to say.</p>
              <div className="grid">{VOLUNTARY.map((f) => renderScalar(f))}</div>
            </fieldset>
          </>
        )}
      </main>
    </>
  );

  function renderScalar(f: Scalar) {
    const cls = f.type === "textarea" ? "full" : undefined;
    return (
      <div className={cls} key={f.path}>
        <label>{f.label}</label>
        {f.type === "bool" ? (
          <select value={scalarVal(f.path, true)} disabled={busy}
            onChange={(e) => setScalar(f.path, e.target.value, true)}>
            <option value="">— not set —</option>
            <option value="true">Yes</option>
            <option value="false">No</option>
          </select>
        ) : f.type === "textarea" ? (
          <textarea value={scalarVal(f.path)} disabled={busy}
            onChange={(e) => setScalar(f.path, e.target.value)} />
        ) : (
          <input value={scalarVal(f.path)} placeholder={f.ph} disabled={busy}
            onChange={(e) => setScalar(f.path, e.target.value)} />
        )}
      </div>
    );
  }
}
