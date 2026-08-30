// Backend (loopback) calls and page messaging, kept out of the React component.
const BASE = "http://127.0.0.1:8000";

export async function getToken(): Promise<string> {
  const { localToken } = await browser.storage.local.get("localToken");
  return (localToken as string) || "";
}

export async function saveToken(v: string): Promise<void> {
  await browser.storage.local.set({ localToken: v.trim() });
}

async function authHeaders(): Promise<Record<string, string>> {
  return { "Content-Type": "application/json", "X-Local-Token": await getToken() };
}

export async function health(): Promise<any> {
  const r = await fetch(`${BASE}/health`);
  return r.json();
}

export async function llmTest(): Promise<any> {
  const r = await fetch(`${BASE}/llm/test`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ prompt: "Say hello in one short sentence." }),
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

// POST a perceived form to a backend path (/privacy/plan, /fill/plan, /generate/answers).
export async function postForm(path: string, form: unknown): Promise<any> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(form),
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

// ------------------------- multi-profile management -------------------------

export type ProfileMeta = { id: number; name: string; updated_at: string; active: boolean };

export async function listProfiles(): Promise<ProfileMeta[]> {
  const r = await fetch(`${BASE}/profiles`, { headers: await authHeaders() });
  const j = await r.json();
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j.profiles || [];
}

export async function createProfile(name: string): Promise<{ id: number; name: string }> {
  const r = await fetch(`${BASE}/profiles`, {
    method: "POST", headers: await authHeaders(), body: JSON.stringify({ name }),
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

export async function activateProfile(id: number): Promise<void> {
  const r = await fetch(`${BASE}/profiles/${id}/activate`, {
    method: "POST", headers: await authHeaders(),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
}

export async function renameProfile(id: number, name: string): Promise<void> {
  const r = await fetch(`${BASE}/profiles/${id}`, {
    method: "PATCH", headers: await authHeaders(), body: JSON.stringify({ name }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
}

export async function deleteProfile(id: number): Promise<void> {
  const r = await fetch(`${BASE}/profiles/${id}`, {
    method: "DELETE", headers: await authHeaders(),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
}

// Read / write the ACTIVE profile document.
export async function getProfile(): Promise<any> {
  const r = await fetch(`${BASE}/profile`, { headers: await authHeaders() });
  const j = await r.json();
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

export async function saveProfile(profile: unknown): Promise<any> {
  const r = await fetch(`${BASE}/profile`, {
    method: "PUT", headers: await authHeaders(), body: JSON.stringify(profile),
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

// Upload a resume to populate the ACTIVE profile (multipart; empty slots only).
export async function importResume(file: File): Promise<any> {
  const fd = new FormData();
  fd.append("file", file, file.name);
  const r = await fetch(`${BASE}/profile/import-resume`, {
    method: "POST", headers: { "X-Local-Token": await getToken() }, body: fd,
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

export function openOptionsPage(): void {
  browser.runtime.openOptionsPage();
}

async function activeTabId(): Promise<number> {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  if (!tab || tab.id == null) throw new Error("No active tab.");
  return tab.id;
}

// Message the content script. If it isn't present yet (page was open before the
// extension loaded/updated), inject it from the manifest and retry once.
export async function sendToPage(msg: unknown): Promise<any> {
  const tabId = await activeTabId();
  try {
    return await browser.tabs.sendMessage(tabId, msg);
  } catch {
    const manifest = browser.runtime.getManifest() as any;
    const files: string[] = manifest.content_scripts?.[0]?.js || [];
    if (files.length) {
      await browser.scripting.executeScript({ target: { tabId }, files });
      return await browser.tabs.sendMessage(tabId, msg);
    }
    throw new Error("Could not reach the page. Reload the tab and try again.");
  }
}
