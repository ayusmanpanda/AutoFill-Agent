# AutoFill Agent — Setup guide (for friends)

This tool runs **entirely on your own computer**. Nothing is uploaded to me or to
any shared server. You bring your **own free AI key**, and you pick your **own
local password** (the "local token"). Two people never share keys or data.

There are **two pieces**:

1. **The backend** — a small Python program that runs in the background.
2. **The extension** — the toolbar button in Chrome.

You set up the backend once, then load the extension once. After that you just
start the backend whenever you want to use it.

---

## What you need first (one time)

- **Python 3.10 or newer** — https://www.python.org/downloads/
  On Windows, tick **"Add python.exe to PATH"** in the installer.
- **Google Chrome** (or Edge / Brave — anything Chromium).
- The **AutoFill Agent folder** I sent you (unzip it somewhere like your Desktop).
- A **free Groq API key** (takes 1 minute) — see step 2.

You do **not** need Node.js — the extension comes pre-built.

---

## Step 1 — Start the backend (the easy way)

The folder includes a launcher that does everything for you.

- **Windows:** double-click **`start.bat`** in the `backend` folder.
- **Mac/Linux:** in a terminal in the `backend` folder run `chmod +x start.sh`
  once, then `./start.sh`.

On the **first run** it will:

1. create its own private Python environment and install what it needs, then
2. create a `.env` file and open it for you to fill in (see step 2), then stop.

Fill in the `.env` (step 2), then run the launcher **again** — this time it starts
the backend and prints `Backend running at http://127.0.0.1:8000`. Leave that
window **open** while you use the tool. Every time you want to use it later, just
run the launcher.

> Prefer typing commands yourself? See "Manual start" at the bottom.

---

## Step 2 — Get your own free AI key, then fill in `.env`

1. Go to **https://console.groq.com/keys**, sign in (free), click **Create API
   Key**, and copy it.
2. In the `.env` the launcher opened, set **two** things:

```
GROQ_API_KEY=paste-your-groq-key-here
LOCAL_TOKEN=pick-any-random-password-here
```

- `GROQ_API_KEY` — the key you just copied.
- `LOCAL_TOKEN` — **madeByAyusman** . It's a
  local password so only your browser can talk to your backend. You'll paste the
  same value into the extension in step 4. Don't reuse anyone else's.

Save the file, then run the launcher again to start the backend.
(Prefer Gemini? Comment out the Groq lines in `.env`, uncomment the Gemini ones,
and paste a key from https://aistudio.google.com/apikey.)

To confirm it's up, open http://127.0.0.1:8000/health — you should see
`{"status":"ok"}`.

---

## Step 3 — Load the extension in Chrome

The extension came **pre-built** in a folder named `chrome-mv3` (unzip it if it's a
`.zip`).

1. Open Chrome and go to **`chrome://extensions`**.
2. Turn on **Developer mode** (top-right toggle).
3. Click **Load unpacked**.
4. Select the **`chrome-mv3`** folder.

The AutoFill Agent icon appears in your toolbar. (Pin it via the puzzle-piece icon.)

---

## Step 4 — Connect the extension and add your profile

1. Click the AutoFill Agent icon.
2. Paste the **same `LOCAL_TOKEN`** you chose in step 2, click **Save token**.
3. Click **Check backend** — it should say OK.
4. Click **Manage** to open the options page. Add a profile (your name), fill in
   your details, or use **Import from résumé** to auto-fill the basics from a PDF.
5. Back on any job form: **Scan → Preview autofill → Fill page**. Review everything,
   then submit the form yourself.

You can add **multiple profiles** (e.g. for family members) and pick who you are
from the dropdown each time you open the popup.

---

## Privacy — what this tool will never do

- **Passwords, OTP/2FA codes, CAPTCHAs, card numbers/CVV/PIN, bank logins, SSN** are
  **never** filled, never stored, and never sent to the AI. You always type those by
  hand.
- The tool **never submits a form for you** — it fills, you review, you submit.
- Your profile lives in a local file on your machine. Your API key stays in your
  `.env`. Nothing is shared between you and your friends.

---

## Manual start (optional — instead of the launcher)

If you'd rather run the commands yourself, from the `backend` folder:

```powershell
python -m venv .venv                          # first time only
.\.venv\Scripts\Activate.ps1                  # Windows  (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt               # first time only
copy .env.example .env                         # first time only, then edit .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run each line separately — Windows PowerShell does not accept `&&`. If PowerShell
blocks the activate script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
once and press `Y`.

---

## Troubleshooting

- **`&&` error in PowerShell** — run each command on its own line, or join with `;`.
- **Extension says backend failed** — is the `uvicorn` window still open (step 4)?
  Is the token in the extension exactly the same as `LOCAL_TOKEN` in `.env`?
- **`python` not found** — reinstall Python with "Add to PATH" ticked, reopen the
  terminal.
- **LLM test fails** — check your `GROQ_API_KEY` is pasted correctly and has no extra
  spaces.
