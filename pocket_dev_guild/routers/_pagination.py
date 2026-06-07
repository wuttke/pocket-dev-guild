"""Shared helpers for paginated list endpoints.

`parse_sort` translates a query-string sort spec like `"-created_at"` or
`"status,-created_at"` into the `list[tuple[str, int]]` shape the storage
backends consume. Field names are checked against a per-resource allow
list so callers can't sneak in arbitrary projection paths.
"""

from __future__ import annotations

from fastapi import HTTPException

# Cap pagination so a malicious / careless client can't pull the whole
# collection in one request. Default is on the conservative side; bump
# via the route param if a specific endpoint needs more.
MAX_LIMIT = 200
DEFAULT_LIMIT = 50


def parse_sort(
    raw: str | None,
    *,
    allowed: set[str],
    default: list[tuple[str, int]],
) -> list[tuple[str, int]]:
    """Parse a `field,-other` style sort spec.

    Prefix a field with `-` for descending order. Empty / None returns
    `default`. Unknown fields raise HTTP 400.
    """
    if not raw:
        return default
    result: list[tuple[str, int]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("-"):
            field, direction = part[1:], -1
        else:
            field, direction = part, 1
        if field not in allowed:
            raise HTTPException(
                400,
                f"Invalid sort field '{field}'. Allowed: {sorted(allowed)}",
            )
        result.append((field, direction))
    return result or default
