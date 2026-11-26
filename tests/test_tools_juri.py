from unittest.mock import MagicMock, patch

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


@pytest.mark.asyncio
async def test_returns_formatted_decisions_on_success(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    decision = MagicMock()
    decision.to_markdown.return_value = "## Cour de cassation\n\nRésumé"
    with patch("server.JuriAPI") as mock_juri_cls:
        mock_juri_cls.return_value.search.return_value = [decision]
        result = await call_rechercher_jurisprudence(
            {
                "search": "licenciement",
                "type_recherche": "AU_MOINS_UN_MOT",
                "page_size": 500,
                "champ": "ALL",
                "sort": "DATE_DESC",
                "publication_bulletin": ["T"],
                "fetch_all": True,
                "juri_keys": ["titre"],
                "juridiction_judiciaire": ["Cour de cassation"],
            }
        )
    assert "Cour de cassation" in result[0].text


@pytest.mark.asyncio
async def test_normalizes_search_type_before_building_query(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    with patch("server.JuriAPI") as mock_juri_cls:
        mock_juri_cls.return_value.search.return_value = []
        await call_rechercher_jurisprudence({"search": "x", "type_recherche": "AU_MOINS_UN_MOT"})

    query = mock_juri_cls.return_value.search.call_args.args[0]
    assert query.search_type.value == "UN_DES_MOTS"
