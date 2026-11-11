"""v14 multi-format storyboard loaders.

Reads storyboards from 4 formats and normalizes to the canonical dict
shape that v14_storyboard_renderer.render_storyboard expects.

Supported:
  - Lexicon JSON (.json)
  - TOML (.toml)
  - JSON-LD (.jsonld)
  - EDN / Datomic (.edn)
"""
from __future__ import annotations
import json
import os
import re


def load_any(path: str) -> dict:
    """Detect format from extension and load."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".json",):       return load_lexicon(path)
    if ext in (".toml",):       return load_toml(path)
    if ext in (".jsonld",):     return load_jsonld(path)
    if ext in (".edn",):        return load_edn(path)
    raise ValueError(f"unknown extension: {ext}")


# ── Lexicon JSON ──────────────────────────────────────────────────────
def load_lexicon(path: str) -> dict:
    return json.load(open(path))


# ── TOML ───────────────────────────────────────────────────────────────
def load_toml(path: str) -> dict:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with open(path, "rb") as f:
        d = tomllib.load(f)
    return {
        "pageNumber": d["page"]["number"],
        "pageTitle": d["page"].get("title", ""),
        "layout": d["page"].get("layout", ""),
        "baseTags": d["page"]["baseTags"],
        "negativeTags": d["page"]["negativeTags"],
        "panels": d["panels"],
    }


# ── JSON-LD (strip @-keys, keep flat structure) ──────────────────────
def load_jsonld(path: str) -> dict:
    d = json.load(open(path))
    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items() if not k.startswith("@")}
        if isinstance(o, list):
            return [clean(x) for x in o]
        if isinstance(o, str) and o.startswith("gh:"):
            # Strip namespace prefix from focal IDs
            return o.split("/", 1)[-1]
        return o
    return clean(d)


# ── EDN / Datomic ──────────────────────────────────────────────────────
def load_edn(path: str) -> dict:
    src = open(path).read()
    src = re.sub(r";;[^\n]*", "", src)
    src = src.strip()
    if src.startswith("["):
        src = src[1:-1].strip()
    entities = {}
    depth = 0
    start = -1
    for i, c in enumerate(src):
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                ent = parse_edn_entity(src[start + 1:i])
                if ent.get(":db/id"):
                    entities[ent[":db/id"]] = ent
    page = next((e for e in entities.values() if e.get(":page/number")), None)
    if not page:
        raise ValueError("no :page/number entity")
    panels = []
    for pid in page.get(":page/panels", []):
        p = entities.get(pid, {})
        if not p:
            continue
        panel = {
            "index": p.get(":panel/index"),
            "rect": p.get(":panel/rect"),
            "shot": p.get(":panel/shot"),
            "focal": [str(f).split("/")[-1] for f in p.get(":panel/focal", [])],
            "tone": p.get(":panel/tone"),
            "inkStyle": p.get(":panel/ink-style"),
            "tags": p.get(":panel/tags", []),
            "polygon": p.get(":panel/polygon"),
            "tilt": p.get(":panel/tilt", 0),
            "bleed": p.get(":panel/bleed", []),
            "z": p.get(":panel/z", 1),
            "bubbles": [], "sfx": [],
        }
        if p.get(":panel/screen-overlay"):
            panel["screenOverlay"] = p[":panel/screen-overlay"]
        for bid in p.get(":panel/bubbles", []):
            b = entities.get(bid, {})
            if b:
                panel["bubbles"].append({
                    "text": b.get(":bubble/text"),
                    "shape": b.get(":bubble/shape"),
                    "anchor": b.get(":bubble/anchor"),
                    "font": b.get(":bubble/font"),
                    "fontSize": b.get(":bubble/font-size"),
                    "rotation": b.get(":bubble/rotation"),
                    "writingMode": b.get(":bubble/writing-mode"),
                })
        for sid in p.get(":panel/sfx", []):
            s = entities.get(sid, {})
            if s:
                panel["sfx"].append({
                    "text": s.get(":sfx/text"),
                    "pos": s.get(":sfx/pos"),
                    "rot": s.get(":sfx/rot"),
                    "scale": s.get(":sfx/scale"),
                    "style": s.get(":sfx/style"),
                    "font": s.get(":sfx/font"),
                })
        panels.append(panel)
    return {
        "pageNumber": page.get(":page/number"),
        "pageTitle": page.get(":page/title", ""),
        "layout": page.get(":page/layout", ""),
        "baseTags": page.get(":page/base-tags"),
        "negativeTags": page.get(":page/negative-tags"),
        "panels": panels,
    }


def parse_edn_entity(s: str) -> dict:
    out, i, s = {}, 0, s.strip()
    while i < len(s):
        while i < len(s) and s[i] in " \n\t,":
            i += 1
        if i >= len(s):
            break
        if s[i] != ":":
            i += 1
            continue
        j = i
        while j < len(s) and s[j] not in " \n\t":
            j += 1
        key = s[i:j].strip()
        i = j
        while i < len(s) and s[i] in " \n\t":
            i += 1
        val, i = parse_edn_value(s, i)
        out[key] = val
    return out


def parse_edn_value(s: str, i: int):
    while i < len(s) and s[i] in " \n\t":
        i += 1
    if i >= len(s):
        return None, i
    c = s[i]
    if c == '"':
        end = s.index('"', i + 1)
        return s[i + 1:end], end + 1
    if c == '[':
        depth, j = 0, i
        while j < len(s):
            if s[j] == '[':
                depth += 1
            elif s[j] == ']':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        inner = s[i + 1:j]
        items = []
        ii = 0
        while ii < len(inner):
            while ii < len(inner) and inner[ii] in " \n\t,":
                ii += 1
            if ii >= len(inner):
                break
            v, ii = parse_edn_value(inner, ii)
            items.append(v)
        return items, j + 1
    if c == ':':
        j = i
        while j < len(s) and s[j] not in " \n\t,]}":
            j += 1
        return s[i:j], j
    j = i
    while j < len(s) and s[j] not in " \n\t,]}\"":
        j += 1
    tok = s[i:j]
    try:
        return float(tok) if '.' in tok else int(tok), j
    except ValueError:
        return tok, j
