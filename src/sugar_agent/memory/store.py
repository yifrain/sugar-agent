"""Unified memory store interface.

Provides a clean API for adding, querying, and managing memories.
Backed by both file storage (markdown) and database index.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger


class MemoryStore:
    """Unified memory management interface.

    Memories are stored as markdown files for human readability,
    with a JSON index for fast retrieval.
    """

    def __init__(self, storage_dir: str, db_session_factory=None):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.storage_dir / "index.json"
        self.db_factory = db_session_factory
        self._index: dict = {"memories": [], "version": 1}
        self._load_index()

    def _load_index(self):
        """Load the memory index from disk."""
        if self.index_path.exists():
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    self._index = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load memory index: {e}")
                self._index = {"memories": [], "version": 1}

        # Also try to rebuild from markdown files
        self._rebuild_index_from_files()

    def _save_index(self):
        """Save the memory index to disk."""
        try:
            with open(self.index_path, "w", encoding="utf-8") as f:
                json.dump(self._index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save memory index: {e}")

    def _rebuild_index_from_files(self):
        """Rebuild index from markdown files (for detecting manual edits)."""
        existing_ids = {m.get("id") for m in self._index["memories"]}
        new_memories = 0

        for md_file in sorted(self.storage_dir.glob("*.md")):
            if md_file.name == "README.md":
                continue
            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    content = f.read()
                # Parse markdown entries
                extracted = self._parse_markdown_file(content, md_file.name)
                for mem in extracted:
                    if mem.get("id") not in existing_ids:
                        self._index["memories"].append(mem)
                        existing_ids.add(mem.get("id"))
                        new_memories += 1
            except Exception as e:
                logger.warning(f"Failed to parse memory file {md_file}: {e}")

        if new_memories > 0:
            logger.info(f"Rebuilt {new_memories} memories from markdown files")
            self._save_index()

    def _parse_markdown_file(self, content: str, filename: str) -> list[dict]:
        """Parse a markdown file into memory entries."""
        memories = []
        lines = content.split("\n")
        current_memory = None

        for line in lines:
            line = line.strip()
            if line.startswith("## "):
                # New memory entry
                if current_memory:
                    memories.append(current_memory)
                title = line[3:].strip()
                # Parse title like "[category] Content"
                category = "fact"
                text = title
                if title.startswith("[") and "]" in title:
                    end_bracket = title.index("]")
                    category = title[1:end_bracket]
                    text = title[end_bracket + 1:].strip()
                current_memory = {
                    "id": f"file_{filename}_{len(memories)}",
                    "content": text,
                    "category": category,
                    "tags": "",
                    "importance": 3,
                    "is_pinned": False,
                    "file": filename,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            elif line.startswith("- Tags:") and current_memory:
                current_memory["tags"] = line.replace("- Tags:", "").strip()
            elif line.startswith("- Importance:") and current_memory:
                try:
                    current_memory["importance"] = int(line.split(":")[-1].strip())
                except ValueError:
                    pass

        if current_memory:
            memories.append(current_memory)

        return memories

    async def add(self, content: str, category: str = "fact", importance: int = 3) -> str:
        """Add a new memory.

        Returns the memory ID.
        """
        memory_id = f"mem_{int(datetime.now().timestamp() * 1000)}"
        now = datetime.now(timezone.utc)

        # Add to index
        memory_entry = {
            "id": memory_id,
            "content": content,
            "category": category,
            "tags": "",
            "importance": importance,
            "is_pinned": False,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        self._index["memories"].append(memory_entry)
        self._save_index()

        # Write to today's markdown file
        today = now.strftime("%Y-%m-%d")
        md_file = self.storage_dir / f"{today}.md"

        entry_text = f"\n## [{category}] {content}\n- Tags: \n- Importance: {importance}\n- Created: {now.strftime('%Y-%m-%d %H:%M')}\n"

        with open(md_file, "a", encoding="utf-8") as f:
            if not md_file.exists() or md_file.stat().st_size == 0:
                f.write(f"# Memories - {today}\n")
            f.write(entry_text)

        # Also store in DB if available
        await self._store_in_db(memory_entry)

        logger.info(f"Memory added: [{category}] {content[:50]}...")
        return memory_id

    async def query(self, query: str, category: Optional[str] = None) -> list[dict]:
        """Search memories by keyword and optional category filter.

        Simple full-text search on content and tags.
        """
        query_lower = query.lower()
        results = []

        for mem in self._index["memories"]:
            # Category filter
            if category and mem.get("category") != category:
                continue

            # Text search
            content = mem.get("content", "").lower()
            tags = mem.get("tags", "").lower()
            if query_lower in content or query_lower in tags:
                results.append(mem)

        # Sort by importance (desc) then recency
        results.sort(key=lambda m: (-m.get("importance", 0), m.get("created_at", "")), reverse=True)
        # Fix: we want higher importance first, then newer first
        results.sort(key=lambda m: (-m.get("importance", 0), m.get("created_at", "")), reverse=False)
        # Actually: sort by importance desc, then created_at desc
        results.sort(key=lambda m: (-m.get("importance", 0)), reverse=False)
        # Simple approach:
        results.sort(key=lambda m: (m.get("importance", 0)), reverse=True)

        # Also query DB if available
        db_results = await self._query_db(query, category)
        for db_mem in db_results:
            if db_mem not in results:
                results.append(db_mem)

        return results[:20]

    async def get_recent(self, limit: int = 10) -> list[dict]:
        """Get recent memories, prioritizing pinned and high-importance."""
        memories = self._index["memories"]

        # Pinned first, then by importance, then by recency
        pinned = [m for m in memories if m.get("is_pinned")]
        unpinned = [m for m in memories if not m.get("is_pinned")]
        unpinned.sort(key=lambda m: m.get("created_at", ""), reverse=True)

        return (pinned + unpinned)[:limit]

    async def update(self, memory_id: str, **updates) -> bool:
        """Update an existing memory."""
        for mem in self._index["memories"]:
            if mem.get("id") == memory_id:
                mem.update(updates)
                mem["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._save_index()
                return True
        return False

    async def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID."""
        for i, mem in enumerate(self._index["memories"]):
            if mem.get("id") == memory_id:
                self._index["memories"].pop(i)
                self._save_index()
                return True
        return False

    async def get_all(self, category: Optional[str] = None) -> list[dict]:
        """Get all memories, optionally filtered by category."""
        if category:
            return [m for m in self._index["memories"] if m.get("category") == category]
        return self._index["memories"]

    async def pin(self, memory_id: str, pinned: bool = True) -> bool:
        """Pin or unpin a memory. Pinned memories are always loaded into context."""
        return await self.update(memory_id, is_pinned=pinned)

    async def _store_in_db(self, memory_entry: dict):
        """Store a memory in the database."""
        if not self.db_factory:
            return
        try:
            from sugar_agent.db.models import Memory

            async with self.db_factory() as session:
                mem = Memory(
                    content=memory_entry["content"],
                    category=memory_entry.get("category"),
                    tags=memory_entry.get("tags"),
                    importance=memory_entry.get("importance", 3),
                    is_pinned=memory_entry.get("is_pinned", False),
                )
                session.add(mem)
                await session.commit()
        except Exception as e:
            logger.debug(f"Failed to store memory in DB: {e}")

    async def _query_db(self, query: str, category: Optional[str] = None) -> list[dict]:
        """Query memories from the database."""
        if not self.db_factory:
            return []
        try:
            from sqlalchemy import select
            from sugar_agent.db.models import Memory

            async with self.db_factory() as session:
                stmt = select(Memory).where(Memory.content.contains(query))
                if category:
                    stmt = stmt.where(Memory.category == category)
                stmt = stmt.limit(20)

                result = await session.execute(stmt)
                rows = result.scalars().all()

                return [
                    {
                        "id": f"db_{row.id}",
                        "content": row.content,
                        "category": row.category,
                        "tags": row.tags or "",
                        "importance": row.importance,
                        "is_pinned": row.is_pinned,
                        "created_at": row.created_at.isoformat() if row.created_at else "",
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.debug(f"Failed to query DB memories: {e}")
            return []
