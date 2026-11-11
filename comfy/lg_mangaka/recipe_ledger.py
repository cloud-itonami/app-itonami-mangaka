"""Recipe → published-post ledger (the attribution join for reaction fitness).

At publish time we record which render recipe produced a work and which social
post (AT-URI) announced it. Later the co-scientist joins real engagement on that
post back to the recipe's style fingerprint, so the crowd's reaction becomes the
fitness (ADR-2606181200).

A newline-delimited JSON ledger (append-only, crash-safe, diffable). Path is
`$MANGAKA_RECIPE_LEDGER` or `data/recipe-ledger.jsonl`. Deliberately file-based
for the first cut — no D1 migration needed to start collecting attribution; a
D1 table can mirror it later.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from lg_mangaka import recipe_fingerprint as _fp


def _path() -> Path:
    p = os.environ.get("MANGAKA_RECIPE_LEDGER")
    if p:
        return Path(p)
    # default: <repo>/.../ai-gftd-project-mangaka/data/recipe-ledger.jsonl
    return Path(__file__).resolve().parents[2] / "data" / "recipe-ledger.jsonl"


def record(recipe: dict, *, work_rkey: str, post_uri: str, ts: str,
           extra: dict | None = None) -> dict:
    """Append one attribution row. `ts` is caller-supplied (ISO) — this module
    never reads the clock so it stays deterministic/testable."""
    row = {"fingerprint": _fp.fingerprint(recipe), "recipe": recipe,
           "work_rkey": work_rkey, "post_uri": post_uri, "ts": ts}
    if extra:
        row.update(extra)
    fp = _path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    with fp.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def entries() -> list[dict]:
    fp = _path()
    if not fp.exists():
        return []
    rows = []
    for line in fp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def post_uris_for(fingerprint: str) -> list[str]:
    """Every published post URI produced by recipes of this style fingerprint."""
    return [e["post_uri"] for e in entries()
            if e.get("fingerprint") == fingerprint and e.get("post_uri")]
