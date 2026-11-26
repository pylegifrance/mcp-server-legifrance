import pytest
from mcp.types import GetPromptResult, TextContent

from server import call_get_prompt, call_list_prompts


@pytest.mark.asyncio
async def test_list_prompts_includes_agent_juridique_expert():
    prompts = await call_list_prompts()
    assert any(p.name == "agent_juridique_expert" for p in prompts)


@pytest.mark.asyncio
async def test_get_prompt_builds_valid_messages_with_single_content_each():
    result = await call_get_prompt("agent_juridique_expert", {"question": "Qu'est-ce que le PACS ?"})

    assert isinstance(result, GetPromptResult)
    assert len(result.messages) == 2
    for message in result.messages:
        assert isinstance(message.content, TextContent)

    user_content = result.messages[1].content
    assert isinstance(user_content, TextContent)
    assert "Qu'est-ce que le PACS ?" in user_content.text


@pytest.mark.asyncio
async def test_get_prompt_unknown_name_raises():
    with pytest.raises(ValueError, match="Prompt inconnu"):
        await call_get_prompt("inconnu", None)
