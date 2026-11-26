from unittest.mock import MagicMock, patch

import pytest

from server import _resolve_loda_text, call_get_text_history


@pytest.mark.asyncio
async def test_unknown_text_id_returns_explicit_message(monkeypatch):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    with patch("server.Loda") as mock_loda_cls:
        mock_loda_cls.return_value.fetch.return_value = None
        mock_loda_cls.return_value.search.return_value = []
        result = await call_get_text_history({"text_id": "99-999"})
    assert "aucun résultat" in result[0].text.lower()


@pytest.mark.asyncio
async def test_resolves_law_number_via_search_before_fetching(monkeypatch):
    """"78-17" isn't a LEGITEXT/JORFTEXT id that Loda.fetch() accepts
    directly — it must be resolved via search first, like
    rechercher_dans_texte_legal already does."""
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")

    resolved_texte = MagicMock()
    resolved_texte.format_modifications_report.return_value = "## Loi 78-17\n\nImpact détaillé"
    resolved_texte.versions.return_value = []

    match = MagicMock(id="LEGITEXT000006069095")

    def fake_fetch(text_id):
        if text_id == "LEGITEXT000006069095":
            return resolved_texte
        return None

    with patch("server.Loda") as mock_loda_cls:
        mock_loda_cls.return_value.fetch.side_effect = fake_fetch
        mock_loda_cls.return_value.search.return_value = [match]
        result = await call_get_text_history({"text_id": "78-17"})

    assert "Impact détaillé" in result[0].text


@pytest.mark.asyncio
async def test_includes_version_history_section(monkeypatch):
    """The tool's own description promises version/history over time, not
    just which articles the law touched elsewhere."""
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")

    version = MagicMock()
    version.date_debut.strftime.return_value = "01/01/2020"
    version.date_fin = None
    version.etat = "VIGUEUR"

    texte = MagicMock()
    texte.format_modifications_report.return_value = "Aucun impact disponible."
    texte.to_markdown.return_value = "## Texte\n\ncontenu"
    texte.versions.return_value = [version]

    with patch("server.Loda") as mock_loda_cls:
        mock_loda_cls.return_value.fetch.return_value = texte
        result = await call_get_text_history({"text_id": "78-17"})

    assert "01/01/2020" in result[0].text
    assert "VIGUEUR" in result[0].text


@pytest.mark.asyncio
async def test_versions_failure_does_not_crash_the_tool(monkeypatch):
    """.versions() hits a separate API call that can fail independently
    (observed live: consult/loda/versions can 403 even when the text
    itself fetches fine) -- that must degrade gracefully, not crash the
    whole tool call."""
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")

    texte = MagicMock()
    texte.format_modifications_report.return_value = "Aucun impact disponible."
    texte.to_markdown.return_value = "## Loi 78-17\n\ncontenu"
    texte.versions.side_effect = Exception("API client error 403 - ...")

    with patch("server.Loda") as mock_loda_cls:
        mock_loda_cls.return_value.fetch.return_value = texte
        result = await call_get_text_history({"text_id": "78-17"})

    assert "Loi 78-17" in result[0].text


@pytest.mark.asyncio
async def test_backend_failure_is_reported_distinctly_from_no_results(monkeypatch):
    """A real backend failure (auth, network, 5xx) while resolving text_id
    must surface as an explicit error, not be indistinguishable from
    "Aucun résultat." -- a caller needs to know the lookup failed rather
    than concluding the text has no history."""
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    with patch("server.Loda") as mock_loda_cls:
        mock_loda_cls.return_value.fetch.return_value = None
        mock_loda_cls.return_value.search.side_effect = RuntimeError("503 Service Unavailable")
        result = await call_get_text_history({"text_id": "78-17"})

    assert "aucun résultat" not in result[0].text.lower()
    assert "erreur" in result[0].text.lower()
    assert "503" in result[0].text


def test_resolve_loda_text_propagates_when_search_raises():
    """Only the first fetch(text_id) attempt is allowed to fail silently
    (an expected outcome for non-LEGITEXT inputs like "78-17"). A failure
    of the fallback search itself is a real backend problem (auth,
    network, 5xx) and must not be reported as if the text simply doesn't
    exist."""
    loda = MagicMock()
    loda.fetch.return_value = None
    loda.search.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        _resolve_loda_text(loda, "78-17")


def test_resolve_loda_text_returns_none_when_matched_id_is_none():
    loda = MagicMock()
    loda.fetch.return_value = None
    loda.search.return_value = [MagicMock(id=None)]

    assert _resolve_loda_text(loda, "78-17") is None


def test_resolve_loda_text_propagates_when_second_fetch_raises():
    match = MagicMock(id="LEGITEXT000006069095")

    def fake_fetch(text_id):
        if text_id == "LEGITEXT000006069095":
            raise RuntimeError("boom")
        return None

    loda = MagicMock()
    loda.fetch.side_effect = fake_fetch
    loda.search.return_value = [match]

    with pytest.raises(RuntimeError, match="boom"):
        _resolve_loda_text(loda, "78-17")
