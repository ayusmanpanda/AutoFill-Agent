"""AutoFill Agent — local backend.

Endpoints:
  GET  /health                 liveness + configured provider/model (no auth)
  POST /llm/test               round-trips a prompt through the free LLM (auth)
  GET  /profile                read the stored profile (auth)
  PUT  /profile                save the profile (auth)
  GET  /profile/completeness   quick fill summary (auth)
  POST /profile/learn          save non-secret values typed on a page (auth, local-only)
  POST /pdf/analyze            read an uploaded PDF form's fields (auth)
  POST /pdf/plan               fill plan for an uploaded PDF (auth)
  POST /pdf/fill               download the filled PDF (auth, secrets stay blank)
  /static/editor.html          local profile editor page (open in a browser)
  /static/pdf.html             local PDF fill page (open in a browser)

Run from the backend/ folder:
  uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
"""
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import settings
from .forms.router import router as forms_router
from .pdf.router import router as pdf_router
from .privacy.guard import safe_completion
from .privacy.router import router as privacy_router
from .profile.router import profiles_router
from .profile.router import router as profile_router
from .rag.gen_router import router as generate_router
from .rag.router import router as fill_router
from .security import require_token

app = FastAPI(title="AutoFill Agent — Local Backend", version="0.1.0")

# Local-dev CORS. The extension calls us from a chrome-extension:// origin.
# Tighten allow_origins to your extension id before sharing widely.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "autofill-agent",
        "provider": settings.LLM_PROVIDER,
        "model": settings.LLM_MODEL,
    }


class LLMTestIn(BaseModel):
    prompt: str = "Say hello in one short sentence."


@app.post("/llm/test", dependencies=[Depends(require_token)])
def llm_test(body: LLMTestIn) -> dict:
    try:
        out = safe_completion([{"role": "user", "content": body.prompt}], max_tokens=100)
        return {
            "ok": True,
            "model": settings.LLM_MODEL,
            "reply": out["reply"],
            "redactions": out["redactions"],
        }
    except Exception as exc:  # surface provider errors to the client for debugging
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")


# Profile CRUD API (/profile ...)
app.include_router(profile_router)

# Multi-profile management API (/profiles ...)
app.include_router(profiles_router)

# Form analysis API (/forms ...)
app.include_router(forms_router)

# Privacy API (/privacy ...)
app.include_router(privacy_router)

# Fill-plan API (/fill ...)
app.include_router(fill_router)

# Answer-generation API (/generate ...)
app.include_router(generate_router)

# PDF form filling API (/pdf ...)
app.include_router(pdf_router)

# Serve the local profile editor at /static/editor.html
_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
