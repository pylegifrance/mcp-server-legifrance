import server


def test_get_legifrance_client_builds_from_env(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    client = server.get_legifrance_client()
    assert client.api_url  # built successfully, no proxy env vars needed


def test_get_legifrance_client_is_cached(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    first = server.get_legifrance_client()
    second = server.get_legifrance_client()
    assert first is second


def test_get_judilibre_client_is_cached(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("JUDILIBRE_KEY_ID", "key-id")
    first = server.get_judilibre_client()
    second = server.get_judilibre_client()
    assert first is second
