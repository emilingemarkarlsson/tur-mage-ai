"""
Standalone runner för shl_transform pipeline.
Kör de 4 transformer-blocken i sekvens mot MotherDuck.

Kräver: MOTHERDUCK_TOKEN i env eller .env-fil
Kör:    python3 scripts/run_shl_pipeline.py
"""
from __future__ import annotations

import os
import sys
import time
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# Mage-mock
# ---------------------------------------------------------------------------
_mage = types.ModuleType("mage_ai")
_mage.settings = types.ModuleType("mage_ai.settings")
_mage.settings.repo = types.ModuleType("mage_ai.settings.repo")
_mage.settings.repo.get_repo_path = lambda: str(
    Path(__file__).resolve().parent.parent / "mage_project"
)
_mage.data_preparation = types.ModuleType("mage_ai.data_preparation")
_mage.data_preparation.decorators = types.ModuleType("mage_ai.data_preparation.decorators")
_mage.data_preparation.decorators.transformer = lambda f: f
_mage.data_preparation.decorators.data_loader = lambda f: f
_mage.data_preparation.decorators.data_exporter = lambda f: f
sys.modules.update({
    "mage_ai": _mage,
    "mage_ai.settings": _mage.settings,
    "mage_ai.settings.repo": _mage.settings.repo,
    "mage_ai.data_preparation": _mage.data_preparation,
    "mage_ai.data_preparation.decorators": _mage.data_preparation.decorators,
})

# ---------------------------------------------------------------------------
# Paths & env
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "mage_project"))


def _load_env():
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
STEPS = [
    ("shl_fact_player_game", "transformers.shl_fact_player_game", "shl_fact_player_game"),
    ("shl_fact_goalie_game", "transformers.shl_fact_goalie_game", "shl_fact_goalie_game"),
    ("shl_fact_team_game",   "transformers.shl_fact_team_game",   "shl_fact_team_game"),
    ("shl_dim_standings",    "transformers.shl_dim_standings",    "shl_dim_standings"),
]


def run():
    if not os.environ.get("MOTHERDUCK_TOKEN", "").strip():
        raise SystemExit("[shl runner] MOTHERDUCK_TOKEN saknas – kan inte köra")

    t0 = time.time()
    result = {}

    for step_name, module_path, fn_name in STEPS:
        print(f"\n[shl runner] ── {step_name} ──────────────────────")
        t1 = time.time()
        try:
            import importlib
            mod = importlib.import_module(module_path)
            fn = getattr(mod, fn_name)
            result = fn(result)
        except Exception as exc:
            print(f"[shl runner] KRITISKT FEL i {step_name}: {exc}")
            raise

        print(f"[shl runner] {step_name} klar ({round(time.time()-t1,1)}s)")

    print(f"\n[shl runner] Pipeline klar på {round(time.time()-t0,1)}s. "
          f"Resultat: {result}")


if __name__ == "__main__":
    run()
