"""Storage backend abstraction for different persistence strategies.

Defines a Protocol for storage backends and provides implementations
for in-memory and MongoDB storage.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol

logger = logging.getLogger(__name__)


def _attach_utc(value: Any) -> Any:
    """Tag naive datetimes (as returned by motor/BSON) with UTC.

    Motor decodes BSON dates as naive `datetime` objects in UTC. We
    normalize them here so callers always see tz-aware datetimes,
    matching what `datetime.now(timezone.utc)` produces on writes.
    """
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    if isinstance(value, dict):
        return {k: _attach_utc(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_attach_utc(v) for v in value]
    return value


def _match_filter(doc: dict[str, Any], filter: dict[str, Any]) -> bool:
    """Tiny Mongo-style matcher for InMemoryBackend.

    Supported per-field specs:
      * scalar value -> exact equality
      * `{"$ne": v}` -> not equal (also matches missing fields)
      * `{"$in": [...]}` -> membership
      * `{"$gte": v}` / `{"$lte": v}` -> range (None compares as < anything)
    Mongo accepts the same dialect verbatim, so callers can build one
    filter dict and hand it to either backend.
    """
    for field, spec in filter.items():
        value = doc.get(field)
        if isinstance(spec, dict):
            for op, operand in spec.items():
                if op == "$ne":
                    if value == operand:
                        return False
                elif op == "$in":
                    if value not in operand:
                        return False
                elif op == "$gte":
                    if value is None or value < operand:
                        return False
                elif op == "$lte":
                    if value is None or value > operand:
                        return False
                else:
                    raise ValueError(f"Unsupported filter operator: {op}")
        else:
            if value != spec:
                return False
    return True


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
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        """Find documents matching filter, optionally sorted/paginated."""
        ...

    async def count(
        self,
        collection: str,
        filter: dict[str, Any] | None = None,
    ) -> int:
        """Count documents matching filter."""
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
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        docs = list(self._data.get(collection, {}).values())

        if filter:
            docs = [doc for doc in docs if _match_filter(doc, filter)]

        # Sort: list of (field, direction) where direction is 1 (asc) or -1 (desc)
        if sort:
            for field, direction in reversed(sort):
                # `None` sorts before everything else regardless of direction;
                # the secondary key (`field` itself missing → "") keeps the
                # ordering deterministic across heterogenous docs.
                docs.sort(
                    key=lambda d: (d.get(field) is None, d.get(field, "")),
                    reverse=(direction == -1),
                )

        if offset:
            docs = docs[offset:]
        if limit is not None:
            docs = docs[:limit]

        return docs

    async def count(
        self,
        collection: str,
        filter: dict[str, Any] | None = None,
    ) -> int:
        docs = self._data.get(collection, {}).values()
        if not filter:
            return len(docs)
        return sum(1 for doc in docs if _match_filter(doc, filter))

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
            return _attach_utc(doc) if doc else doc
        except Exception as e:
            logger.error(f"Failed to get document {id} from {collection}: {e}")
            return None

    async def find(
        self,
        collection: str,
        filter: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        try:
            query = filter or {}
            cursor = self._db[collection].find(query, {"_id": 0})

            if sort:
                cursor = cursor.sort(sort)

            if offset:
                cursor = cursor.skip(offset)
            if limit is not None:
                cursor = cursor.limit(limit)

            docs = await cursor.to_list(None)
            return [_attach_utc(d) for d in docs]
        except Exception as e:
            logger.error(f"Failed to find documents in {collection}: {e}")
            return []

    async def count(
        self,
        collection: str,
        filter: dict[str, Any] | None = None,
    ) -> int:
        try:
            return await self._db[collection].count_documents(filter or {})
        except Exception as e:
            logger.error(f"Failed to count documents in {collection}: {e}")
            return 0

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
