from unittest.mock import MagicMock, patch

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


@pytest.mark.asyncio
async def test_returns_formatted_articles_on_success(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    article = MagicMock(
        code_name="Code civil",
        number="1240",
        title="De la responsabilité",
        legal_status="VIGUEUR",
        url="https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006438834",
        content="Tout fait quelconque de l'homme...",
    )
    with patch("server.Code") as mock_code_cls:
        (
            mock_code_cls.return_value.search.return_value.in_code.return_value
            .with_formatter.return_value.text.return_value.execute.return_value
        ) = [article]
        result = await call_rechercher_code(
            {"search": "responsabilité", "code_name": "Code civil", "champ": "ARTICLE"}
        )
    assert "1240" in result[0].text
    assert "responsabilité" in result[0].text.lower()


@pytest.mark.asyncio
async def test_proximite_is_forwarded_to_text_builder(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    with patch("server.Code") as mock_code_cls:
        builder = mock_code_cls.return_value.search.return_value.in_code.return_value.with_formatter.return_value
        builder.text.return_value.execute.return_value = []
        await call_rechercher_code(
            {"search": "bail commercial", "code_name": "Code civil", "proximite": 3}
        )
    assert builder.text.call_args.kwargs["proximity"] == 3


@pytest.mark.asyncio
async def test_num_article_champ_uses_article_number_builder(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    with patch("server.Code") as mock_code_cls:
        builder = mock_code_cls.return_value.search.return_value.in_code.return_value.with_formatter.return_value
        builder.article_number.return_value.execute.return_value = []
        await call_rechercher_code(
            {"search": "1240", "code_name": "Code civil", "champ": "NUM_ARTICLE"}
        )
    builder.article_number.assert_called_once_with("1240")
