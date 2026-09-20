from __future__ import annotations

from .models import AgentListing


BASE_TOOLS = {
    "filesystem.list",
    "filesystem.read",
    "filesystem.write",
    "skill.search",
    "skill.list",
    "skill.list_files",
    "skill.read",
    "skill.invoke",
    "a2a.call",
}

WEB_TOOLS = {'web.search', 'web.fetch'}
SHELL_TOOLS = {'shell.exec'}

WEB_DIVISIONS = {
    'academic', 'design', 'finance', 'healthcare', 'marketing', 'paid-media',
    'product', 'project-management', 'research', 'sales', 'specialized', 'support',
}

SHELL_DIVISIONS = {
    'engineering', 'testing', 'security', 'game-development', 'spatial-computing',
    'gis', 'unity', 'unreal-engine', 'godot', 'roblox-studio', 'blender', 'mcp-memory',
}


def tools_for_agent(agent: AgentListing) -> list[str]:
    tools = set(BASE_TOOLS)
    division = agent.division.lower()
    corpus = f'{agent.id} {agent.name} {agent.description}'.lower()

    tools |= WEB_TOOLS

    if division in SHELL_DIVISIONS or any(k in corpus for k in ('engineer', 'developer', 'tester', 'code', 'devops', 'sre')):
        tools |= SHELL_TOOLS

    if division in {'testing', 'security'}:
        tools |= WEB_TOOLS

    return sorted(tools)
