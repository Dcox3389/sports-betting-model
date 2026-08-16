"""
Shared configuration for the cross-sport prediction screen.

Change the three dates below and rerun `python run_all.py` to rebuild
everything for a different period.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "out")
for d in (DATA, OUT):
    os.makedirs(d, exist_ok=True)

# History used to warm up ratings. Nothing before EVAL_START is ever scored.
HISTORY_START = "2024-12-01"

# The window that gets graded.
EVAL_START = "2025-06-01"
EVAL_END   = "2026-08-03"

# ---------------------------------------------------------------- team sports
# league key -> (espn path, [(fetch_start, fetch_end), ...])
ESPN_TEAM = {
    "nba":  ("basketball/nba",  [("20241020", "20250625"), ("20251020", "20260803")]),
    "nhl":  ("hockey/nhl",      [("20241005", "20250625"), ("20251005", "20260803")]),
    "wnba": ("basketball/wnba", [("20250501", "20251020"), ("20260501", "20260803")]),
}

# NOTE: paths must include the "soccer/" segment, exactly like ESPN_TEAM
# entries include "basketball/" or "hockey/". Omitting it 404s every request
# and looks identical to "this league has no data".
ESPN_SOCCER = {
    "mls":    ("soccer/usa.1",      [("20250215", "20251115"), ("20260215", "20260803")]),
    "nwsl":   ("soccer/usa.nwsl",   [("20250301", "20251115"), ("20260301", "20260803")]),
    "wcup":   ("soccer/fifa.world", [("20260601", "20260720")]),
    "epl":    ("soccer/eng.1",      [("20240801", "20250601"), ("20250801", "20260803")]),
    "laliga": ("soccer/esp.1",      [("20240801", "20250601"), ("20250801", "20260803")]),
    "seriea": ("soccer/ita.1",      [("20240801", "20250601"), ("20250801", "20260803")]),
    "bundes": ("soccer/ger.1",      [("20240801", "20250601"), ("20250801", "20260803")]),
    "ligue1": ("soccer/fra.1",      [("20240801", "20250601"), ("20250801", "20260803")]),
    "ucl":    ("soccer/uefa.champions", [("20240901", "20250601"), ("20250901", "20260803")]),
    "uclq":   ("soccer/uefa.champions_qual", [("20250601", "20250901"), ("20260601", "20260803")]),
    "mexico": ("soccer/mex.1",      [("20250101", "20251201"), ("20260101", "20260803")]),
    "brazil": ("soccer/bra.1",      [("20250101", "20251215"), ("20260101", "20260803")]),
    "argent": ("soccer/arg.1",      [("20250101", "20251215"), ("20260101", "20260803")]),
    "norway": ("soccer/nor.1",      [("20250301", "20251201"), ("20260301", "20260803")]),
    "sweden": ("soccer/swe.1",      [("20250301", "20251201"), ("20260301", "20260803")]),
    "japan":  ("soccer/jpn.1",      [("20250201", "20251215"), ("20260201", "20260803")]),
}

SOCCER_KEYS = set(ESPN_SOCCER)

# MLB seasons to pull from statsapi (its own API, richer than ESPN).
MLB_SEASONS = [("2025-03-01", "2025-11-05"), ("2026-03-01", "2026-08-03")]

# ------------------------------------------------------------------- ratings
# league -> (K, home-field advantage in Elo points, min prior events to grade)
ELO = {
    "mlb":  (4.0,  24.0, 20),
    "nba":  (20.0, 100.0, 20),
    "nhl":  (6.0,  50.0, 20),
    "wnba": (20.0, 100.0, 10),
    "tennis_m": (0.0, 0.0, 10),   # K is dynamic, see screen.py
    "tennis_w": (0.0, 0.0, 10),
}
for _k in ESPN_SOCCER:
    ELO.setdefault(_k, (20.0, 65.0, 10))
ELO["wcup"] = (30.0, 65.0, 3)
ELO["uclq"] = (25.0, 65.0, 3)
ELO["ucl"] = (25.0, 65.0, 5)

# Confidence thresholds reported by the screen.
THRESHOLDS = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.825, 0.85, 0.875, 0.90, 0.95)
