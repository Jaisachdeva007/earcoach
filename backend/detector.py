"""
EarCoach stuck detector.

Runs a global pynput keyboard listener and exposes a tiny shared state object
the FastAPI backend can read. The detector itself does NOT call the LLM —
the VS Code extension is the trigger source for hints (because it has the code
context). The detector is here so the backend can corroborate "is this person
actually typing?" and so /health can show what the OS-level signal looks like.

Why it's separate from the extension:
    - The VS Code extension only sees text-document edits inside VS Code.
    - A real student switches to the browser, reads docs, scrolls Stack Overflow.
    - The OS-level pynput listener captures *all* keyboard activity, so a
      "long pause" inside VS Code with active typing in another window is
      correctly classified as "context-switching" rather than "stuck".
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque

try:
    from pynput import keyboard  # type: ignore
except Exception:  # pragma: no cover — pynput needs accessibility permission on macOS
    keyboard = None  # type: ignore


_STUCK_PAUSE_MS = 90_000          # >= 90s with no key = stuck candidate
_BACKSPACE_WINDOW_MS = 30_000     # rolling window for backspace count
_BACKSPACE_THRESHOLD = 8          # >= 8 backspaces in window = churn


class DetectorState:
    """In-process shared state. The FastAPI app imports the singleton below."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_key_time = time.monotonic()
        self._backspaces: Deque[float] = deque()
        self._listener: "keyboard.Listener | None" = None
        self._started = False

    # ----- public API used by main.py -----

    def start(self) -> None:
        if self._started:
            return
        if keyboard is None:
            # Detector is best-effort. If pynput can't load (no permission, headless),
            # the backend still works — the extension is the primary trigger.
            self._started = True
            return
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.daemon = True
        self._listener.start()
        self._started = True

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._started = False

    def is_stuck(self) -> bool:
        return self.idle_ms() >= _STUCK_PAUSE_MS

    def idle_ms(self) -> int:
        with self._lock:
            return int((time.monotonic() - self._last_key_time) * 1000)

    def recent_backspaces(self) -> int:
        with self._lock:
            self._prune()
            return len(self._backspaces)

    def is_churning(self) -> bool:
        return self.recent_backspaces() >= _BACKSPACE_THRESHOLD

    # ----- listener callback -----

    def _on_press(self, key) -> None:
        now = time.monotonic()
        with self._lock:
            self._last_key_time = now
            if key == keyboard.Key.backspace:  # type: ignore[union-attr]
                self._backspaces.append(now)
                self._prune()

    def _prune(self) -> None:
        cutoff = time.monotonic() - (_BACKSPACE_WINDOW_MS / 1000.0)
        while self._backspaces and self._backspaces[0] < cutoff:
            self._backspaces.popleft()


# Singleton imported by main.py
detector_state = DetectorState()


if __name__ == "__main__":
    # Quick smoke test: print state once a second until you hit Ctrl+C.
    detector_state.start()
    try:
        while True:
            print(
                f"idle={detector_state.idle_ms()}ms  "
                f"backspaces={detector_state.recent_backspaces()}  "
                f"stuck={detector_state.is_stuck()}"
            )
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        detector_state.stop()
