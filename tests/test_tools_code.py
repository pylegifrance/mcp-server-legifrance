from unittest.mock import patch

import pytest

from server import call_rechercher_code


@pytest.mark.asyncio
async def test_unknown_code_name_returns_clear_error():
    result = await call_rechercher_code({"search": "contrat", "code_name": "Pas un code"})
    assert "code" in result[0].text.lower()
    assert "Pas un code" in result[0].text


@pytest.mark.asyncio
async def test_no_results_returns_explicit_message(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    with patch("server.Code") as mock_code_cls:
        (
            mock_code_cls.return_value.search.return_value.in_code.return_value
            .with_formatter.return_value.text.return_value.execute.return_value
        ) = []
        result = await call_rechercher_code({"search": "zzzzz", "code_name": "Code civil"})
    assert "aucun résultat" in result[0].text.lower()
