# EarCoach

Earable AI scaffolding for novice programmers. Detects when a student is stuck while coding in VS Code and whispers a Socratic hint into their earphones — without breaking their visual focus on the code.

---

## How it works

You're coding. You hit a bug. You stop typing.

EarCoach detects you're stuck using a multimodal confidence model — combining typing idle time, backspace churn, frustration signals, and head stillness from your webcam. When the score crosses a threshold, it:

1. Runs your code and captures the actual runtime error
2. Reads VS Code diagnostics (static errors and warnings)
3. Fuses all signals and sends context to a local LLM (no cloud, fully private)
4. Gets back a Socratic question — not the answer, a nudge toward understanding
5. Speaks it into your earphones

Example: stuck on an `IndexError` in a list reversal → you hear *"What index does your loop access when `i` is zero?"*

**Keyboard shortcuts:**
- `Cmd+Shift+E` — trigger a hint immediately
- `Cmd+Shift+H` — ask for a follow-up / elaboration on the last hint
- `Escape` — dismiss the current hint

---

## Architecture

```
[VS Code Extension (TypeScript)]
   reads: active file code + diagnostics + cursor line
   detects: long pause (90s) | backspace churn | manual | follow-up
   languages: Python, JavaScript, TypeScript, Java, C, C++
            │  HTTP POST /hint  (code + diagnostics + idle time + churn)
            ▼
[FastAPI Backend (Python)]
   ├─ Code Runner  → executes code, captures runtime errors (IndexError, etc.)
   ├─ Stuck Scorer → multimodal confidence score (keystroke + head + frustration)
   ├─ Ollama LLM (llama3.2:1b, fully local) → Socratic hint text
   ├─ edge-tts (en-US-AriaNeural) → mp3
   ├─ playsound → default audio device → earphones
   └─ Session Logger → ~/earcoach_sessions/*.jsonl
            ▲
            │
[Keystroke Detector (pynput)]       [Head Stillness (MediaPipe + webcam)]
   OS-wide idle time                  nose-tip movement via face mesh
   backspace churn                    still head = stronger stuck signal
   frustration score (burst → silence)
```

Fully local. No data leaves the machine.

---

## Quick start

### Prerequisites

- Python 3.10+
- Node.js 18+
- [Ollama](https://ollama.com) installed

### 1. Pull the model

```bash
ollama pull llama3.2:1b
ollama serve
```

### 1b. (Optional) Enable head stillness detection

Requires camera access: **System Settings → Privacy & Security → Camera → Terminal**

```bash
pip install mediapipe opencv-python
```

If not installed, EarCoach works fine without it — head signals show as `unavailable` in `/health`.

### 2. Start the backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Verify it's running:
```bash
curl http://localhost:8000/health
```

Session logs are written automatically to `~/earcoach_sessions/` on startup.

### 3. Smoke test (no VS Code needed)

```bash
cd backend
python test_request.py
```

You should hear a Socratic hint spoken aloud about a buggy list-reversal function.

### 4. Load the VS Code extension

```bash
cd vscode-extension
npm install
npm run compile
```

Open the `vscode-extension` folder in VS Code and press **F5**. A new **Extension Development Host** window opens with EarCoach active.

In that window:
- Open any `.py`, `.js`, `.ts`, `.java`, `.c`, or `.cpp` file
- Write some code with a bug
- Stop typing — EarCoach fires when the stuck score crosses the threshold
- Listen

Manual trigger: `Cmd+Shift+P` → **EarCoach: Ask for a hint now**

---

## Session logs

Every hint and suppressed event is automatically saved to `~/earcoach_sessions/session_<date>.jsonl`. Each line is a JSON record containing the hint text, latency, stuck score, trigger, language, runtime error, and multimodal signals.

To analyse a session:

```bash
python3 backend/session_logger.py --analyse ~/earcoach_sessions/*.jsonl
```

Output includes:
- Mean / median / min / max latency
- Trigger breakdown
- Stuck score distribution
- Every hint in order for manual quality rating

---

## Configuration

### VS Code settings (`Cmd+,` → search "EarCoach")

| Setting | Default | Description |
|---|---|---|
| `earcoach.pauseThresholdMs` | `90000` | Idle time (ms) before stuck fires |
| `earcoach.backspaceWindowMs` | `30000` | Rolling window for backspace churn |
| `earcoach.backspaceThreshold` | `8` | Backspaces in window = churn |
| `earcoach.cooldownMs` | `120000` | Min time between auto hints |
| `earcoach.backendUrl` | `http://localhost:8000/hint` | Backend endpoint |

### Backend env vars

| Variable | Default | Description |
|---|---|---|
| `EARCOACH_OLLAMA_MODEL` | `llama3.2:1b` | Ollama model |
| `EARCOACH_TTS_VOICE` | `en-US-AriaNeural` | edge-tts voice |
| `EARCOACH_SPEAK` | `1` | Set to `0` for text-only (no audio) |
| `EARCOACH_OLLAMA_URL` | `http://localhost:11434/api/generate` | Ollama endpoint |
| `EARCOACH_STUCK_THRESHOLD` | `5` | Minimum stuck score to fire a hint |

---

## Stuck scoring model

Hints only fire when the multimodal confidence score reaches the threshold (default: 5).

| Signal | Score |
|---|---|
| VS Code idle ≥ 90s | +2 |
| VS Code idle ≥ 30s | +1 |
| Active error in editor | +3 |
| Active warning in editor | +1 |
| Backspace churn (≥ 8 deletions / 30s) | +2 |
| Frustration score ≥ 0.5 | +2 |
| Head still (webcam) | +2 |
| Head moving (webcam) | −2 |

Manual and follow-up triggers always fire regardless of score.

---

## macOS permissions

| Feature | Permission needed |
|---|---|
| Keystroke detector | System Settings → Privacy & Security → Accessibility → Terminal |
| Head stillness | System Settings → Privacy & Security → Camera → Terminal |

Both are optional — EarCoach works without them, with reduced stuck detection accuracy.

---

## Project structure

```
earcoach/
├── backend/
│   ├── main.py            — FastAPI server, hint endpoint, startup
│   ├── detector.py        — pynput keystroke monitor + frustration scoring
│   ├── head_stillness.py  — MediaPipe webcam head movement detector
│   ├── stuck_scorer.py    — multimodal confidence scoring model
│   ├── code_runner.py     — executes student code, captures runtime errors
│   ├── session_logger.py  — JSONL session log + analysis CLI
│   ├── test_request.py    — smoke test
│   └── requirements.txt
└── vscode-extension/
    ├── src/
    │   └── extension.ts   — stuck detection, context capture, hint trigger
    ├── package.json
    └── tsconfig.json
```
