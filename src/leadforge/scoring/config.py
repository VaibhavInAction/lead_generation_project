"""Tunable knobs for intent-lead scoring (README §14, §16).

Everything the scorer weighs lives here, not baked into the algorithms — so an
agency can retune the half-life or the freshness/need/quality balance without a
code change. Defaults are grounded in the noisy production data we've seen: a
"need editor" post is dead in a week (~4-day half-life), and a job/hiring post
must sink to the bottom (it is noise for an agency hunting *clients*, not staff).

Load order: hardcoded defaults → overrides from ``scoring.yaml`` (if present).
A missing file is not an error — the defaults score correctly out of the box.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ScoringConfig:
    """Weights and thresholds for the scoring signals (README §16)."""

    # --- Freshness (README §14: configurable half-life, default ~4 days) ---
    freshness_half_life_days: float = 4.0
    # posted_at missing → fall back to first_seen, but discount it: we don't
    # actually know when they posted, so the freshness is less trustworthy.
    freshness_fallback_penalty: float = 0.6

    # --- Component weights (need not sum to 1; normalized at combine time) ---
    weight_freshness: float = 0.4
    weight_need_match: float = 0.4
    weight_data_quality: float = 0.2

    # --- Need-match thresholds (0–100 fit strength) ---
    need_full_phrase: float = 70.0  # the whole need phrase appears verbatim
    need_all_tokens: float = 50.0  # every need word present, not adjacent
    need_partial_cap: float = 40.0  # scaled by fraction of need words present
    need_topic_floor: float = 10.0  # need not really present
    need_solicitation_bonus: float = 30.0  # "looking for a <need>" etc.

    # --- Hard rule: a job/hiring post is not a client lead ---
    # A post classified job_posting has its lead_score capped here, near 0, no
    # matter how fresh or on-topic — it is the wrong kind of post for us.
    job_posting_score_cap: float = 0.0

    def normalized_weights(self) -> tuple[float, float, float]:
        """The three component weights scaled to sum to 1 (equal split if all zero)."""
        raw = (self.weight_freshness, self.weight_need_match, self.weight_data_quality)
        total = sum(raw)
        if total <= 0:
            return (1 / 3, 1 / 3, 1 / 3)
        return tuple(w / total for w in raw)  # type: ignore[return-value]


def load_scoring_config(path: str | Path | None) -> ScoringConfig:
    """Build a :class:`ScoringConfig`, overlaying ``scoring.yaml`` on the defaults.

    A missing file yields the defaults (scoring must work with zero config). A
    present file may override any subset of fields under a top-level ``scoring:``
    key (or at the document root). Unknown keys are ignored; bad types raise
    ``ValueError`` rather than silently scoring on garbage.
    """
    if path is None:
        return ScoringConfig()
    file_path = Path(path)
    if not file_path.is_file():
        return ScoringConfig()

    data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    overrides = data.get("scoring", data)
    if overrides is None:  # an empty/commented-out `scoring:` block → just use defaults
        return ScoringConfig()
    if not isinstance(overrides, dict):
        raise ValueError(f"{path}: 'scoring' must be a mapping")

    known = {f.name for f in fields(ScoringConfig)}
    kwargs: dict[str, float] = {}
    for key, value in overrides.items():
        if key not in known:
            continue  # forward-compatible: ignore keys this version doesn't know
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{path}: '{key}' must be a number, got {value!r}")
        kwargs[key] = float(value)
    return ScoringConfig(**kwargs)
