from neura_marketplace.capabilities import tools_for_agent
from neura_marketplace.models import AgentListing


def agent(agent_id: str, division: str, description: str = '') -> AgentListing:
    return AgentListing(
        id=agent_id,
        name=agent_id,
        division=division,
        description=description,
        source_path='/tmp/x',
        sha256='x',
    )


def test_research_gets_web_not_shell():
    tools = tools_for_agent(agent('research:x', 'research'))
    assert 'web.search' in tools
    assert 'web.fetch' in tools
    assert 'shell.exec' not in tools


def test_engineering_gets_shell():
    tools = tools_for_agent(agent('engineering:x', 'engineering'))
    assert 'shell.exec' in tools
