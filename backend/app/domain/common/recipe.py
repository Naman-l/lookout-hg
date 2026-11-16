"""Which recipe this deployment runs: `LOOKOUT_RECIPE`, else the one `recipes/DEFAULT` names, else the first recipe under `recipes/` by name.
The customer is the recipe's, never the code's: the default is a line of configuration, not a name written here."""

from __future__ import annotations

import os
from pathlib import Path

RECIPES = Path(__file__).resolve().parents[4] / "recipes"


def recipe_dir() -> Path:
    if os.environ.get("LOOKOUT_RECIPE"):
        return Path(os.environ["LOOKOUT_RECIPE"])
    named = (RECIPES / "DEFAULT").read_text().strip() if (RECIPES / "DEFAULT").exists() else ""
    if named and (RECIPES / named / "answers.yaml").exists():
        return RECIPES / named
    found = sorted(p for p in RECIPES.iterdir() if (p / "answers.yaml").exists()) if RECIPES.exists() else []
    return found[0] if found else RECIPES / "recipe"
