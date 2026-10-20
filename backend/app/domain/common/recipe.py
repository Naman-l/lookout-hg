"""Which recipe this deployment runs: `LOOKOUT_RECIPE`, else the one recipe under `recipes/` (the first, by name, if several). The customer is the recipe's, never the code's."""

from __future__ import annotations

import os
from pathlib import Path

RECIPES = Path(__file__).resolve().parents[4] / "recipes"


def recipe_dir() -> Path:
    if os.environ.get("LOOKOUT_RECIPE"):
        return Path(os.environ["LOOKOUT_RECIPE"])
    found = sorted(p for p in RECIPES.iterdir() if (p / "answers.yaml").exists()) if RECIPES.exists() else []
    return found[0] if found else RECIPES / "recipe"
