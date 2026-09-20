from __future__ import annotations

import asyncio

from neura_marketplace.config import settings
from neura_marketplace.db import Database
from neura_marketplace.marketplace import AgentMarketplace


async def main() -> None:
    db = Database(settings.database_path)
    marketplace = AgentMarketplace(db, settings.effective_agent_dataset_dir)
    count = await marketplace.index()
    print(f"Indexed {count} agents from {settings.effective_agent_dataset_dir}")


if __name__ == "__main__":
    asyncio.run(main())
