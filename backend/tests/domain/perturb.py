"""The facts of the customer's month, changed: the same recipe and the same code must still work. Shared by the perturbed build test and the Import flow test."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import yaml

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
OLD_NAME, NEW_NAME = "Yunzhan", "Marlowe"
SWAPS = [("yunzhan-rnotor", "marlowe-rnotion"), ("yunzhan-motor", "marlowe-motion"), ("Yunzhan", "Marlowe"), ("YUNZHAN", "MARLOWE"), ("yunzhan", "marlowe")]
FRAUD_AMOUNT = "61,205.50"


def _swap(text: str) -> str:
    for a, b in SWAPS:
        text = text.replace(a, b)
    return text


def perturb(root: Path) -> tuple[Path, Path]:
    """Copy the data and the recipe under `root` and change the facts: a renamed supplier, a different fraud, a sixth buyer, a quote nobody read in. Returns (data, recipe)."""
    data, recipe = root / "data", root / "recipe"
    shutil.copytree(ROOT / "data", data, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "recipes" / "halden", recipe, ignore=shutil.ignore_patterns("__pycache__"))
    # 1. the supplier is renamed everywhere it is written: master, parts, news, the quotes (text and file names), look-alike domain included
    for p in [*data.glob("*.csv"), *(data / "external").glob("*"), *(data / "quotes").glob("*")]:
        if p.is_file() and p.suffix in (".csv", ".json", ".md", ".eml", ".txt"):
            p.write_text(_swap(p.read_text(encoding="utf-8")), encoding="utf-8")
        if p.is_file() and OLD_NAME in p.name:
            p.rename(p.with_name(_swap(p.name)))
    # 2. the fraud mail asks for a different amount
    fraud = next((data / "quotes").glob("*URGENT*"))
    fraud.write_text(fraud.read_text(encoding="utf-8").replace("187,420.00", FRAUD_AMOUNT), encoding="utf-8")
    # 2b. a quote that arrived after the export was read: nobody has turned it into a record
    old = next((data / "quotes").glob("2026-09-21_Quotation_QV-Q-2609-17*"))
    (data / "quotes" / "2026-09-20_Quotation_NEW-QUOTE-1_connector_pricing.eml").write_text(
        old.read_text(encoding="utf-8").replace("Subject:", "Subject: NEW-QUOTE-1 ", 1), encoding="utf-8")
    # 3. a sixth buyer: the sensors desk is his, and he signs a few orders
    answers = yaml.safe_load((recipe / "answers.yaml").read_text())
    answers["buyers"].append({"id": "Ravi", "name": "Ravi Okafor", "initials": "RO"})
    answers["company"] = "Ashgrove Robotics"      # another company's files: every sentence that says the company must say this one
    for cat, who in answers["category_buyer"].items():
        if cat == "Sensors":
            answers["category_buyer"][cat] = "Ravi"
    (recipe / "answers.yaml").write_text(yaml.safe_dump(answers, sort_keys=False))
    with open(data / "parts.csv", newline="", encoding="utf-8") as f:
        sensors = {r["part_number"].replace("-", "") for r in csv.DictReader(f) if r["category"] == "Sensors"} | {r["part_number"] for r in csv.DictReader(open(data / "parts.csv", newline="", encoding="utf-8")) if r["category"] == "Sensors"}
    rows = list(csv.DictReader(open(data / "purchase_orders.csv", newline="", encoding="utf-8")))
    for r in rows:
        if r["part_number"] in sensors:
            r["buyer"] = "RO"
    with open(data / "purchase_orders.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return data, recipe
