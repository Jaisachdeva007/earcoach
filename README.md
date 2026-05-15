# EarCoach

Earable AI scaffolding for novice programmers. Detects when a student is stuck while coding in VS Code and whispers a Socratic hint into their earphones — without breaking their visual focus on the code.

> System paper target: **ISWC 2026 Brief** (3 pages)

---

## How it works

You're coding. You hit a bug. You stop typing.

After 90 seconds of inactivity, EarCoach:
1. Reads your current code and any VS Code diagnostics (errors/warnings)
2. Sends it to a local LLM (no cloud, fully private)
3. Gets back a Socratic question — not the answer, a nudge
4. Speaks it into your earphones

Example: stuck on an `IndexError` in a list reversal → you hear *"What index does your loop start at, and when does it stop?"*

---

## Architecture

```
[VS Code Extension (TypeScript)]
   reads active file code + diagnostics + cursor line
   detects: long pause (90s) OR backspace churn (8 deletions/30s)
            │  HTTP POST /hint
            ▼
[FastAPI Backend (Python)]
   ├─ Socratic system prompt + Ollama (llama3.2:1b, local)  → hint text
   ├─ edge-tts (en-US-AriaNeural)                           → mp3
   └─ playsound → default audio device                      → earphones
            ▲
            │
[Stuck Detector (pynput)]
   global keystroke listener — corroborates VS Code idle signal
   exposes idle_ms / backspace count via GET /health
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

Open the `vscode-extension` folder in VS Code and press **F5**. A new **Extension Development Host** window opens with EarCoach loaded.

In that window:
- Open any `.py` file with a bug
- Stop typing for 90 seconds
- Listen

Manual trigger anytime: `Cmd+Shift+P` → **EarCoach: Ask for a hint now**

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
| `EARCOACH_SPEAK` | `1` | Set to `0` for text-only mode |
| `EARCOACH_OLLAMA_URL` | `http://localhost:11434/api/generate` | Ollama endpoint |

---

## macOS note

`pynput` needs accessibility access to monitor keystrokes. Go to **System Settings → Privacy & Security → Accessibility** and add Terminal. The system works without this — VS Code diagnostics still trigger hints — but the `/health` endpoint won't show live keystroke data.

---

## Project structure

```
earcoach/
├── backend/
│   ├── main.py          — FastAPI server, Ollama call, TTS, audio playback
│   ├── detector.py      — pynput keystroke monitor
│   ├── test_request.py  — smoke test
│   └── requirements.txt
└── vscode-extension/
    ├── src/
    │   └── extension.ts — stuck detector, context capture, backend POST
    ├── package.json
    └── tsconfig.json
```

---

## Evaluation (paper)

Three metrics, no user study required:

| Metric | Method |
|---|---|
| End-to-end latency | `latency_ms` from `/hint` averaged over 20 simulated stuck events |
| Hint quality | 30 hints rated on 4-point Socratic rubric (socratic / partial / directive / off-topic) |
| Detection precision | Replay 10 coding sessions, count true vs. false stuck firings |

---

## Research context

EarCoach extends prior work on AI scaffolding for novice programmers (Sachdeva et al., DCUTL 2026) into the wearable domain. Existing AI coding tools (Copilot, ChatGPT) are screen-based and require the student to break focus. EarCoach delivers help through the earable channel — ambient, proactive, and hands-free.
