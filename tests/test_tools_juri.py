from unittest.mock import patch

import pytest

from server import call_rechercher_jurisprudence


@pytest.mark.asyncio
async def test_no_results_returns_explicit_message(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    with patch("server.JuriAPI") as mock_juri_cls:
        mock_juri_cls.return_value.search.return_value = []
        result = await call_rechercher_jurisprudence({"search": "zzzzz"})
    assert "aucun résultat" in result[0].text.lower()
