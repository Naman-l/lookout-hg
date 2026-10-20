"""The system on data it never saw (evals/perturbed.py): four checks over one build of the changed files."""
import pytest

from evals import perturbed
from evals.run import ROOT

pytestmark = pytest.mark.skipif(not (ROOT / "data").exists(), reason="no data")


@pytest.fixture(scope="module")
def checks():
    return {c["name"]: c for c in perturbed.run()}


def test_the_build_the_fire_the_fraud_and_the_tariff_hold_on_changed_data(checks):
    for name in ("the build passes on changed data", "the fire is found under the new name", "the fraud is held, the imitation named correctly",
                 "the app and the oracle agree on the three tariff amounts per part, on the changed data"):
        assert checks[name]["ok"], checks[name]


def test_nothing_of_the_old_month_leaks_into_what_the_app_says(checks):
    assert checks["nothing of the old month leaks into what the app says"]["ok"]
