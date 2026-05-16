"""
EarCoach session logger.

Writes every hint event to a newline-delimited JSON file (one JSON object per
line). Each record captures everything needed for the ISWC evaluation:

  - timestamp
  - trigger type (long_pause | backspace_churn | manual | follow_up)
  - stuck score and per-signal breakdown
  - end-to-end latency (ms)
  - whether audio was spoken
  - the hint text
  - language and file name
  - diagnostic count (errors / warnings)
  - runtime error (from code runner)
  - frustration score, head movement

Log file location: ~/earcoach_sessions/session_<date>_<time>.jsonl
One file per backend startup. Safe to run multiple sessions.

To generate paper stats:
    python3 session_logger.py --analyse ~/earcoach_sessions/session_*.jsonl
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


SESSION_DIR = Path.home() / "earcoach_sessions"


class SessionLogger:
    def __init__(self) -> None:
        self._file = None
        self._path: Optional[Path] = None
        self._event_count = 0

    def start(self) -> None:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._path = SESSION_DIR / f"session_{ts}.jsonl"
        self._file = open(self._path, "w", encoding="utf-8")
        # Write session header
        self._write({
            "event": "session_start",
            "timestamp": datetime.now().isoformat(),
            "session_file": str(self._path),
        })
        print(f"[earcoach] session log → {self._path}")

    def stop(self) -> None:
        if self._file:
            self._write({
                "event": "session_end",
                "timestamp": datetime.now().isoformat(),
                "total_hints": self._event_count,
            })
            self._file.close()
            self._file = None

    def log_hint(
        self,
        *,
        trigger: str,
        language: str,
        file_name: str,
        stuck_score: int,
        stuck_breakdown: dict,
        latency_ms: int,
        spoken: bool,
        hint_text: str,
        error_count: int,
        warning_count: int,
        runtime_error: str,
        frustration_score: float,
        head_movement: float,
        head_available: bool,
        vscode_idle_ms: int,
        suppressed: bool = False,
    ) -> None:
        self._event_count += 1
        record = {
            "event": "hint",
            "timestamp": datetime.now().isoformat(),
            "seq": self._event_count,
            # Core metrics (go in the paper table)
            "trigger": trigger,
            "latency_ms": latency_ms,
            "spoken": spoken,
            "suppressed": suppressed,
            # Stuck model
            "stuck_score": stuck_score,
            "stuck_breakdown": stuck_breakdown,
            # Context
            "language": language,
            "file_name": file_name,
            "error_count": error_count,
            "warning_count": warning_count,
            "runtime_error": runtime_error[:300] if runtime_error else "",
            # Multimodal signals
            "frustration_score": frustration_score,
            "head_movement": head_movement,
            "head_available": head_available,
            "vscode_idle_ms": vscode_idle_ms,
            # Hint content (for quality rating)
            "hint_text": hint_text,
        }
        self._write(record)

    def log_suppressed(self, *, trigger: str, stuck_score: int, stuck_breakdown: dict, language: str, file_name: str) -> None:
        """Log events where the stuck scorer blocked a hint."""
        record = {
            "event": "suppressed",
            "timestamp": datetime.now().isoformat(),
            "trigger": trigger,
            "stuck_score": stuck_score,
            "stuck_breakdown": stuck_breakdown,
            "language": language,
            "file_name": file_name,
        }
        self._write(record)

    def _write(self, record: dict) -> None:
        if self._file:
            self._file.write(json.dumps(record) + "\n")
            self._file.flush()


# Singleton
session_logger = SessionLogger()


# ---------------------------------------------------------------------------
# Analysis CLI  (python3 session_logger.py --analyse file.jsonl ...)

def _analyse(paths: list[str]) -> None:
    import statistics

    hints = []
    suppressed = 0

    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec["event"] == "hint":
                    hints.append(rec)
                elif rec["event"] == "suppressed":
                    suppressed += 1

    if not hints:
        print("No hint events found.")
        return

    latencies = [h["latency_ms"] for h in hints if h["latency_ms"] > 0]
    scores = [h["stuck_score"] for h in hints]
    triggers = {}
    for h in hints:
        triggers[h["trigger"]] = triggers.get(h["trigger"], 0) + 1

    spoken = sum(1 for h in hints if h["spoken"])
    frustrated = [h for h in hints if h.get("frustration_score", 0) >= 0.5]
    with_runtime_err = [h for h in hints if h.get("runtime_error")]

    print("=" * 60)
    print("EarCoach Session Analysis")
    print("=" * 60)
    print(f"Total hint events:        {len(hints)}")
    print(f"Suppressed by scorer:     {suppressed}")
    print(f"Spoken (audio):           {spoken} / {len(hints)}")
    print()
    print("Latency (ms):")
    if latencies:
        print(f"  Mean:   {statistics.mean(latencies):.0f}")
        print(f"  Median: {statistics.median(latencies):.0f}")
        print(f"  Min:    {min(latencies)}")
        print(f"  Max:    {max(latencies)}")
    print()
    print("Triggers:")
    for t, n in sorted(triggers.items(), key=lambda x: -x[1]):
        print(f"  {t:<20} {n}")
    print()
    print("Stuck scores:")
    print(f"  Mean:   {statistics.mean(scores):.1f}")
    print(f"  Min:    {min(scores)}")
    print(f"  Max:    {max(scores)}")
    print()
    print(f"Hints with runtime error: {len(with_runtime_err)} / {len(hints)}")
    print(f"Hints while frustrated:   {len(frustrated)} / {len(hints)}")
    print()
    print("Hints (for quality rating):")
    print("-" * 60)
    for i, h in enumerate(hints, 1):
        print(f"[{i}] {h['timestamp'][:19]}  score={h['stuck_score']}  trigger={h['trigger']}")
        print(f"    File: {h['file_name']}  lang={h['language']}")
        if h.get("runtime_error"):
            print(f"    Error: {h['runtime_error'][:120]}")
        print(f"    Hint: {h['hint_text']}")
        print()


if __name__ == "__main__":
    if "--analyse" in sys.argv:
        files = [a for a in sys.argv[1:] if a != "--analyse"]
        if not files:
            print("Usage: python3 session_logger.py --analyse session_*.jsonl")
        else:
            _analyse(files)
    else:
        print("Session logger module. Import session_logger from your backend.")
        print("To analyse logs: python3 session_logger.py --analyse ~/earcoach_sessions/*.jsonl")
