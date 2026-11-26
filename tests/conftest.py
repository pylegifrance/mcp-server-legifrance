import pytest

import server


@pytest.fixture(autouse=True)
def _reset_cached_clients():
    """Module-level client caches (added for token reuse) must not leak
    between tests that monkeypatch different env vars."""
    server._legifrance_client = None
    server._judilibre_client = None
    yield
    server._legifrance_client = None
    server._judilibre_client = None
