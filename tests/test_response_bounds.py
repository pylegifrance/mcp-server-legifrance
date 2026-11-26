from unittest.mock import MagicMock, patch

import pytest

from server import (
    _MAX_CHARS_PER_RESULT,
    _MAX_PAGE_SIZE,
    _MAX_RESULTS_PER_RESPONSE,
    _format_results,
    call_rechercher_code,
    call_rechercher_jurisprudence,
)


def test_format_results_truncates_long_text():
    long_text = "x" * (_MAX_CHARS_PER_RESULT + 500)
    output = _format_results([object()], lambda _: long_text)
    assert len(output) < len(long_text)
    assert "tronqué" in output


def test_format_results_caps_count():
    results = list(range(_MAX_RESULTS_PER_RESPONSE + 5))
    output = _format_results(results, lambda n: f"item-{n}")
    assert output.count("item-") == _MAX_RESULTS_PER_RESPONSE
    assert "5 résultat" in output


@pytest.mark.asyncio
async def test_rechercher_code_clamps_oversized_page_size(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")

    with patch("server.Code") as mock_code_cls:
        builder = (
            mock_code_cls.return_value.search.return_value.in_code.return_value
            .with_formatter.return_value.text.return_value
        )
        builder.paginate.return_value.execute.return_value = []
        await call_rechercher_code(
            {"search": "x", "code_name": "Code civil", "fetch_all": True}
        )

    builder.paginate.assert_called_once_with(page_size=_MAX_PAGE_SIZE)


@pytest.mark.asyncio
async def test_rechercher_jurisprudence_fetch_all_uses_max_page_size(monkeypatch):
    """pylegifrance's JuriSearchRequest.fetch_all field is never read by
    JuriAPI.search() -- forwarding it is a no-op. fetch_all must instead
    request the largest single page, like rechercher_code already does."""
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")

    with patch("server.JuriAPI") as mock_juri_cls:
        mock_juri_cls.return_value.search.return_value = []
        await call_rechercher_jurisprudence({"search": "x", "fetch_all": True})

    query = mock_juri_cls.return_value.search.call_args.args[0]
    assert query.page_size == _MAX_PAGE_SIZE
