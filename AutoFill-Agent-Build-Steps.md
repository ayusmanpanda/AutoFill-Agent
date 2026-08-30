# AutoFill Agent — Build Steps (Python MVP → v1)

*A dependency-ordered roadmap. Each phase has a **Goal**, the **Steps**, and a **Done when** check so you always know what "finished" looks like. Build them in order — later phases assume earlier ones exist. Companion to `AutoFill-Agent-Architecture.md`.*

---

## Prerequisites (one-time)

- **Python 3.11+**, **Node 18+**, **git**, and **Chrome** (or Edge).
- A **free LLM API key** — start with **Groq** (fast, generous free tier) or **Google Gemini** (free tier + vision). You'll paste it into `.env`.
- Comfort with a terminal. Everything runs locally; nothing is deployed.

## Repo layout (monorepo)

```
autofill-agent/
├── backend/        # Python: FastAPI + agent + RAG + privacy
│   ├── app/
│   │   ├── main.py          # FastAPI app, local API + token
│   │   ├── profile/         # profile models + SQLite store
│   │   ├── perception/      # FormSchema types
│   │   ├── privacy/         # sensitivity classifier + egress scrub
│   │   ├── rag/             # chroma index + field mapping
│   │   ├── generate/        # open-ended answer generation
│   │   └── pdf/             # PDF form filling
│   ├── .env                 # YOUR api key (gitignored!)
│   └── requirements.txt
├── extension/      # TypeScript: WXT + React
└── README.md       # so your friend can run it
```

---

## Phase 0 — Foundations: get the two halves talking

**Goal:** a skeleton where clicking the extension reaches your local backend and a test LLM call returns text.

**Steps**

1. Create the repo and initialise git; add a `.gitignore` that excludes `.env`, `*.db`, and `.venv`.
2. Backend setup:
   ```bash
   cd backend && python3 -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install "fastapi" "uvicorn[standard]" litellm chromadb fastembed \
               pydantic python-dotenv pymupdf python-docx
   pip freeze > requirements.txt
   ```
3. Put your key in `backend/.env` (e.g. `GROQ_API_KEY=...`) and a random `LOCAL_TOKEN=...`.
4. Write a minimal FastAPI app bound to `127.0.0.1` with a `/health` endpoint and a `/llm/test` endpoint that calls the model through **LiteLLM**. Require the `LOCAL_TOKEN` on every request.
5. Extension setup: `cd ../extension && npm create wxt@latest .` then add a popup that calls `/health` and `/llm/test`.

**Done when:** clicking the extension shows "backend connected" and a round-trip LLM reply.

---

## Phase 1 — The profile (foundation of all filling)

**Goal:** a local, structured store of everything a form might ask for.

**Steps**

1. Define profile models with **Pydantic**, based on the **JSON Resume** schema — plus job-specific fields: work authorization / visa status, salary expectation, notice period, EEO/demographic answers (optional), links (LinkedIn, GitHub, portfolio).
2. Store it in **SQLite** (single file). Add CRUD endpoints.
3. Build a simple profile editor in the extension (or a local page) to fill it in once.
4. *(Optional now)* Résumé import: upload PDF/docx → extract text (PyMuPDF/python-docx) → LLM turns it into the profile JSON for review.

**Done when:** you can save and reload a complete profile locally.

---

## Phase 2 — Form perception (read any form)

**Goal:** the extension turns a live web form into a clean, structured `FormSchema`.

**Steps**

1. Content script: find fillable elements (`input`, `select`, `textarea`, `contenteditable`).
2. Associate a human label to each via `label[for]`, `aria-labelledby`, `aria-label`, `placeholder`, or nearest text.
3. Emit a normalized `FormSchema`: for each field `{ id, label, type, options, required, selector, autocomplete, sensitivityGuess }`. **Never read pre-filled values of sensitive fields.**
4. POST the `FormSchema` (structure only) to the backend and log it.

**Done when:** on a real job form (try a Greenhouse or Lever posting), you get back a tidy structured field list.

---

## Phase 3 — Privacy filter (build this BEFORE any LLM mapping)

**Goal:** secrets are gated out before a fill pipeline even exists — your non-negotiable rule, enforced structurally.

**Steps**

