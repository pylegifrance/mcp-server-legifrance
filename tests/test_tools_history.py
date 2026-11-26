from unittest.mock import patch

import pytest

from server import call_get_text_history


@pytest.mark.asyncio
async def test_unknown_text_id_returns_explicit_message(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    with patch("server.Loda") as mock_loda_cls:
        mock_loda_cls.return_value.fetch.return_value = None
        result = await call_get_text_history({"text_id": "99-999"})
    assert "aucun résultat" in result[0].text.lower()
