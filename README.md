# AutoFill-Agent
Use RAG , Agentic AI, Web Scarrping, and Full Stack Idea that autofill all you RESUME
# AutoFill Agent

A free, **local-first**, privacy-preserving agentic-RAG tool that fills any form (web + PDF), aimed at job applications. Everything runs on your machine; only anonymized text is sent to a free cloud LLM tier, and **secrets (passwords, OTP, CAPTCHA, card, PIN, SSN) are always typed manually and never stored or sent.**

This repo currently contains **Phase 0** (connectivity skeleton), **Phase 1** (the local profile store + editor), **Phase 2** (form perception — scanning a page's fields), **Phase 3** (the privacy filter — sensitivity classifier + egress PII scrub), **Phase 4** (RAG field mapping — matching perceived fields to your profile), **Phase 5** (answer generation — writing the free-text responses from your profile), and **Phase 6** (one-click fill with human review, plus the extension rebuilt on WXT + React). See `AutoFill-Agent-Architecture.md` and `AutoFill-Agent-Build-Steps.md` (in the planning docs) for the full design and roadmap.

```
AI Forms/
├── backend/            # Python — FastAPI local API
│   ├── app/
│   │   ├── config.py       # settings from .env
│   │   ├── security.py     # X-Local-Token guard (shared dependency)
│   │   ├── main.py         # /health + /llm/test + mounts profile, forms & privacy APIs
│   │   ├── profile/
│   │   │   ├── schema.py    # Pydantic profile models (JSON Resume + job fields)
│   │   │   ├── store.py     # single-document SQLite store (data/profile.db)
│   │   │   └── router.py    # GET/PUT /profile, GET /profile/completeness
│   │   ├── forms/
│   │   │   ├── schema.py    # PerceivedForm / PerceivedField contract
│   │   │   └── router.py    # POST /forms/analyze (validate + summarize)
│   │   ├── privacy/
│   │   │   ├── classifier.py # SECRET/PII/SAFE sensitivity rules (authoritative)
│   │   │   ├── scrub.py      # stateful egress PII scrubber (+ local rehydrate)
│   │   │   ├── guard.py      # safe_completion() — the only path to the cloud LLM
│   │   │   └── router.py     # POST /privacy/plan, POST /privacy/scrub-test
│   │   ├── rag/
│   │   │   ├── flatten.py    # Profile -> flat retrievable facts (key/value/kind/hint)
│   │   │   ├── resolver.py   # deterministic field -> fact match (autocomplete + labels)
│   │   │   ├── mapper.py     # LLM fallback matcher (keys only, never values)
│   │   │   ├── plan.py       # build_plan() orchestrator (fill/manual/generate/unmapped)
│   │   │   ├── generate.py   # grounded answer writer for free-text fields (scrubbed)
│   │   │   ├── router.py     # POST /fill/plan
│   │   │   └── gen_router.py # POST /generate/answers, POST /generate/answer
│   │   └── static/
│   │       ├── editor.html  # local profile editor page
│   │       └── editor.js
│   ├── .env.example
│   └── requirements.txt
└── extension/          # Legacy no-build MV3 extension (kept as a fallback)
    ├── manifest.json
    ├── popup.html
    ├── popup.js
    └── content.js      # injected on demand to read a page's fields

webext/                 # Phase 6 extension — WXT + React + TypeScript (the build we use now)
├── entrypoints/
│   ├── content.ts      # page agent: AUTOFILL_PERCEIVE (read) / AUTOFILL_APPLY (fill, never submit)
│   └── popup/
│       ├── App.tsx     # popup UI: token, scan, preview, draft, and one-click Fill page
│       ├── main.tsx    # React entry
│       ├── index.html
│       └── style.css
├── lib/
│   ├── perceive.js     # form perception, ported to a plain-JS ESM module (unit-tested)
│   ├── fill.js         # DOM fill core — React-safe value setter, secrets refused (unit-tested)
│   └── api.ts          # backend (loopback) calls + page messaging with fallback injection
├── tests/
│   ├── fill.test.mjs   # offline node tests for the fill core
│   └── perceive.test.mjs # offline node tests for the perception helpers
├── wxt.config.ts
├── tsconfig.json
└── package.json
```

## Phase 0 quickstart

### 1. Backend

From the `backend/` folder:

```powershell
# Windows (PowerShell)
cd "backend"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

```bash
# macOS / Linux
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and set:
- `GROQ_API_KEY` — get a free key at https://console.groq.com/keys (or use Gemini: uncomment `GEMINI_API_KEY` and switch `LLM_MODEL`).
- `LOCAL_TOKEN` — any random string; you'll paste the same value into the extension.

Run the server (from `backend/`):

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Visit http://127.0.0.1:8000/health — you should see `{"status":"ok", ...}`.

### 2. Extension

1. Open `chrome://extensions` (or `edge://extensions`).
2. Turn on **Developer mode**.
3. Click **Load unpacked** and select the `extension/` folder.
4. Click the extension icon → paste your `LOCAL_TOKEN` → **Save token**.
5. Click **Check backend** (should say *Backend connected ✔*), then **Test LLM** (should return a one-line reply from the model).

If both work, Phase 0 is done — the two halves are talking.

## Phase 1 — profile store

Your profile is stored as a single validated JSON document in `backend/data/profile.db` (SQLite, created automatically, gitignored). No secrets ever go in it.

With the backend running, open the local editor:

```
http://127.0.0.1:8000/static/editor.html
```

Paste your `LOCAL_TOKEN` at the top and click **Remember**, then **Load** to pull the current profile and **Save** to store your edits. Simple fields have their own inputs; list sections (work, education, skills, projects, social profiles) are edited as JSON.

Endpoints (all require the `X-Local-Token` header):

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/profile` | Read the stored profile (empty template if none yet) |
| PUT | `/profile` | Validate and save the full profile |
| GET | `/profile/completeness` | Quick summary of which key sections are filled |

Next up: **Phase 2 — form perception** (reading the fields on a page).

## Phase 2 — form perception

The extension can now read a page's form into a normalized structure — every field's type, best human label (from `<label>`, ARIA, `<legend>`, placeholder, or the field name), whether it's required, select/radio options, and whether it's a **secret** (password, OTP, CVV, card, PIN, SSN, bank). Field *values* are never read, and secrets are flagged so later phases leave them for manual entry.

With the backend running and the extension reloaded (bump is `v0.2.0`), open any form — a job application, or the local editor page — click the extension icon, then **Scan this page**. You'll see a summary like:

```
12 fields — Careers — Application
Types: email×1, select×2, text×7, textarea×1, tel×1
Manual-only (never stored): Password

• Full name [text] *
• Email [email] *
• Phone [tel]
• Password [password] * (secret)
…
```

The scan is also POSTed to the backend, which returns a validated summary (counts, how many are fillable vs. manual-only). The full structured form is logged to the extension's console (right-click the popup → Inspect) for a closer look.

Endpoint (requires the `X-Local-Token` header):

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/forms/analyze` | Validate a perceived form and summarize it |

This normalized structure is the input the RAG field-matching will consume next.

## Phase 3 — the privacy filter

Before any field text can go to the cloud LLM, it passes through a dedicated privacy layer. This is where the project's hard rule lives: **secrets are never stored, never embedded, and never sent to the model — they are left for you to type manually.**

Two mechanisms enforce it:

**1. An authoritative sensitivity classifier** (`privacy/classifier.py`) buckets every field into one of three levels. It runs on the backend and never trusts the extension's own flags.

| Level | Examples | What happens |
| --- | --- | --- |
| `SECRET` | password, OTP/2FA, CAPTCHA, CVV, card/bank number, PIN, SSN | Manual entry only — never stored or sent |
| `PII` | name, email, phone, address, date of birth | Filled locally from your profile, but scrubbed out of anything sent to the LLM |
| `SAFE` | job titles, skills, free-text questions | May be reasoned about by the model |

The rules are separator-aware, so snake_case and camelCase names (`user_otp`, `cardNumber`) are classified the same as their spaced labels, and locale traps like the Indian **PIN Code** are treated as an address (PII), not a secret.

**2. A stateful egress scrubber** (`privacy/scrub.py`) is the safety net for PII. Every cloud call goes through the single choke point `safe_completion()` (`privacy/guard.py`), which scrubs known profile values and format-detected PII (emails, phone numbers, card/SSN-shaped digits) into typed placeholders like `[[EMAIL_1]]`, calls the model, then re-hydrates the reply locally. The placeholder→value map never leaves your machine. Because `/llm/test` now routes through `safe_completion` too, no code path reaches the model without scrubbing first.

With the backend running and the extension reloaded, **Scan this page** now shows an egress summary:

```
Cloud-eligible: 6 safe · Kept on device: 4 (1 secret, 3 PII) ✔
```

Endpoints (both require the `X-Local-Token` header):

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/privacy/plan` | Classify each field of a perceived form; report per-field action + cloud-eligible vs. kept-local counts |
| POST | `/privacy/scrub-test` | Preview the egress scrub on a piece of text (returns redacted text + per-type counts only) |

Next up: **Phase 4 — RAG field mapping** (matching perceived SAFE/PII fields to your profile, with SECRET fields structurally excluded from the LLM).

## Phase 4 — RAG field mapping

Given a perceived form and your stored profile, the backend now builds a **fill plan**: for each field it decides *what would go in it and where that value comes from*. It resolves every field in this order:

1. **Authoritative classify.** `SECRET` fields (password, OTP, CVV, card, PIN, SSN) are set to `manual_entry` immediately — they are never resolved, never valued, and never sent anywhere.
2. **Deterministic resolver** (`rag/resolver.py`) — no LLM, no network. It maps a field to a profile fact using the `autocomplete` token first (`email`, `given-name`, `postal-code`, `country`, …), then a label/name regex. For dropdowns and radios it matches your value against the field's actual options (e.g. country `India` → the `IN` option). This handles the bulk of an application's identity/contact/location fields instantly and for free.
3. **LLM matcher** (`rag/mapper.py`) — only for leftover `SAFE`/`PII` fields. Crucially, it is shown the field labels and a catalog of profile **keys with short hints — never your values**. It just picks which key answers each field; the actual value is pulled locally by key afterward. The call still routes through `safe_completion`, so the privacy guarantee holds even here.
4. **Anything still unmatched:** a `SAFE` free-text field becomes `generate` (Phase 5 will write the answer); everything else is `unmapped`.

Each field ends up with one of four actions:

| Action | Meaning |
| --- | --- |
| `fill` | A value was found (from a profile key); ready to fill locally |
| `manual_entry` | A secret — you type it yourself; we never touch it |
| `generate` | A free-text answer to be written in Phase 5 |
| `unmapped` | No profile match (and, for dropdowns, no matching option) |

The plan is **preview only** — it does not modify the page. Applying it with human review comes in Phase 6. With the backend running and the extension reloaded (bump is `v0.3.0`), click **Preview autofill** to see something like:

```
Fill 6 · Generate 2 · Manual 3 · Unmapped 1

• Email [email] → jane@example.com
• First Name [text] → Jane
• Country [select] → IN
• Password [password] → manual entry (secret)
• Tell us about yourself [textarea] → write answer (Phase 5)
…
```

Endpoint (requires the `X-Local-Token` header):

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/fill/plan` | Build a per-field fill plan. `?use_llm=false` forces a pure-local run (deterministic matches only, no cloud call at all) |

Resolved values are returned only over loopback to your local extension — they never go to the cloud. The one thing that can reach the model is field labels plus profile *keys*, and only when a leftover field needs matching.

Next up: **Phase 5 — answer generation** (writing the free-text `generate` fields — cover-letter-style responses — from your profile, still routed through the privacy scrub).

## Phase 5 — answer generation

Some application fields can't be looked up — they have to be *written*: "Why do you want to work here?", "Tell us about yourself", "Describe a challenge you overcame." Phase 4 marks these `generate`. Phase 5 writes them, grounded in your profile.

The generator (`rag/generate.py`) builds a compact **profile digest** — your headline, summary, recent roles, skills, and the bullet-point highlights from your work and projects — and asks the model to answer each open question in your own voice. It is told, firmly, to use **only** the facts in that digest: no invented employers, titles, dates, degrees, or achievements. For a single targeted question it first does lightweight **lexical retrieval** over your highlights (ranking them by word overlap with the question) so the most relevant experience leads.

Two ways to call it:

- **Batched** (`POST /generate/answers`): send a whole perceived form. The backend builds the fill plan, then writes every `generate` field in **one model call**. Each answered field is promoted from `generate` to `fill` and tagged `via: "generated"`; the response also carries a `generated` count. Batching keeps you under free-tier rate limits.
- **Single** (`POST /generate/answer`): send one `{question, max_length?, tone?}` and get back `{answer, redactions}` — handy for regenerating just one box.

Everything still flows through the same privacy choke point (`safe_completion`): PII is scrubbed to typed placeholders before the call and rehydrated locally afterward, and because only `SAFE` free-text fields are ever `generate` candidates, **no secret or sensitive field is ever part of a generation request**. Character limits declared by the page (`maxlength`) are passed to the model as a budget, so answers fit the box.

With the backend running and the extension reloaded (bump is `v0.4.0`), click **Draft answers**. The plan re-renders with the written text in place, marked `✎`:

```
Fill 8 · Generate 0 · Manual 3 · Unmapped 1
(2 answers drafted — marked ✎)

• Email [email] → jane@example.com
• Why do you want to work here? [textarea] → ✎ I'm drawn to your work on payments…
• Tell us about yourself [textarea] → ✎ I'm a backend engineer who…
• Password [password] → manual entry (secret)
…
```

Like the plan, this is **preview only** — nothing is typed into the page yet (that's Phase 6). You review and edit the drafts first.

Endpoints (both require the `X-Local-Token` header):

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/generate/answers` | Build the fill plan, then draft all free-text answers; returns the plan with them promoted to `fill`/`via=generated` |
| POST | `/generate/answer` | Draft a single answer to one question (`{question, max_length?, tone?}`) |

Next up: **Phase 6 — fill + review UI** (applying the plan to the page with human review, and migrating the extension to WXT + React).

## Phase 6 — one-click fill (with review) + WXT/React rebuild

This is the first phase that **writes to the page** — and it does so only when you ask, and it **never submits the form**. You stay in the loop: preview or draft a plan, glance at it, click **Fill page**, then review every field yourself before submitting.

Two things landed here.

**1. The extension is rebuilt on WXT + React + TypeScript.** The old no-build extension is kept at `extension/` as a fallback, but the extension we use now lives in `webext/` and is a proper Vite/WXT project with a React popup. To keep the migration safe, the risky logic is *not* in the React/TSX shell — it's in two plain-JS ESM modules that run in Node with no browser:

- `lib/perceive.js` — the Phase 2 perception, ported unchanged in behavior (still never reads a field's value, still flags secrets).
- `lib/fill.js` — the new DOM-writing core.

Both are covered by offline unit tests in `webext/tests/` (21 tests), so the parts that touch your data are verified without needing a browser.

**2. A one-click Fill page button.** Applying a plan is deliberately careful:

- It fills **only** records the backend marked `fill` (including Phase 5's generated answers). `manual_entry`, `unmapped`, and anything flagged sensitive are refused in the fill core itself — so **secrets are never written, as defense in depth** even if a plan were malformed.
- Modern job sites (Workday, Greenhouse, Lever) use React-controlled inputs that ignore `element.value = …`. The fill core sets the value through the native prototype setter, nudges React's internal value tracker, and dispatches real `input`/`change`/`blur` events so the site registers the change. Selects match by option value then by visible label; radios/checkboxes check the option whose value matches.
- Each field is re-found by a **selector** captured during perception, so filling doesn't depend on the page staying identical between scan and fill.
- It **never calls submit** and never clicks a submit button. Filling is where the agent stops; you review and send.

After a fill you get a report of exactly what happened:

```
Filled 6 · skipped 4 · not found 0 · no option 0

Review every field before submitting — nothing was submitted.

Filled:
  ✓ Full name
  ✓ Email
  ✓ Why do you want to work here?
  …
```

### Building and running the Phase 6 extension

The `webext/` project has a build step (it's a real npm project), so unlike the old extension you install dependencies and run a dev build once:

```bash
cd webext
npm install
npm run dev
```

WXT builds the extension into `webext/.output/chrome-mv3-dev/`. Then, in the browser:

1. Open `chrome://extensions` (or `edge://extensions`) and turn on **Developer mode**.
2. Click **Load unpacked** and select `webext/.output/chrome-mv3-dev/`.
3. Click the extension icon → paste your `LOCAL_TOKEN` → **Save token** → **Check backend**.

`npm run dev` hot-reloads as you edit. For a production build use `npm run build` (output in `.output/chrome-mv3/`). The old `extension/` folder still loads unpacked if you want the no-build fallback.

Typical flow on a job application: **Scan this page** to see what's there → **Preview autofill** (or **Draft answers** for the free-text boxes) → look over the plan → **Fill page** → review every field → submit it yourself.

## Learn from page (remember missing details)

Some fields have no home in your profile yet — a LinkedIn URL you never saved, for
example — so they fill in empty. Instead of asking you to re-type them on every
application, the agent can **learn** them: type the value once, and it's saved to
your profile so it auto-fills next time.

Two ways it happens:

- **Automatically after a fill.** When you click **Fill page**, the agent reads
  back the non-secret values already on the page and quietly saves any that fill an
  empty profile slot. The popup shows a short "learned …" note so it's never a
  surprise.
- **On demand.** Fill in whatever you like by hand, then click **Learn from page**
  to capture it immediately.

Guarantees (all enforced on the backend, `POST /profile/learn` — no LLM, no network):

- **Secrets are never read or stored.** Passwords, OTP, CVV, card/PIN, SSN and any
  field classified sensitive are refused before their value is ever looked at.
- **Only profile fields.** Just the whitelisted single-value slots are learnable
  (name, email, phone, website, address/city/region/postal/country, LinkedIn,
  GitHub, portfolio, work authorization, notice period, start date, work mode,
  desired salary). Work history, education, skills, yes/no preferences and
  voluntary EEO answers are **not** auto-learned — edit those in the profile page.
- **Non-destructive.** Only *empty* slots are filled; an existing value is never
  overwritten, so a page typo can't clobber good profile data.

Learned values are written to exactly the place the fill step reads from, so the
round-trip holds (learn once → auto-fills forever after).

Next up: **Phase 7 — PDF forms** (filling the same profile into PDF application forms).

## Phase 7 — PDF forms

Not every application is a web page. Many employers hand you a **fillable PDF** (an
AcroForm). Phase 7 fills those from the exact same profile, reusing the exact same
privacy pipeline — so the guarantees you trust on web forms carry over unchanged.

**Library: `pypdf` (not PyMuPDF).** The roadmap originally guessed PyMuPDF, but
`pypdf` is **pure-Python with no binary/system dependencies**, which makes it both
trivial to `pip install` on a friend's machine *and* unit-testable offline. That's a
better fit for a free, local, shareable tool, so this phase deliberately swaps to it.

**How it works.** A PDF is read into normalized fields (text / textarea / select /
radio / checkbox), using each field's tooltip (`/TU`) as its human label. Those
fields flow through the **same classifier and the same `build_plan`** the web path
uses, then the plan is written back into the AcroForm with `pypdf`.

**Privacy is identical to the web path.** Secret fields (SSN, card, CVV, PIN, bank,
password) are classified `SECRET`, marked `manual_entry`, and **never written** — the
`is_fillable()` gate in `app/pdf/fill.py` refuses to write any secret record as
defense in depth, mirroring `lib/fill.js`. The filled PDF is **handed back to you as a
download over loopback and submitted nowhere**. You review it, type any secrets by
hand, and submit it yourself.

Endpoints (all token-guarded, multipart upload):

| Endpoint | Does |
|---|---|
| `POST /pdf/analyze` | normalized fields + a sensitivity summary (no fill) |
| `POST /pdf/plan?use_llm=` | the per-field fill plan (same shape as `/fill/plan`) |
| `POST /pdf/fill?use_llm=` | streams the **filled** PDF back as an attachment |

**Using it.** With the backend running, open **`http://127.0.0.1:8000/static/pdf.html`**,
paste your local token, pick a PDF, click **Review plan** to see exactly what will be
filled (secrets shown as *manual*), then **Fill & download**. Leave *use LLM* off for
local-only matching, or tick it to let the (values-free) matcher handle tricky labels.

Verify offline (pure-Python, no web stack needed):

```bash
cd backend
python3 tests/test_pdf.py     # builds an AcroForm fixture → perceive → plan → fill,
                              # proves identity fields fill and SSN stays EMPTY
```

Next up: **Phase 8 — harden & share** (packaging, docs, and locking down for handoff).

## Multiple profiles + in-extension editing + resume import

Profiles now live **inside the extension** — no more opening a URL to edit them.

- **One profile per person, kept separate.** The backend stores each person in a
  single SQLite DB (`profiles` table) with an `app_state.active_profile_id` pointer.
  Everything downstream (fill / PDF / learn / generate) transparently uses the
  **active** profile, so `get_profile()` / `save_profile()` still take no args.
  Legacy single-profile data is migrated automatically into a "Default" profile
  on first run.

- **Pick who you are on open.** The popup shows a "Profile (who are you?)" selector;
  switching activates that person's profile for the whole session and forces a fresh
  plan (so one person's data never carries into another's).

- **Full options page.** "Manage" (popup) opens the extension's options tab
  (`webext/entrypoints/options/`) — a React port of the old `editor.html`. Add /
  rename / delete / switch profiles, edit Basics / Job preferences / Voluntary
  fields and the JSON sections (work, education, skills, projects, social,
  preferred locations), and save.

- **Resume import (100% local).** On the options page, upload a PDF or text résumé
  to fill **empty** profile slots only. Text is extracted with `pypdf` (PDF) or
  decoded (`.txt`), then email / phone / LinkedIn / GitHub / name are pulled with
  regex and applied via the same non-destructive `apply_learned` path used by
  "Learn from page". **No upload to any server or LLM; secrets are never read;**
  work history and education are left for you to fill in manually.

Profile API (all token-guarded, loopback only):

| Method | Path | Purpose |
|---|---|---|
| GET | `/profiles` | list profiles (`{id,name,updated_at,active}`) |
| POST | `/profiles` | create + activate (`{name}`; 409 on duplicate) |
| POST | `/profiles/{id}/activate` | switch active profile (404 if missing) |
| PATCH | `/profiles/{id}` | rename |
| DELETE | `/profiles/{id}` | delete (refuses the last one; re-points active) |
| POST | `/profile/import-resume` | multipart résumé → fill empty slots of active |

Offline verification:

```bash
python3 tests/test_profiles_store.py   # mirror-SQL: seed/migrate/switch/delete rules
python3 tests/test_resume.py           # regex facts, no false phones, empty-slots-only
cd ../webext && npx tsc --noEmit       # options page + popup selector type-check
```

## Notes

- The real `.env` is gitignored — never commit your API key.
- Free LLM tiers have rate limits; later phases batch requests to stay under them.
- The extension now builds with WXT + React (`webext/`); the plain no-build `extension/` folder is kept as a fallback. The data-touching logic (`webext/lib/perceive.js`, `webext/lib/fill.js`) is plain JS with offline node tests, so it's verified without a browser.

## License

MIT (intended — add a LICENSE file before publishing).
