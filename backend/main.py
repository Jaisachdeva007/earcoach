"""
EarCoach backend.

Receives a stuck-event from the VS Code extension, asks a local Ollama model
for a Socratic hint, converts it to speech with edge-tts, and plays it through
the default audio device (which routes to whatever earable is connected).

Run:
    uvicorn main:app --host 127.0.0.1 --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import time
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import edge_tts
from playsound import playsound

from detector import detector_state        # keystroke signals
from head_stillness import head_state     # camera-based head stillness
from stuck_scorer import score_stuck, signals_from_request

# ---------------------------------------------------------------------------
# Config

OLLAMA_URL = os.getenv("EARCOACH_OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("EARCOACH_OLLAMA_MODEL", "llama3.2:1b")
TTS_VOICE = os.getenv("EARCOACH_TTS_VOICE", "en-US-AriaNeural")
SPEAK_AUDIO = os.getenv("EARCOACH_SPEAK", "1") == "1"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [earcoach] %(message)s")
log = logging.getLogger("earcoach")

# ---------------------------------------------------------------------------
# Socratic system prompt
#
# The single most important piece of EarCoach. Forces the model to produce a
# guiding question, never the answer. Kept short so the LLM doesn't drift.

SOCRATIC_SYSTEM = """\
You are EarCoach, a Socratic coding tutor for novice programmers.
The student is stuck. They are NOT looking at a screen — your reply will be
spoken into their earphones, so it must be SHORT and CLEAR.

STRICT RULES:
1. Reply with at most TWO sentences.
2. NEVER give the answer, the fixed code, or the exact bug location.
3. Ask ONE guiding question that nudges them toward the bug.
4. Reference the concept that's wrong (loop bound, type, indexing) without
   naming the fix.
5. Use plain spoken English — no code snippets, no markdown, no symbols.
6. Be warm, not condescending. They have been stuck for a while.

If you cannot infer a useful hint, ask them to describe what they expect the
code to do.
"""

USER_TEMPLATE = """\
Trigger: {trigger}
Language: {language}
File: {file_name}
Cursor line: {cursor_line}

Multimodal stuck signals:
- Keystroke idle: {idle_ms}ms
- Backspace churn: {backspaces} recent deletions
- Frustration score: {frustration_score} (0=calm, 1=frustrated)
- Head movement: {head_movement}px avg (low = staring at screen)

Errors and warnings currently flagged in the editor:
{diag_block}

Current code:
```
{code}
```

