"""Storage backend abstraction for different persistence strategies.

Defines a Protocol for storage backends and provides implementations
for in-memory and MongoDB storage.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class StorageBackend(Protocol):
    """Protocol for storage backends.
    
    Provides basic CRUD operations on collections of documents.
    Each document is a dict with an 'id' field as primary key.
    """

    async def get(self, collection: str, id: str) -> dict[str, Any] | None:
        """Get a document by ID. Returns None if not found."""
        ...

    async def find(
        self,
        collection: str,
        filter: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Find documents matching filter, optionally sorted and limited."""
        ...

    async def insert(self, collection: str, document: dict[str, Any]) -> None:
        """Insert a new document. Document must have 'id' field."""
        ...

    async def update(
        self, collection: str, id: str, updates: dict[str, Any]
    ) -> None:
        """Update fields of an existing document. Only specified fields are changed."""
        ...

    async def append_to_list(
        self, collection: str, id: str, field: str, item: dict[str, Any]
    ) -> None:
        """Append an item to a list field in a document."""
        ...


class InMemoryBackend:
    """In-memory storage backend using dicts."""

    def __init__(self) -> None:
        # collection -> id -> document
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    async def get(self, collection: str, id: str) -> dict[str, Any] | None:
        return self._data.get(collection, {}).get(id)

    async def find(
        self,
        collection: str,
        filter: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        docs = list(self._data.get(collection, {}).values())

        # Simple filter: exact match on specified fields
        if filter:
            docs = [
                doc
                for doc in docs
                if all(doc.get(k) == v for k, v in filter.items())
            ]

        # Sort: list of (field, direction) where direction is 1 (asc) or -1 (desc)
        if sort:
            for field, direction in reversed(sort):
                docs.sort(key=lambda d: d.get(field, ""), reverse=(direction == -1))

        if limit is not None:
            docs = docs[:limit]

        return docs

    async def insert(self, collection: str, document: dict[str, Any]) -> None:
        if collection not in self._data:
            self._data[collection] = {}
        doc_id = document["id"]
        # Deep copy to prevent external mutations
        self._data[collection][doc_id] = dict(document)

    async def update(
        self, collection: str, id: str, updates: dict[str, Any]
    ) -> None:
        doc = self._data.get(collection, {}).get(id)
        if doc is None:
            return
        doc.update(updates)

    async def append_to_list(
        self, collection: str, id: str, field: str, item: dict[str, Any]
    ) -> None:
        doc = self._data.get(collection, {}).get(id)
        if doc is None:
            return
        if field not in doc:
            doc[field] = []
        doc[field].append(item)


class MongoBackend:
    """MongoDB storage backend."""

    def __init__(self, db) -> None:
        """Initialize with a motor AsyncIOMotorDatabase instance."""
        self._db = db

    async def ensure_indexes(self, collection: str, indexes: list[dict[str, Any]]) -> None:
        """Create indexes for a collection.

        Args:
            collection: Collection name
            indexes: List of index specs, each with 'fields' (str or list) and optional 'unique' (bool)
        """
        coll = self._db[collection]
        for idx in indexes:
            try:
                fields = idx["fields"]
                unique = idx.get("unique", False)
                # create_index is idempotent - if index exists, it's a no-op
                await coll.create_index(fields, unique=unique)
            except Exception as e:
                logger.error(f"Failed to create index on {collection}.{idx['fields']}: {e}")

    async def get(self, collection: str, id: str) -> dict[str, Any] | None:
        try:
            doc = await self._db[collection].find_one({"id": id}, {"_id": 0})
            return doc
        except Exception as e:
            logger.error(f"Failed to get document {id} from {collection}: {e}")
            return None

    async def find(
        self,
        collection: str,
        filter: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        try:
            query = filter or {}
            cursor = self._db[collection].find(query, {"_id": 0})

            if sort:
                cursor = cursor.sort(sort)

            if limit is not None:
                cursor = cursor.limit(limit)

            return await cursor.to_list(None)
        except Exception as e:
            logger.error(f"Failed to find documents in {collection}: {e}")
            return []

    async def insert(self, collection: str, document: dict[str, Any]) -> None:
        try:
            await self._db[collection].insert_one(document)
        except Exception as e:
            logger.error(f"Failed to insert document into {collection}: {e}")
            raise

    async def update(
        self, collection: str, id: str, updates: dict[str, Any]
    ) -> None:
        try:
            await self._db[collection].update_one({"id": id}, {"$set": updates})
        except Exception as e:
            logger.error(f"Failed to update document {id} in {collection}: {e}")
            raise

    async def append_to_list(
        self, collection: str, id: str, field: str, item: dict[str, Any]
    ) -> None:
        try:
            await self._db[collection].update_one(
                {"id": id}, {"$push": {field: item}}
            )
        except Exception as e:
            logger.error(f"Failed to append to list {field} in {collection}.{id}: {e}")
            raise
