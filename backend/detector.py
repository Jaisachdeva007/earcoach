"""
EarCoach stuck detector.

Runs a global pynput keyboard listener and exposes a tiny shared state object
the FastAPI backend can read. Tracks three signals:

  1. Idle time       — how long since the last keystroke (OS-wide)
  2. Backspace churn — rapid deletions on the same line (confusion signal)
  3. Typing bursts   — rapid short keystroke bursts followed by silence
                       (frustration proxy: the student hammers keys then stops)

The detector is a corroborating signal. The VS Code extension is the primary
trigger because it has code context. The detector adds OS-level awareness:
e.g. "long pause in VS Code but the student is actually typing in a browser"
is correctly classified as context-switching, not stuck.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, List

try:
    from pynput import keyboard  # type: ignore
except Exception:
    keyboard = None  # type: ignore


_STUCK_PAUSE_MS = 90_000
_BACKSPACE_WINDOW_MS = 30_000
_BACKSPACE_THRESHOLD = 8

# Frustration burst: >= N keystrokes in a short window, followed by silence
_BURST_WINDOW_MS = 4_000       # 4-second rolling window
_BURST_THRESHOLD = 20          # >= 20 keys in 4s = rapid burst
_BURST_SILENCE_MS = 3_000      # silence after burst = frustration signal


class DetectorState:
    """In-process shared state. The FastAPI app imports the singleton below."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_key_time = time.monotonic()
        self._backspaces: Deque[float] = deque()
        self._burst_keys: Deque[float] = deque()   # all keystrokes for burst tracking
        self._burst_fired_at: float = 0.0           # when the last burst was detected
        self._listener: "keyboard.Listener | None" = None
        self._started = False

    # ----- public API -----

    def start(self) -> None:
        if self._started:
            return
        if keyboard is None:
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
            self._prune_backspaces()
            return len(self._backspaces)

    def is_churning(self) -> bool:
        return self.recent_backspaces() >= _BACKSPACE_THRESHOLD

    def is_frustrated(self) -> bool:
        """True if a rapid typing burst was followed by silence — frustration proxy."""
        with self._lock:
            if self._burst_fired_at == 0.0:
                return False
            silence = time.monotonic() - self._last_key_time
            # Burst happened recently AND student has gone quiet since
            burst_age = time.monotonic() - self._burst_fired_at
            return burst_age < 30.0 and silence * 1000 >= _BURST_SILENCE_MS

    def frustration_score(self) -> float:
        """0.0–1.0 frustration estimate based on burst recency and silence duration."""
        with self._lock:
            if self._burst_fired_at == 0.0:
                return 0.0
            burst_age = time.monotonic() - self._burst_fired_at
            if burst_age > 30.0:
                return 0.0
            silence = time.monotonic() - self._last_key_time
            silence_norm = min(silence / (_BURST_SILENCE_MS / 1000.0), 1.0)
            recency_norm = 1.0 - (burst_age / 30.0)
            return round(silence_norm * recency_norm, 2)

    def burst_keys_in_window(self) -> int:
        with self._lock:
            self._prune_burst()
            return len(self._burst_keys)

    # ----- listener callback -----

    def _on_press(self, key) -> None:
        now = time.monotonic()
        with self._lock:
            self._last_key_time = now
            if key == keyboard.Key.backspace:  # type: ignore[union-attr]
                self._backspaces.append(now)
                self._prune_backspaces()

            self._burst_keys.append(now)
            self._prune_burst()
            if len(self._burst_keys) >= _BURST_THRESHOLD:
                self._burst_fired_at = now
                self._burst_keys.clear()  # reset so we don't re-fire immediately

    def _prune_backspaces(self) -> None:
        cutoff = time.monotonic() - (_BACKSPACE_WINDOW_MS / 1000.0)
        while self._backspaces and self._backspaces[0] < cutoff:
            self._backspaces.popleft()

    def _prune_burst(self) -> None:
        cutoff = time.monotonic() - (_BURST_WINDOW_MS / 1000.0)
        while self._burst_keys and self._burst_keys[0] < cutoff:
            self._burst_keys.popleft()


# Singleton imported by main.py
detector_state = DetectorState()


if __name__ == "__main__":
    detector_state.start()
    try:
        while True:
            print(
                f"idle={detector_state.idle_ms()}ms  "
                f"backspaces={detector_state.recent_backspaces()}  "
                f"burst_keys={detector_state.burst_keys_in_window()}  "
                f"frustrated={detector_state.is_frustrated()}  "
                f"frustration_score={detector_state.frustration_score()}  "
                f"stuck={detector_state.is_stuck()}"
            )
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        detector_state.stop()
