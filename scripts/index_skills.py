from __future__ import annotations

import asyncio
from pathlib import Path

from neura_marketplace.config import settings
from neura_marketplace.db import Database
from neura_marketplace.skill_catalog import SkillCatalog


async def main() -> None:
    db = Database(settings.database_path)

    await db.init()

    catalog = SkillCatalog(
        settings.skills_dir
    )

    skills = catalog.scan()

    await db.execute(
        "DELETE FROM skill_files"
    )

    await db.execute(
        "DELETE FROM skill_search"
    )

    await db.execute(
        "DELETE FROM skills"
    )

    skill_rows = []
    search_rows = []
    file_rows = []

    for skill in skills:
        skill_rows.append(
            (
                skill.id,
                skill.source,
                skill.name,
                skill.description,
                skill.version,
                skill.source_path,
                skill.skill_md_path,
                skill.sha256,
                skill.file_count,
            )
        )

        search_rows.append(
            (
                skill.id,
                skill.name,
                skill.description,
                skill.source,
            )
        )

        for file in catalog.list_files(skill.id):
            file_rows.append(
                (
                    skill.id,
                    file["path"],
                    file["size"],
                )
            )

    await db.executemany(
        """
        INSERT INTO skills(
            id,
            source,
            name,
            description,
            version,
            source_path,
            skill_md_path,
            sha256,
            file_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        skill_rows,
    )

    await db.executemany(
        """
        INSERT INTO skill_search(
            skill_id,
            name,
            description,
            source
        )
        VALUES (?, ?, ?, ?)
        """,
        search_rows,
    )

    await db.executemany(
        """
        INSERT INTO skill_files(
            skill_id,
            relative_path,
            size
        )
        VALUES (?, ?, ?)
        """,
        file_rows,
    )

    print(
        f"Indexed {len(skills)} skills "
        f"and {len(file_rows)} skill files "
        f"from {settings.skills_dir}"
    )


if __name__ == "__main__":
    asyncio.run(main())
