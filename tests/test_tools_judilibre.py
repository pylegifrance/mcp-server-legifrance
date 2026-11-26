from unittest.mock import MagicMock, patch

import pytest

import server
from server import call_rechercher_judilibre


@pytest.mark.asyncio
async def test_no_results_returns_explicit_message(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("JUDILIBRE_KEY_ID", "key-id")
    with patch("server.JudilibreAPI") as mock_api_cls:
        mock_api_cls.return_value.search.return_value = []
        result = await call_rechercher_judilibre({"search": "zzzzz"})
    assert "aucun résultat" in result[0].text.lower()


@pytest.mark.asyncio
async def test_missing_key_id_fails_clearly(monkeypatch):
    monkeypatch.delenv("JUDILIBRE_KEY_ID", raising=False)
    result = await call_rechercher_judilibre({"search": "licenciement"})
    assert "judilibre_key_id" in result[0].text.lower()


@pytest.mark.asyncio
async def test_returns_formatted_decisions_on_success(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("JUDILIBRE_KEY_ID", "key-id")
    decision = MagicMock()
    decision.to_markdown.return_value = "## Cour de cassation\n\nRésumé"
    with patch("server.JudilibreAPI") as mock_api_cls:
        mock_api_cls.return_value.search.return_value = [decision]
        result = await call_rechercher_judilibre(
            {
                "search": "licenciement",
                "jurisdiction": ["cc"],
                "chamber": ["soc"],
                "date_start": "2020-01-01",
                "date_end": "2020-12-31",
                "page_size": 500,
            }
        )
    assert "Cour de cassation" in result[0].text


def test_production_env_uses_production_judilibre_url(monkeypatch):
    from pylegifrance.fonds.judilibre import JUDILIBRE_PROD_URL

    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("JUDILIBRE_KEY_ID", "key-id")
    monkeypatch.setenv("PISTE_ENV", "production")

    client = server.get_judilibre_client()

    assert client.api_url == JUDILIBRE_PROD_URL
