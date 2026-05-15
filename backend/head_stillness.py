"""
EarCoach head stillness detector.

Uses the Mac webcam and MediaPipe Face Mesh to estimate whether the student's
head has stopped moving — a reliable proxy for "staring blankly at the screen."

A moving head (nodding, looking around) suggests active thinking.
A still head combined with a long typing pause is a stronger stuck signal
than either alone.

Runs in a background thread. The FastAPI backend reads the shared state via
the singleton `head_state`.

Requires: pip install mediapipe opencv-python
macOS: Camera access must be granted to Terminal in
       System Settings → Privacy & Security → Camera.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

try:
    import cv2  # type: ignore
    import mediapipe as mp  # type: ignore
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


_STILLNESS_WINDOW_S = 3.0       # seconds of history to average over
_STILLNESS_THRESHOLD = 2.5      # pixel movement below this = "still"
_SAMPLE_INTERVAL_S = 0.1        # capture a frame every 100ms


class HeadStillnessState:
    """Thread-safe head stillness state read by the FastAPI backend."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._available = _AVAILABLE
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # Ring buffer of (timestamp, nose_x, nose_y)
        self._samples: list[tuple[float, float, float]] = []
        self._last_movement = 0.0   # avg pixel movement over recent window
        self._camera_ok = False

    # ----- public API -----

    def start(self) -> None:
        if not _AVAILABLE or self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def is_still(self) -> bool:
        """True if head hasn't moved meaningfully in the last few seconds."""
        with self._lock:
            return self._camera_ok and self._last_movement < _STILLNESS_THRESHOLD

    def movement_score(self) -> float:
        """Average pixel movement of nose tip over the stillness window. 0 = perfectly still."""
        with self._lock:
            return round(self._last_movement, 2)

    def is_available(self) -> bool:
        return _AVAILABLE

    def is_camera_ok(self) -> bool:
        with self._lock:
            return self._camera_ok

    # ----- background thread -----

    def _run(self) -> None:
        mp_face = mp.solutions.face_mesh  # type: ignore
        face_mesh = mp_face.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return

        with self._lock:
            self._camera_ok = True

        try:
            while self._running:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(_SAMPLE_INTERVAL_S)
                    continue

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = face_mesh.process(rgb)

                if result.multi_face_landmarks:
                    lm = result.multi_face_landmarks[0].landmark
                    # Nose tip = landmark 1
                    h, w = frame.shape[:2]
                    nx = lm[1].x * w
                    ny = lm[1].y * h
                    now = time.monotonic()
                    with self._lock:
                        self._samples.append((now, nx, ny))
                        self._prune_samples(now)
                        self._last_movement = self._compute_movement()

                time.sleep(_SAMPLE_INTERVAL_S)
        finally:
            cap.release()
            face_mesh.close()
            with self._lock:
                self._camera_ok = False

    def _prune_samples(self, now: float) -> None:
        cutoff = now - _STILLNESS_WINDOW_S
        self._samples = [(t, x, y) for (t, x, y) in self._samples if t >= cutoff]

    def _compute_movement(self) -> float:
        """Mean Euclidean distance between consecutive nose-tip positions."""
        if len(self._samples) < 2:
            return 0.0
        total = 0.0
        for i in range(1, len(self._samples)):
            _, x1, y1 = self._samples[i - 1]
            _, x2, y2 = self._samples[i]
            total += math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        return total / (len(self._samples) - 1)


# Singleton
head_state = HeadStillnessState()


if __name__ == "__main__":
    if not _AVAILABLE:
        print("mediapipe or opencv not installed. Run: pip install mediapipe opencv-python")
        raise SystemExit(1)

    head_state.start()
    print("Head stillness detector running. Press Ctrl+C to stop.")
    try:
        while True:
            print(
                f"still={head_state.is_still()}  "
                f"movement={head_state.movement_score()}px  "
                f"camera_ok={head_state.is_camera_ok()}"
            )
            time.sleep(1)
    except KeyboardInterrupt:
        head_state.stop()
