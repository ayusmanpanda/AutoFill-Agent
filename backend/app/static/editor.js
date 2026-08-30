// AutoFill Agent — profile editor (plain JS, no build step).
// Served from the backend at /static/editor.js, so all fetches are same-origin.

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "localToken";

const getToken = () => localStorage.getItem(TOKEN_KEY) || "";

function getPath(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

function setPath(obj, path, val) {
  const keys = path.split(".");
  let o = obj;
  for (let i = 0; i < keys.length - 1; i++) {
    if (o[keys[i]] == null || typeof o[keys[i]] !== "object") o[keys[i]] = {};
    o = o[keys[i]];
  }
  o[keys[keys.length - 1]] = val;
}

function fillForm(profile) {
  document.querySelectorAll("[data-path]").forEach((el) => {
    const val = getPath(profile, el.dataset.path);
    if (el.hasAttribute("data-json")) {
      el.value = JSON.stringify(val ?? [], null, 2);
    } else if (el.dataset.type === "bool") {
      el.value = val === true ? "true" : val === false ? "false" : "";
    } else {
      el.value = val == null ? "" : val;
    }
  });
}

function collectForm() {
  const profile = {};
  let error = null;
  document.querySelectorAll("[data-path]").forEach((el) => {
    if (error) return;
    const path = el.dataset.path;
    if (el.hasAttribute("data-json")) {
      const t = el.value.trim();
      try {
        setPath(profile, path, t === "" ? [] : JSON.parse(t));
      } catch (e) {
        error = `Invalid JSON in "${path}": ${e.message}`;
      }
    } else if (el.dataset.type === "bool") {
      const v = el.value;
      setPath(profile, path, v === "true" ? true : v === "false" ? false : null);
    } else {
      const v = el.value.trim();
      setPath(profile, path, v === "" ? null : v);
    }
  });
  if (error) throw new Error(error);
  return profile;
}

function setStatus(msg, ok) {
  const s = $("status");
  s.textContent = msg;
  s.className = ok ? "ok" : "err";
}

async function detail(resp) {
  try {
    const j = await resp.json();
    return j.detail || resp.statusText;
  } catch {
    return resp.statusText;
  }
}

async function load() {
  setStatus("Loading…", true);
  try {
    const r = await fetch("/profile", { headers: { "X-Local-Token": getToken() } });
    if (!r.ok) throw new Error(await detail(r));
    fillForm(await r.json());
    setStatus("Profile loaded ✔", true);
  } catch (e) {
    setStatus("Load failed: " + e.message, false);
  }
}

async function save() {
  let body;
  try {
    body = collectForm();
  } catch (e) {
    setStatus(e.message, false);
    return;
  }
  setStatus("Saving…", true);
  try {
    const r = await fetch("/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-Local-Token": getToken() },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await detail(r));
    fillForm(await r.json());
    setStatus("Profile saved ✔", true);
  } catch (e) {
    setStatus("Save failed: " + e.message, false);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("token").value = getToken();
  $("saveToken").onclick = () => {
    localStorage.setItem(TOKEN_KEY, $("token").value.trim());
    setStatus("Token remembered.", true);
  };
  $("load").onclick = load;
  $("save").onclick = save;
  // Prefill JSON textareas with [] so they're valid even before first load.
  document.querySelectorAll("[data-json]").forEach((el) => {
    if (!el.value.trim()) el.value = "[]";
  });
});