1. Sensitivity classifier, **rules first**: flag if `type=password`; if `autocomplete` ∈ {`current-password`, `new-password`, `one-time-code`, `cc-number`, `cc-csc`, `cc-exp`}; or if label/name matches keywords (`password`, `otp`, `2fa`, `cvv`, `pin`, `ssn`, `social security`, `account number`, `routing`, `captcha`).
2. Sensitive fields are marked `MANUAL` and **removed from all downstream processing** — never retrieved, embedded, generated, stored, or sent to the LLM.
3. Add an **egress scrubber**: middleware that inspects every LLM-bound payload and blocks anything matching secret-like patterns (card regex, etc.) as a backstop.
4. Write unit tests covering the rules with tricky field names.

**Done when:** on a form containing a password/OTP/card field, those are flagged `MANUAL`, and tests prove nothing sensitive can reach the model or the DB.

---

## Phase 4 — Field mapping via RAG (the core intelligence)

**Goal:** each ordinary field gets the right value from the profile.

**Steps**

1. Index the profile into **ChromaDB** using **local `fastembed`** embeddings — one document per fact, with the profile key in metadata. (Local embeddings keep profile text off the network.)
2. For each non-sensitive field: embed its label → retrieve top profile candidates → have the LLM select/format the value.
3. **Batch every field into ONE LLM call per form** (returns a JSON map `{ fieldId: { value, confidence, sourceKey } }`) — this respects free-tier rate limits.
4. Validate values against the field: dropdown values must match an option, dates/emails must match format, etc.

**Done when:** the backend returns a `FillPlan` covering the standard fields (name, email, phone, address, education, experience) with confidence scores.

---

## Phase 5 — Generation for open-ended questions

**Goal:** tailored drafts for essays and custom questions.

**Steps**

1. Detect free-text fields (textareas, long prompts like "Why this company?").
2. Scrape job context from the page (title, company, JD text).
3. LLM writes a tailored answer from `{ JD + profile + answer library }`.
4. Save good answers to an **answer library** (after the sensitivity screen) so future forms reuse and adapt them.

**Done when:** a "Why do you want to work here?" field gets a reasonable, editable draft.

---

## Phase 6 — Fill + review UI (human-in-the-loop)

**Goal:** values land in the page, you review, you submit.

**Steps**

1. Extension applies the `FillPlan`: set each value **and dispatch `input`/`change` events** so React/Vue-controlled inputs register it.
2. Highlight low-confidence fields; visually flag `MANUAL` fields and focus-prompt you to type them.
3. Review overlay to edit before submitting. **No auto-submit by default.**

**Done when:** full loop on a real form — auto-filled, you review, you type the secret fields yourself, you submit.

---

## Phase 7 — PDF forms (because "any form")

**Goal:** fill fillable PDFs with the same pipeline.

**Steps**

1. Backend endpoint: upload PDF → detect AcroForm fields with **PyMuPDF/pypdf** → run the same mapping → write values → return the filled PDF.
2. *(Optional)* Scanned PDFs: OCR with **Tesseract**, off by default for privacy.

**Done when:** a fillable PDF comes back correctly filled.

---

## Phase 8 — Harden & share with your friend

**Goal:** safe at rest and runnable on someone else's machine.

**Steps**

1. Encrypt the profile at rest (**SQLCipher** or a passphrase); use the OS keychain (`keyring`) only for opt-in saved values.
2. Package the backend (`pipx`, PyInstaller, or docker-compose) and the extension (load-unpacked or Chrome Web Store).
3. Write the `README` so a friend clones it, adds **their own** free API key, and runs it.
4. Add a small **eval set** (sample forms + expected fills) to track accuracy, and basic logging/observability (**Langfuse** or logs).

**Done when:** your friend runs it on their machine with their own key and fills a form end to end.

---

## Cross-cutting practices (do from day one)

- **Git from the start**; never commit `.env` or the profile DB.
- **MIT / Apache-2.0 license** so it's genuinely free and shareable.
- **No telemetry** — nothing phones home.
- Keep the **privacy boundary** visible in code: sensitive data should be structurally unable to reach storage or the LLM, not just "handled carefully."

## Suggested first week

Phase 0 → Phase 1 → Phase 2 → Phase 3. That gets you a real profile, a form reader, and the privacy guardrail — the spine everything else hangs off. Phases 4–6 turn it into a working filler; 7–8 make it complete and shareable.
