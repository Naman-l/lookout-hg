"""Every skipped test file is listed with its reason in tests/conftest.py, and every listed file exists: nothing is skipped silently. Since Phase 4 nothing is skipped."""

from tests.conftest import HERE, SKIPPED


def test_every_skipped_file_exists_and_nothing_is_skipped():
    assert [k for k in SKIPPED if not (HERE / k).exists()] == []
    assert SKIPPED == {}
    assert not (HERE / "organism").exists(), "the Halden-era organism tests were replaced by tests/hg"
