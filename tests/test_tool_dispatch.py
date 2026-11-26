from unittest.mock import AsyncMock, patch

import pytest

from server import _MAX_PAGE_SIZE, call_list_tools, dispatch_tool_call, rate_limit


@pytest.mark.asyncio
async def test_page_size_schemas_advertise_the_real_clamp():
    """page_size is silently clamped to _MAX_PAGE_SIZE by _clamp_page_size();
    the advertised schema maximum must match, or a caller tuning page_size
    off the schema gets far fewer results than the schema promised."""
    tools = await call_list_tools()
    for tool in tools:
        page_size_schema = tool.inputSchema["properties"].get("page_size")
        if page_size_schema is not None:
            assert page_size_schema["maximum"] == _MAX_PAGE_SIZE, tool.name


@pytest.mark.asyncio
async def test_list_tools_exposes_all_five_tools():
    tools = await call_list_tools()
    names = {t.name for t in tools}
    assert names == {
        "rechercher_dans_texte_legal",
        "rechercher_code",
        "rechercher_jurisprudence_judiciaire",
        "rechercher_jurisprudence_judilibre",
        "get_text_history",
    }


@pytest.mark.asyncio
async def test_dispatch_routes_each_known_tool_name():
    for tool_name, target in [
        ("rechercher_dans_texte_legal", "server.call_rechercher_texte_legal"),
        ("rechercher_code", "server.call_rechercher_code"),
        ("rechercher_jurisprudence_judiciaire", "server.call_rechercher_jurisprudence"),
        ("rechercher_jurisprudence_judilibre", "server.call_rechercher_judilibre"),
        ("get_text_history", "server.call_get_text_history"),
    ]:
        with patch(target, new_callable=AsyncMock) as mock_call:
            mock_call.return_value = ["sentinel"]
            result = await dispatch_tool_call(tool_name, {})
        assert result == ["sentinel"]
        mock_call.assert_awaited_once_with({})


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_error_text():
    result = await dispatch_tool_call("inconnu", {})
    assert "inconnu" in result[0].text.lower()


@pytest.mark.asyncio
async def test_dispatch_catches_exceptions_from_tool_handlers():
    with patch("server.call_rechercher_code", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = RuntimeError("boom")
        result = await dispatch_tool_call("rechercher_code", {})
    assert "boom" in result[0].text


@pytest.mark.asyncio
async def test_rate_limit_throttles_calls_exceeding_the_quota(monkeypatch):
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr("server.asyncio.sleep", fake_sleep)

    calls_made = []

    @rate_limit(calls=2, period=10.0)
    async def limited():
        calls_made.append(1)
        return "ok"

    for _ in range(3):
        await limited()

    assert len(calls_made) == 3
    assert len(sleep_calls) == 1
