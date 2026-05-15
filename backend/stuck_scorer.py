"""
EarCoach multimodal stuck scorer.

Combines signals from the VS Code extension, the keystroke detector, and the
head stillness detector into a single confidence score (0–10). A hint fires
only when this score crosses a threshold.

Signal weights:
  +2  idle > 90s in VS Code
  +1  idle > 30s in VS Code (partial credit)
  +3  active error diagnostics in editor
  +1  active warning diagnostics in editor
  +2  backspace churn (>= 8 deletions / 30s)
  +2  frustration score >= 0.5 (burst → silence)
  +2  head still (< 2.5px avg movement)
  -2  head moving (student actively reading/thinking)

Fire threshold: >= 5  (configurable via EARCOACH_STUCK_THRESHOLD env var)

This scoring model is the core research contribution for the ISWC paper —
it makes explicit what "stuck" means across modalities and allows ablation
studies (what happens to precision/recall when you remove each signal).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional


FIRE_THRESHOLD = int(os.getenv("EARCOACH_STUCK_THRESHOLD", "5"))


@dataclass
class StuckSignals:
    """Snapshot of all signals at the moment of evaluation."""
    # From VS Code extension
    vscode_idle_ms: int = 0
    has_errors: bool = False
    has_warnings: bool = False
    backspace_churn: bool = False
    trigger: str = "long_pause"

    # From keystroke detector
    os_idle_ms: int = 0
    frustration_score: float = 0.0

    # From head stillness detector
    head_available: bool = False
    head_still: bool = False
    head_movement: float = 0.0


@dataclass
class StuckScore:
    """Result of scoring a set of stuck signals."""
    score: int
    fired: bool
    threshold: int
    breakdown: dict = field(default_factory=dict)

    def __str__(self) -> str:
        parts = [f"{k}={v:+d}" for k, v in self.breakdown.items() if v != 0]
        return f"score={self.score}/{self.threshold} fired={self.fired} [{', '.join(parts)}]"


def score_stuck(signals: StuckSignals) -> StuckScore:
    """
    Compute stuck confidence score from multimodal signals.
    Returns a StuckScore with the total, fired flag, and per-signal breakdown.
    """
    breakdown: dict[str, int] = {}

    # --- VS Code idle time ---
    if signals.vscode_idle_ms >= 90_000:
        breakdown["vscode_idle_90s"] = 2
    elif signals.vscode_idle_ms >= 30_000:
        breakdown["vscode_idle_30s"] = 1
    else:
        breakdown["vscode_idle_30s"] = 0

    # --- Editor diagnostics ---
    if signals.has_errors:
        breakdown["has_errors"] = 3
    elif signals.has_warnings:
        breakdown["has_warnings"] = 1
    else:
        breakdown["has_errors"] = 0

    # --- Backspace churn ---
    breakdown["backspace_churn"] = 2 if signals.backspace_churn else 0

    # --- Frustration (typing burst → silence) ---
    if signals.frustration_score >= 0.5:
        breakdown["frustration"] = 2
    elif signals.frustration_score >= 0.25:
        breakdown["frustration"] = 1
    else:
        breakdown["frustration"] = 0

    # --- Head stillness ---
    if signals.head_available:
        if signals.head_still:
            breakdown["head_still"] = 2
        else:
            # Head is moving — student is likely reading/thinking, not stuck
            breakdown["head_moving"] = -2
    # If camera not available, neither bonus nor penalty

    total = sum(breakdown.values())
    # Manual and follow-up triggers always fire regardless of score
    fired = total >= FIRE_THRESHOLD or signals.trigger in ("manual", "follow_up")

    return StuckScore(
        score=total,
        fired=fired,
        threshold=FIRE_THRESHOLD,
        breakdown=breakdown,
    )


def signals_from_request(
    trigger: str,
    vscode_idle_ms: int,
    has_errors: bool,
    has_warnings: bool,
    backspace_churn: bool,
    os_idle_ms: int,
    frustration_score: float,
    head_available: bool,
    head_still: bool,
    head_movement: float,
) -> StuckSignals:
    return StuckSignals(
        trigger=trigger,
        vscode_idle_ms=vscode_idle_ms,
        has_errors=has_errors,
        has_warnings=has_warnings,
        backspace_churn=backspace_churn,
        os_idle_ms=os_idle_ms,
        frustration_score=frustration_score,
        head_available=head_available,
        head_still=head_still,
        head_movement=head_movement,
    )
