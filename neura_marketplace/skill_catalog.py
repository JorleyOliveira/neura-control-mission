from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillListing:
    id: str
    source: str
    name: str
    description: str
    version: str | None
    source_path: str
    skill_md_path: str
    sha256: str
    file_count: int

    def as_dict(self) -> dict:
        return asdict(self)


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}

    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not match:
        return {}

    out: dict[str, str] = {}

    for line in match.group(1).splitlines():
        if ":" not in line:
            continue

        key, value = line.split(":", 1)

        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key:
            out[key] = value

    return out


class SkillCatalog:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def scan(self) -> list[SkillListing]:
        if not self.root.exists():
            return []

        skills: list[SkillListing] = []

        for skill_md in sorted(self.root.rglob("SKILL.md")):
            skill_root = skill_md.parent.resolve()

            if self.root != skill_root and self.root not in skill_root.parents:
                continue

            skill_id = skill_root.relative_to(self.root).as_posix()

            raw = skill_md.read_text(
                encoding="utf-8",
                errors="replace",
            )

            meta = _frontmatter(raw)

            relative_parts = Path(skill_id).parts

            source = (
                relative_parts[0]
                if len(relative_parts) > 1
                else "local"
            )

            name = (
                meta.get("name")
                or skill_root.name
            )

            description = (
                meta.get("description")
                or ""
            )

            version = meta.get("version")

            files = [
                p
                for p in skill_root.rglob("*")
                if p.is_file()
            ]

            digest = hashlib.sha256(
                raw.encode("utf-8")
            ).hexdigest()

            skills.append(
                SkillListing(
                    id=skill_id,
                    source=source,
                    name=name,
                    description=description,
                    version=version,
                    source_path=str(skill_root),
                    skill_md_path=str(skill_md),
                    sha256=digest,
                    file_count=len(files),
                )
            )

        return skills

    def get(self, skill_id: str) -> SkillListing:
        matches = {
            item.id: item
            for item in self.scan()
        }

        try:
            return matches[skill_id]
        except KeyError:
            raise KeyError(f"Unknown skill: {skill_id}")

    def search(
        self,
        query: str,
        limit: int = 8,
    ) -> list[SkillListing]:
        tokens = {
            token
            for token in re.findall(
                r"[a-z0-9_-]+",
                query.lower(),
            )
            if len(token) > 1
        }

        ranked = []

        for skill in self.scan():
            corpus = (
                f"{skill.id} "
                f"{skill.name} "
                f"{skill.description} "
                f"{skill.source}"
            ).lower()

            score = sum(
                1
                for token in tokens
                if token in corpus
            )

            if score:
                ranked.append((score, skill))

        ranked.sort(
            key=lambda item: (
                -item[0],
                item[1].id,
            )
        )

        return [
            skill
            for _, skill in ranked[:limit]
        ]

    def list_files(
        self,
        skill_id: str,
    ) -> list[dict]:
        listing = self.get(skill_id)
        root = Path(listing.source_path)

        result = []

        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue

            result.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size": path.stat().st_size,
                }
            )

        return result

    def read(
        self,
        skill_id: str,
        relative_path: str = "SKILL.md",
        *,
        offset: int = 0,
        max_chars: int = 20000,
    ) -> dict:
        listing = self.get(skill_id)

        skill_root = Path(
            listing.source_path
        ).resolve()

        target = (
            skill_root / relative_path
        ).resolve()

        if (
            target != skill_root
            and skill_root not in target.parents
        ):
            raise ValueError("Skill path traversal rejected")

        if not target.is_file():
            raise FileNotFoundError(relative_path)

        text = target.read_text(
            encoding="utf-8",
            errors="replace",
        )

        offset = max(offset, 0)
        max_chars = max(
            1,
            min(max_chars, 30000),
        )

        chunk = text[
            offset:offset + max_chars
        ]

        next_offset = (
            offset + len(chunk)
            if offset + len(chunk) < len(text)
            else None
        )

        return {
            "skill_id": skill_id,
            "path": relative_path,
            "content": chunk,
            "offset": offset,
            "next_offset": next_offset,
            "truncated": next_offset is not None,
            "total_chars": len(text),
        }
