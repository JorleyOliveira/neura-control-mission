from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .db import Database
from .models import AgentListing


TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9_\-]+")
META_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")


def parse_markdown_agent(raw: str) -> tuple[dict[str, str], str]:
    """Parse the small YAML-like frontmatter subset needed for marketplace discovery.

    Agent execution never uses the parsed body; it always uses the original raw file unchanged.
    """
    if not raw.startswith("---"):
        return {}, raw
    lines = raw.splitlines()
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return {}, raw

    meta: dict[str, str] = {}
    current_key: str | None = None
    block: list[str] = []
    for line in lines[1:end]:
        match = META_RE.match(line)
        if match:
            if current_key and block:
                meta[current_key] = " ".join(block).strip()
                block = []
            key, value = match.groups()
            value = value.strip().strip('"\'')
            if value in {">", "|"}:
                current_key = key
                continue
            meta[key] = value
            current_key = None
        elif current_key and line.strip():
            block.append(line.strip())
    if current_key and block:
        meta[current_key] = " ".join(block).strip()
    body = "\n".join(lines[end + 1 :])
    return meta, body


class AgentMarketplace:
    def __init__(self, db: Database, dataset_dir: Path):
        self.db = db
        self.dataset_dir = dataset_dir.resolve()

    async def index(self) -> int:
        await self.db.init()
        files = sorted(self.dataset_dir.rglob("*.md"))
        if not files:
            raise RuntimeError(f"No .md agent files found under {self.dataset_dir}")

        statements: list[tuple[str, tuple]] = [
            ("DELETE FROM agent_search", ()),
            ("DELETE FROM agents", ()),
        ]
        count = 0
        for path in files:
            raw = path.read_text(encoding="utf-8")
            metadata, body = parse_markdown_agent(raw)
            # agency-agents defines agent files by frontmatter containing at least
            # name + description. Skip README/CONTRIBUTING/docs Markdown.
            if not metadata.get("name") or not metadata.get("description"):
                continue
            rel = path.relative_to(self.dataset_dir).as_posix()
            agent_id = rel.removesuffix(".md").replace("/", ":")
            name = str(metadata.get("name") or path.stem.replace("-", " ").replace("_", " ").title())
            division = str(metadata.get("division") or (path.parent.name if path.parent != self.dataset_dir else "general"))
            description = str(metadata.get("description") or self._derive_description(body))
            vibe = metadata.get("vibe")
            sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            statements.append((
                "INSERT INTO agents(id, name, division, description, vibe, source_path, sha256) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (agent_id, name, division, description, vibe, str(path.resolve()), sha),
            ))
            statements.append((
                "INSERT INTO agent_search(agent_id, name, division, description, vibe) VALUES (?, ?, ?, ?, ?)",
                (agent_id, name, division, description, vibe or ""),
            ))
            count += 1
        await self.db.transaction(statements)
        return count

    @staticmethod
    def _derive_description(content: str) -> str:
        lines = [line.strip(" #-\t") for line in content.splitlines() if line.strip()]
        return " ".join(lines[:5])[:1200]

    async def search(self, query: str, limit: int = 5, exclude: set[str] | None = None) -> list[AgentListing]:
        exclude = exclude or set()
        tokens = TOKEN_RE.findall(query.lower())
        match = " OR ".join(f'"{token}"' for token in tokens[:20])

        rows = []
        if match:
            rows = await self.db.fetchall(
                """
                SELECT a.* FROM agent_search s
                JOIN agents a ON a.id=s.agent_id
                WHERE agent_search MATCH ?
                ORDER BY bm25(agent_search)
                LIMIT ?
                """,
                (match, max(limit * 3, limit)),
            )

        if len(rows) < limit:
            # Token-wise fallback handles catalogs whose metadata does not share the exact query phrase.
            fallback_rows = []
            for token in tokens[:8]:
                like = f"%{token}%"
                fallback_rows.extend(await self.db.fetchall(
                    """
                    SELECT * FROM agents
                    WHERE name LIKE ? OR division LIKE ? OR description LIKE ? OR COALESCE(vibe,'') LIKE ?
                    LIMIT ?
                    """,
                    (like, like, like, like, max(limit * 3, limit)),
                ))
            seen = {row["id"] for row in rows}
            rows.extend(row for row in fallback_rows if row["id"] not in seen)

        results = []
        seen_ids = set()
        for row in rows:
            if row["id"] in exclude or row["id"] in seen_ids:
                continue
            seen_ids.add(row["id"])
            results.append(AgentListing(**dict(row)))
            if len(results) >= limit:
                break
        return results

    async def get(self, agent_id: str) -> AgentListing:
        row = await self.db.fetchone("SELECT * FROM agents WHERE id=?", (agent_id,))
        if not row:
            raise KeyError(f"Unknown agent: {agent_id}")
        return AgentListing(**dict(row))

    async def raw_system_prompt(self, agent_id: str) -> str:
        listing = await self.get(agent_id)
        path = Path(listing.source_path).resolve()
        if self.dataset_dir not in path.parents and path != self.dataset_dir:
            raise RuntimeError("Agent source path escaped configured dataset directory")
        raw = path.read_text(encoding="utf-8")
        actual_sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if actual_sha != listing.sha256:
            raise RuntimeError(f"Agent definition changed after indexing: {agent_id}. Re-index before execution.")
        return raw
