from pathlib import Path

import pytest

from neura_marketplace.db import Database
from neura_marketplace.marketplace import AgentMarketplace


@pytest.mark.asyncio
async def test_index_search_and_exact_raw_prompt(tmp_path: Path):
    agents = tmp_path / "agents"
    agents.mkdir()
    raw = "---\nname: Researcher\ndescription: market research competitor analysis\n---\nSYSTEM BODY"
    (agents / "research.md").write_text(raw, encoding="utf-8")
    (agents / "qa.md").write_text("---\nname: QA\ndescription: verifier audit quality assurance\n---\nQA BODY", encoding="utf-8")
    (agents / "README.md").write_text("# Documentation only", encoding="utf-8")

    db = Database(tmp_path / "test.db")
    marketplace = AgentMarketplace(db, agents)
    assert await marketplace.index() == 2
    hits = await marketplace.search("market research competitor", limit=2)
    assert hits[0].name == "Researcher"
    assert await marketplace.raw_system_prompt(hits[0].id) == raw
