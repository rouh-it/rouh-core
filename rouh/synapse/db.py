"""Plain SQL over the `synapse` schema (migration 0062).

Synapse's tables are searched with full-text vectors, half-precision vectors and
reciprocal rank fusion, which read best as the SQL they are; so it is written as
SQL here, over Django's own connection, and every function is synchronous, to
be called on a thread (`asyncio.to_thread`) from async code.

Every query names its dataset, and every function that reads a dataset is handed
one that `datasets.mine` has already checked belongs to the person asking.
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal

from django.db import connection, transaction


def _value(v):
    if isinstance(v, (dict, list)) and not isinstance(v, Json):
        return v
    return v


class Json:
    """A value to be sent as jsonb."""

    def __init__(self, value):
        self.value = value


def _params(params):
    out = []
    for p in params or ():
        if isinstance(p, Json):
            out.append(json.dumps(p.value, ensure_ascii=False, default=str))
        elif isinstance(p, uuid.UUID):
            out.append(str(p))
        else:
            out.append(p)
    return out


#: PostgreSQL's type ids for json and jsonb.
JSON_TYPES = (114, 3802)


def _json(v):
    if isinstance(v, (str, bytes)):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def _clean(v):
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def rows(sql: str, params=()) -> list[dict]:
    with connection.cursor() as cur:
        cur.execute(sql, _params(params))
        if cur.description is None:
            return []
        names = [c.name for c in cur.description]
        # Django's own driver set-up hands jsonb back as text, for its JSONField
        # to read; here it is read at once.
        as_json = {i for i, c in enumerate(cur.description) if c.type_code in JSON_TYPES}
        return [{n: (_json(v) if i in as_json else _clean(v)) for i, (n, v) in enumerate(zip(names, r))}
                for r in cur.fetchall()]


def row(sql: str, params=()) -> dict | None:
    got = rows(sql, params)
    return got[0] if got else None


def value(sql: str, params=()):
    got = row(sql, params)
    return next(iter(got.values())) if got else None


def run(sql: str, params=()) -> int:
    with connection.cursor() as cur:
        cur.execute(sql, _params(params))
        return cur.rowcount


def atomic():
    return transaction.atomic()


def vec(values) -> str | None:
    """A vector as pgvector's text form."""
    if values is None:
        return None
    return "[" + ",".join(f"{float(x):.6f}" for x in values) + "]"


def ready() -> bool:
    """Whether the schema is there (the migration has run)."""
    try:
        return bool(value("SELECT to_regclass('synapse.dataset') IS NOT NULL"))
    except Exception:  # noqa: BLE001
        return False
