"""mangaka D1 data-access layer (RW decommission, 2026-06-11).

Replaces the inline RisingWave psycopg calls in cine.py / tools.py /
hume_distill.py. The pod has no Cloudflare token, so all D1 access is proxied
through the appview Worker's internal endpoint (pod → Worker → D1), same
topology as shinshi (ADR-2606040000), yukkuri (ADR-2606041900) and animeka.

Like animeka, mangaka's SQL spans several tables, so the Worker endpoint
(svelte/src/routes/_d1/+server.ts) exposes two constrained generic ops instead
of typed ones:

  query   {sql, params}  — single SELECT on an allow-listed mangaka table
  execute {sql, params}  — single INSERT/UPDATE/DELETE on an allow-listed table

``query()``/``execute()`` accept psycopg-style ``%s`` placeholders and convert
them to D1 ``?`` so the existing SQL strings port mechanically. Schema-qualified
names (``graphar.vertex_mangaka``) are also rewritten to the bare D1 table name.

Env:
  MANGAKA_D1_WRITER_URL      appview internal endpoint, e.g. https://mangaka.gftd.ai/_d1
  DISPATCHER_INTERNAL_SECRET (or MANGAKA_D1_WRITER_SECRET) — x-internal-trust value
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

_WRITER_URL = (os.environ.get("MANGAKA_D1_WRITER_URL") or "").rstrip("/")
_WRITER_SECRET = (
    os.environ.get("MANGAKA_D1_WRITER_SECRET")
    or os.environ.get("DISPATCHER_INTERNAL_SECRET")
    or ""
)
_TIMEOUT = float(os.environ.get("MANGAKA_D1_TIMEOUT_SEC", "30"))

# D1 has no schemas — strip the RW ``graphar.`` qualifier so the same SQL
# strings work against the flat D1 namespace.
_SCHEMA_RE = re.compile(r"\bgraphar\.", re.IGNORECASE)


def writer_configured() -> bool:
    """True when the D1 endpoint URL is set (parallels the old ``if not _RW_URL``)."""
    return bool(_WRITER_URL)


def _to_d1_placeholders(sql: str) -> str:
    """psycopg ``%s`` → D1 ``?`` (positional). ``%%`` escapes a literal ``%``."""
    out: list[str] = []
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "%" and i + 1 < len(sql):
            nxt = sql[i + 1]
            if nxt == "s":
                out.append("?")
                i += 2
                continue
            if nxt == "%":
                out.append("%")
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _normalize(sql: str) -> str:
    return _to_d1_placeholders(_SCHEMA_RE.sub("", sql))


async def _call(op: str, sql: str, params: list[Any] | tuple[Any, ...] | None) -> dict[str, Any]:
    if not _WRITER_URL:
        raise RuntimeError("MANGAKA_D1_WRITER_URL not set")
    headers = {"Content-Type": "application/json"}
    if _WRITER_SECRET:
        headers["x-internal-trust"] = _WRITER_SECRET
    body = {"op": op, "sql": _normalize(sql), "params": list(params or [])}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(_WRITER_URL, json=body, headers=headers)
    if r.status_code >= 400:
        raise RuntimeError(f"d1 {op} HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"d1 {op}: {data.get('error', 'unknown error')}")
    return data


async def query(sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
    """Run a SELECT. Returns rows as dicts keyed by column name."""
    data = await _call("query", sql, params)
    return data.get("rows") or []


async def query_one(sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> dict[str, Any] | None:
    rows = await query(sql, params)
    return rows[0] if rows else None


async def execute(sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> int:
    """Run INSERT/UPDATE/DELETE. Returns affected-row count when D1 reports it."""
    data = await _call("execute", sql, params)
    ch = data.get("changes")
    return int(ch) if isinstance(ch, (int, float)) else 0
