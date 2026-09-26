"""Shared test fixtures. Uses a cross-worker filelock to serialize destructive DB tests
(e.g. the CSV `replace_existing` import) with any test that reads global transactions state."""
import pytest

try:
    from filelock import FileLock
except ImportError:  # pragma: no cover - filelock ships with tox/pytest usually
    FileLock = None

LOCK_PATH = "/tmp/rudaya_transactions_db.lock"


@pytest.fixture
def txn_state_lock():
    if FileLock is None:
        yield
        return
    with FileLock(LOCK_PATH):
        yield
