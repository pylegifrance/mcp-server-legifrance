import server


def test_get_legifrance_client_builds_from_env(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    client = server.get_legifrance_client()
    assert client.api_url  # built successfully, no proxy env vars needed