Reply with ONE Socratic question (max two sentences, spoken aloud).
"""


# ---------------------------------------------------------------------------
# Schemas

class Diagnostic(BaseModel):
    message: str
    line: int
    severity: str
    source: Optional[str] = None


class HintRequest(BaseModel):
    trigger: str = Field(..., description="long_pause | backspace_churn | manual | follow_up")
    language: str
    file_name: str
    cursor_line: int
    code: str
    diagnostics: List[Diagnostic] = []
    previous_hint: Optional[str] = None
    # VS Code-side signals for stuck scoring
    vscode_idle_ms: int = 0
    vscode_backspace_churn: bool = False


class HintResponse(BaseModel):
    hint: str
    spoken: bool
    latency_ms: int
    stuck_score: int = 0
    stuck_breakdown: dict = {}


# ---------------------------------------------------------------------------
# App

app = FastAPI(title="EarCoach", version="0.1.0")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model": OLLAMA_MODEL,
        "speaking": SPEAK_AUDIO,
        "detector": {
            "stuck": detector_state.is_stuck(),
            "last_keystroke_age_ms": detector_state.idle_ms(),
            "recent_backspaces": detector_state.recent_backspaces(),
            "is_frustrated": detector_state.is_frustrated(),
            "frustration_score": detector_state.frustration_score(),
            "burst_keys_in_window": detector_state.burst_keys_in_window(),
        },
        "head": {
            "available": head_state.is_available(),
            "camera_ok": head_state.is_camera_ok(),
            "is_still": head_state.is_still(),
            "movement_score": head_state.movement_score(),
        },
    }


@app.post("/hint", response_model=HintResponse)
async def hint(req: HintRequest):
    started = time.perf_counter()
    diag_block = format_diagnostics(req.diagnostics)
    follow_up_block = ""
    if req.trigger == "follow_up" and req.previous_hint:
        follow_up_block = f"\nPrevious hint given: {req.previous_hint}\nStudent asked for elaboration — go one step deeper, still Socratic.\n"

    user_prompt = USER_TEMPLATE.format(
        trigger=req.trigger,
        language=req.language,
        file_name=req.file_name,
        cursor_line=req.cursor_line,
        idle_ms=detector_state.idle_ms(),
        backspaces=detector_state.recent_backspaces(),
        frustration_score=detector_state.frustration_score(),
        head_movement=head_state.movement_score() if head_state.is_camera_ok() else "unavailable",
        diag_block=diag_block,
        code=truncate_code(req.code),
    )
    user_prompt += follow_up_block

    # --- Multimodal stuck scoring ---
    has_errors = any(d.severity == "error" for d in req.diagnostics)
    has_warnings = any(d.severity == "warning" for d in req.diagnostics)
    signals = signals_from_request(
        trigger=req.trigger,
        vscode_idle_ms=req.vscode_idle_ms,
        has_errors=has_errors,
        has_warnings=has_warnings,
        backspace_churn=req.vscode_backspace_churn or detector_state.is_churning(),
        os_idle_ms=detector_state.idle_ms(),
        frustration_score=detector_state.frustration_score(),
        head_available=head_state.is_camera_ok(),
        head_still=head_state.is_still(),
        head_movement=head_state.movement_score(),
    )
    stuck = score_stuck(signals)
    log.info("stuck scorer: %s", stuck)

    if not stuck.fired:
        log.info("hint suppressed by stuck scorer (score=%d < threshold=%d)", stuck.score, stuck.threshold)
        return HintResponse(hint="", spoken=False, latency_ms=0)

    log.info("hint trigger=%s file=%s diags=%d score=%d", req.trigger, req.file_name, len(req.diagnostics), stuck.score)

    try:
        text = await call_ollama(SOCRATIC_SYSTEM, user_prompt)
    except httpx.HTTPError as e:
        log.exception("ollama call failed")
        raise HTTPException(status_code=502, detail=f"Ollama unavailable: {e}") from e

    text = clean_hint(text)
    spoken = False
    if SPEAK_AUDIO and text:
        try:
            await speak(text)
            spoken = True
        except Exception:
            log.exception("tts/playback failed")

    latency_ms = int((time.perf_counter() - started) * 1000)
    log.info("hint latency=%dms spoken=%s text=%r", latency_ms, spoken, text)
    return HintResponse(hint=text, spoken=spoken, latency_ms=latency_ms, stuck_score=stuck.score, stuck_breakdown=stuck.breakdown)


# ---------------------------------------------------------------------------
# Helpers

def format_diagnostics(diags: List[Diagnostic]) -> str:
    if not diags:
        return "(none — code may compile but produce wrong output)"
    return "\n".join(
        f"- [{d.severity}] line {d.line}: {d.message}" for d in diags
    )


def truncate_code(code: str, max_chars: int = 4000) -> str:
    if len(code) <= max_chars:
        return code
    head = code[: max_chars // 2]
    tail = code[-max_chars // 2 :]
    return f"{head}\n# ... {len(code) - max_chars} chars trimmed ...\n{tail}"


_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")


def clean_hint(text: str) -> str:
    """Strip code fences, markdown, and overly long replies — anywhere they appear."""
    text = text.strip()
    # Remove fenced code blocks entirely; a Socratic spoken hint must not contain code.
    text = _CODE_FENCE_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    # Strip stray fence markers in case the model produced an unmatched one.
    text = text.replace("```", " ")
    # Collapse whitespace.
    text = " ".join(text.split())

    # Keep at most two sentences.
    sentences = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in ".?!":
            sentences.append(buf.strip())
            buf = ""
            if len(sentences) == 2:
                break
    if buf.strip() and len(sentences) < 2:
        sentences.append(buf.strip())
    return " ".join(sentences).strip()


async def call_ollama(system: str, user: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "system": system,
                "prompt": user,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 60,
                },
            },
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("response") or "").strip()


async def speak(text: str) -> None:
    """Generate TTS via edge-tts and play it through the default audio device."""
    fd, path = tempfile.mkstemp(suffix=".mp3", prefix="earcoach_")
    os.close(fd)
    try:
        communicator = edge_tts.Communicate(text, TTS_VOICE)
        await communicator.save(path)
        # playsound is blocking; run it in a thread so we don't pin the event loop.
        await asyncio.to_thread(playsound, path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Detector lifecycle — start the keystroke listener alongside the API.

@app.on_event("startup")
async def _start_detector():
    detector_state.start()
    head_state.start()
    log.info("detector started; ollama=%s model=%s", OLLAMA_URL, OLLAMA_MODEL)
    if head_state.is_available():
        log.info("head stillness detector started (mediapipe)")
    else:
        log.info("head stillness detector unavailable (install mediapipe + opencv)")


@app.on_event("shutdown")
async def _stop_detector():
    detector_state.stop()
    head_state.stop()
