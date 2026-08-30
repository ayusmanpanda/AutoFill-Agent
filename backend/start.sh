#!/usr/bin/env bash
# ==========================================================================
#  AutoFill Agent - backend launcher (macOS / Linux)
#  Run:  ./start.sh   (first: chmod +x start.sh)
#  On first run it sets up everything automatically.
# ==========================================================================
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  AutoFill Agent - starting local backend"
echo "============================================"
echo

# --- 1. Check Python ------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 not found. Install Python 3.10+ from https://www.python.org/downloads/"
  exit 1
fi

# --- 2. Create venv on first run -----------------------------------------
if [ ! -x ".venv/bin/python" ]; then
  echo "First run: creating virtual environment..."
  python3 -m venv .venv
  echo "Installing requirements (one-time, may take a minute)..."
  ./.venv/bin/python -m pip install --upgrade pip
  ./.venv/bin/python -m pip install -r requirements.txt
fi

# --- 3. Make sure a .env exists ------------------------------------------
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp ".env.example" ".env"
    echo
    echo "[ACTION NEEDED] A new .env file was created."
    echo "Edit it and set GROQ_API_KEY and LOCAL_TOKEN, then run this again."
    echo "  - Free key: https://console.groq.com/keys"
    echo "  - LOCAL_TOKEN: any random string (also paste it into the extension)"
    exit 0
  else
    echo "[ERROR] No .env or .env.example found."
    exit 1
  fi
fi

# --- 4. Start the server --------------------------------------------------
echo
echo "Backend running at http://127.0.0.1:8000  (health: /health)"
echo "Keep this window open. Press Ctrl+C to stop."
echo
exec ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
