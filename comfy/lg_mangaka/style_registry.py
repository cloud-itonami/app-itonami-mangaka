"""Theme-driven style switching for the manga render pipeline.

Reads `data/style-registry.edn` (SSoT, EDN per repo convention) and resolves a
render style profile from a work's theme/genre (and optionally shot type):

    resolve(work_rkey, genre, shot) -> {
        "profile": "<key>", "mode": "ink"|"color",
        "positive": "...", "negative": "...",
        "cfg": float, "steps": int, "sampler": "...",
    }

Resolution order: :default <- :genre->style[genre] <- :work->style[work_rkey]
(work override wins); the matching :shot-modifiers entry is appended to positive.

A tiny EDN reader (maps / vectors / keywords / strings / numbers / `;` comments)
is embedded so no extra dependency is needed; keywords become plain string keys
(`:profiles` -> "profiles", `:ink` -> "ink").
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "style-registry.edn"

_TOK = re.compile(
    r"""(?P<ws>[\s,]+)|(?P<comment>;[^\n]*)|(?P<lb>\{)|(?P<rb>\})|"""
    r"""(?P<lk>\[)|(?P<rk>\])|(?P<str>"(?:\\.|[^"\\])*")|"""
    r"""(?P<kw>:[^\s,{}\[\]"]+)|(?P<num>-?\d+\.?\d*)|(?P<sym>[^\s,{}\[\]"]+)""",
    re.VERBOSE,
)


def _tokens(s: str):
    for m in _TOK.finditer(s):
        k = m.lastgroup
        if k in ("ws", "comment"):
            continue
        yield k, m.group()


def _parse(toks, i):
    k, v = toks[i]
    if k == "lb":  # map
        i += 1
        d = {}
        while toks[i][0] != "rb":
            key, i = _parse(toks, i)
            val, i = _parse(toks, i)
            d[key] = val
        return d, i + 1
    if k == "lk":  # vector
        i += 1
        out = []
        while toks[i][0] != "rk":
            item, i = _parse(toks, i)
            out.append(item)
        return out, i + 1
    if k == "str":
        return v[1:-1].encode().decode("unicode_escape") if "\\" in v else v[1:-1], i + 1
    if k == "kw":
        return v[1:], i + 1  # keyword -> bare name
    if k == "num":
        return (float(v) if "." in v else int(v)), i + 1
    return v, i + 1  # symbol -> string


def _read_edn(text: str):
    toks = list(_tokens(text))
    val, _ = _parse(toks, 0)
    return val


_CACHE: dict | None = None


def _registry() -> dict:
    global _CACHE
    if _CACHE is None:
        path = Path(os.environ.get("MANGAKA_STYLE_REGISTRY", str(_DEFAULT_PATH)))
        _CACHE = _read_edn(path.read_text(encoding="utf-8"))
    return _CACHE


def resolve(work_rkey: str = "", genre: str = "", shot: str = "") -> dict:
    """Resolve the render style profile for a work (by override or genre)."""
    reg = _registry()
    profiles = reg.get("profiles", {})
    key = (reg.get("work->style", {}).get(work_rkey)
           or reg.get("genre->style", {}).get(genre)
           or reg.get("default"))
    prof = dict(profiles.get(key) or {})
    prof["profile"] = key
    mod = reg.get("shot-modifiers", {}).get((shot or "").lower())
    if mod and prof.get("positive"):
        prof["positive"] = prof["positive"] + ", " + mod
    return prof


if __name__ == "__main__":  # quick self-check
    import json
    for w, g, sh in [("yamainu-1", "", "wide"), ("", "音楽×超常ドラマ", "closeup"),
                     ("halfgram-1", "", ""), ("", "unknown", "")]:
        r = resolve(w, g, sh)
        print(w or g, "->", r["profile"], "|", r["mode"], "| cfg", r["cfg"],
              "| +shot:", "wide" in r["positive"] or "close" in r["positive"])
