from unittest.mock import MagicMock, patch

import pytest

from server import call_rechercher_texte_legal


@pytest.mark.asyncio
async def test_no_results_returns_explicit_message(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    with patch("server.Loda") as mock_loda_cls:
        mock_loda_cls.return_value.search.return_value = []
        result = await call_rechercher_texte_legal({"search": "zzzzz"})
    assert "aucun résultat" in result[0].text.lower()


@pytest.mark.asyncio
async def test_returns_formatted_texts_on_success(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    texte = MagicMock()
    texte.to_markdown.return_value = "## Loi 78-17\n\ncontenu"
    with patch("server.Loda") as mock_loda_cls:
        mock_loda_cls.return_value.search.return_value = [texte]
        result = await call_rechercher_texte_legal(
            {"search": "informatique", "type_recherche": "EXPRESSION_EXACTE", "page_size": 500}
        )
    assert "Loi 78-17" in result[0].text


@pytest.mark.asyncio
async def test_normalizes_type_recherche_before_building_query(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    with patch("server.Loda") as mock_loda_cls:
        mock_loda_cls.return_value.search.return_value = []
        await call_rechercher_texte_legal({"search": "x", "type_recherche": "EXPRESSION_EXACTE"})

    query = mock_loda_cls.return_value.search.call_args.args[0]
    assert query.type_recherche.value == "EXACTE"
