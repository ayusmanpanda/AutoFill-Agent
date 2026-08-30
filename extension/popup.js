// AutoFill Agent — popup (Phase 0)
// Confirms the extension can reach the local backend and round-trip the LLM.

const BASE = "http://127.0.0.1:8000";
const $ = (id) => document.getElementById(id);

async function getToken() {
  const { localToken } = await chrome.storage.local.get("localToken");
  return localToken || "";
}

function setStatus(msg, ok) {
  const s = $("status");
  s.textContent = msg;
  s.className = ok ? "ok" : "err";
}

// Prefill the saved token when the popup opens.
(async () => {
  $("token").value = await getToken();
})();

$("save").onclick = async () => {
  await chrome.storage.local.set({ localToken: $("token").value.trim() });
  setStatus("Token saved.", true);
};

$("health").onclick = async () => {
  try {
    const r = await fetch(`${BASE}/health`);
    const j = await r.json();
    setStatus("Backend connected ✔", true);
    $("out").textContent = JSON.stringify(j, null, 2);
  } catch (e) {
    setStatus("Cannot reach backend. Is it running on :8000?", false);
    $("out").textContent = String(e);
  }
};

$("llm").onclick = async () => {
  setStatus("Calling model…", true);
  try {
    const r = await fetch(`${BASE}/llm/test`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Local-Token": await getToken(),
      },
      body: JSON.stringify({ prompt: "Say hello in one short sentence." }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.statusText);
    setStatus("LLM round-trip OK ✔", true);
    $("out").textContent = j.reply;
  } catch (e) {
    setStatus("LLM test failed.", false);
    $("out").textContent = String(e);
  }
};

// ---- Phase 2: scan the current page's form ----

// Inject the perception script into the active tab and read the form back.
async function perceivePage() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) throw new Error("No active tab.");
  await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
  const res = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => window.__autofillPerceiveForm(),
  });
  const form = res && res[0] && res[0].result;
  if (!form) throw new Error("No result from page (is it a normal web page?).");
  return form;
}

function summarize(form) {
  const byType = {};
  form.fields.forEach((f) => { byType[f.type] = (byType[f.type] || 0) + 1; });
  const secrets = form.fields.filter((f) => f.sensitive);

  const lines = [];
  lines.push(`${form.fields.length} fields — ${form.title || form.url || "this page"}`);
  const types = Object.keys(byType).sort().map((k) => `${k}×${byType[k]}`).join(", ");
  if (types) lines.push(`Types: ${types}`);
  if (secrets.length) {
    lines.push(`Manual-only (never stored): ${secrets.map((f) => f.label || f.selector).join(", ")}`);
  }
  lines.push("");
  form.fields.slice(0, 25).forEach((f) => {
    const marks = `${f.required ? " *" : ""}${f.sensitive ? " (secret)" : ""}`;
    lines.push(`• ${f.label || "(no label)"} [${f.type}]${marks}`);
  });
  if (form.fields.length > 25) lines.push(`… +${form.fields.length - 25} more`);
  return lines.join("\n");
}

$("scan").onclick = async () => {
  setStatus("Scanning page…", true);
  try {
    const form = await perceivePage();

    $("out").textContent = summarize(form);
    console.log("[AutoFill] perceived form:", form);

    // Ask the backend which fields may go to the cloud vs. stay on device.
    try {
      const r = await fetch(`${BASE}/privacy/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Local-Token": await getToken() },
        body: JSON.stringify(form),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.statusText);
      setStatus(
        `Cloud-eligible: ${j.cloud_eligible} safe · Kept on device: ${j.kept_local} ` +
        `(${j.counts.secret} secret, ${j.counts.pii} PII) ✔`,
        true
      );
    } catch (e) {
      setStatus(`Scanned ${form.fields.length} fields ✔ (privacy plan skipped: ${e.message})`, false);
    }
  } catch (e) {
    setStatus("Scan failed: " + e.message, false);
    $("out").textContent = String(e);
  }
};

// ---- Phase 4/5: preview the fill plan (does NOT touch the page) ----
function preview(v, n) {
  v = String(v == null ? "" : v).replace(/\s+/g, " ").trim();
  return v.length > n ? v.slice(0, n - 1) + "…" : v;
}

function renderPlan(plan) {
  const s = plan.summary || {};
  const lines = [];
  lines.push(
    `Fill ${s.fill || 0} · Generate ${s.generate || 0} · ` +
    `Manual ${s.manual_entry || 0} · Unmapped ${s.unmapped || 0}`
  );
  if (plan.generated) {
    lines.push(`(${plan.generated} answer${plan.generated > 1 ? "s" : ""} drafted — marked ✎)`);
  } else if (plan.used_llm) {
    lines.push("(model matched some leftover fields — marked ~)");
  }
  lines.push("");
  (plan.fields || []).slice(0, 30).forEach((f) => {
    const label = preview(f.label || "(no label)", 40);
    let rhs;
    if (f.action === "fill") {
      if (f.via === "generated") rhs = `→ ✎ ${preview(f.value, 80)}`;
      else rhs = `→ ${preview(f.value, 60)}${f.via === "llm" ? "  ~" : ""}`;
    } else if (f.action === "manual_entry") rhs = "→ manual entry (secret)";
    else if (f.action === "generate") rhs = "→ write answer (Draft answers)";
    else rhs = "→ —";
    lines.push(`• ${label} [${f.type}] ${rhs}`);
  });
  const more = (plan.fields || []).length - 30;
  if (more > 0) lines.push(`… +${more} more`);
  return lines.join("\n");
}

$("fill").onclick = async () => {
  setStatus("Building fill plan…", true);
  try {
    const form = await perceivePage();
    const r = await fetch(`${BASE}/fill/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Local-Token": await getToken() },
      body: JSON.stringify(form),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.statusText);
    const s = j.summary || {};
    setStatus(
      `Plan ready: ${s.fill || 0} to fill, ${s.manual_entry || 0} manual, ` +
      `${s.unmapped || 0} unmapped ✔`,
      true
    );
    $("out").textContent = renderPlan(j);
    console.log("[AutoFill] fill plan:", j);
  } catch (e) {
    setStatus("Fill plan failed: " + e.message, false);
    $("out").textContent = String(e);
  }
};

// ---- Phase 5: draft the free-text answers (calls the model; still no DOM fill) ----
$("draft").onclick = async () => {
  setStatus("Drafting answers… (this calls the model)", true);
  try {
    const form = await perceivePage();
    const r = await fetch(`${BASE}/generate/answers`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Local-Token": await getToken() },
      body: JSON.stringify(form),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.statusText);
    const n = j.generated || 0;
    setStatus(
      n ? `Drafted ${n} answer${n > 1 ? "s" : ""} ✔ (review below)` : "No free-text answers to draft.",
      true
    );
    $("out").textContent = renderPlan(j);
    console.log("[AutoFill] generated plan:", j);
  } catch (e) {
    setStatus("Draft failed: " + e.message, false);
    $("out").textContent = String(e);
  }
};
