"""Datomic-style storyboard SSoT — entity store with datalog-style query +
Lexicon JSON wire export.

Design:
  - Entities = dict[eid -> dict[attr -> value]]. Each entity has :db/id.
  - Refs = entity IDs (string). Lookup-ref pattern: [:character/Nei] etc.
  - Transactions = append-only log of (:add/:retract, eid, attr, value)
  - Query = simple pattern matching (where, find, rule)
  - History = full tx log, time-travel via as_of(tx_id)
  - Wire = export_lexicon(page_id) → Lexicon JSON dict (renderer consumes)

This is NOT a full Datomic (no MVCC, no Pull syntax, no Datomic Pro features).
It's a minimum-viable Python implementation that gives:
  - Entity-level edits (no nested-doc-rewriting)
  - Cross-page query (find all panels with focal=:character/Nei)
  - Bulk update by pattern
  - Transaction history (for time-travel A/B, audit)
  - Lexicon JSON export for wire (AT Protocol record)

CLI demo:
  python -m lg_mangaka.storyboard_db --load p38.edn --query 'focal=:character/Nei'
  python -m lg_mangaka.storyboard_db --load p38.edn --update togashi:1.5=togashi:1.3
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


# ── EDN parser (re-uses logic from v14_format_loaders.load_edn) ──────────
def _parse_edn_value(s: str, i: int):
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
        items, ii = [], 0
        while ii < len(inner):
            while ii < len(inner) and inner[ii] in " \n\t,":
                ii += 1
            if ii >= len(inner):
                break
            v, ii = _parse_edn_value(inner, ii)
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


def _parse_edn_entity(s: str) -> dict:
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
        val, i = _parse_edn_value(s, i)
        out[key] = val
    return out


# ── Transaction record ──────────────────────────────────────────────────
@dataclass
class TxOp:
    op: str          # ":add" or ":retract"
    eid: str
    attr: str
    value: Any


@dataclass
class Transaction:
    tx_id: int
    ts: float        # unix epoch
    ops: list[TxOp]
    note: str = ""


# ── Storyboard DB ───────────────────────────────────────────────────────
@dataclass
class StoryboardDB:
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    tx_log: list[Transaction] = field(default_factory=list)
    _next_tx: int = 0

    # ── Loading ──────────────────────────────────────────────────────────
    @classmethod
    def load_edn(cls, path: str) -> StoryboardDB:
        db = cls()
        src = re.sub(r";;[^\n]*", "", open(path).read()).strip()
        if src.startswith("["):
            src = src[1:-1].strip()
        depth, start = 0, -1
        for i, c in enumerate(src):
            if c == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    ent = _parse_edn_entity(src[start + 1:i])
                    eid = ent.pop(":db/id", None)
                    if eid:
                        db.entities[eid] = ent
        db._next_tx = 1
        return db

    # ── Save ─────────────────────────────────────────────────────────────
    def save_edn(self, path: str, header: str = ";; storyboard SSoT"):
        with open(path, "w") as f:
            f.write(f"{header}\n;; ({len(self.entities)} entities, {len(self.tx_log)} tx)\n\n[\n")
            for eid, attrs in self.entities.items():
                f.write(f' {{:db/id "{eid}"\n')
                for k, v in attrs.items():
                    f.write(f"  {k} {self._edn(v)}\n")
                f.write(" }\n\n")
            f.write("]\n")

    def _edn(self, v) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, str):
            if v.startswith(":"):
                return v
            return f'"{v}"'
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, (list, tuple)):
            return "[" + " ".join(self._edn(x) for x in v) + "]"
        return f'"{v}"'

    # ── Transactions ─────────────────────────────────────────────────────
    def transact(self, ops: list[tuple], note: str = "") -> int:
        """Apply a transaction.

        ops: list of (op, eid, attr, value) tuples where op is ":add" or ":retract".
        Returns: tx_id
        """
        self._next_tx += 1
        tx_id = self._next_tx
        tx_ops = []
        for op in ops:
            if len(op) == 3:
                op_kind, eid, attr = op
                value = None
            else:
                op_kind, eid, attr, value = op
            if op_kind == ":add":
                self.entities.setdefault(eid, {})[attr] = value
            elif op_kind == ":retract":
                if eid in self.entities and attr in self.entities[eid]:
                    if value is None or self.entities[eid][attr] == value:
                        del self.entities[eid][attr]
            else:
                raise ValueError(f"unknown op: {op_kind}")
            tx_ops.append(TxOp(op_kind, eid, attr, value))
        self.tx_log.append(Transaction(tx_id, time.time(), tx_ops, note))
        return tx_id

    # ── Query ────────────────────────────────────────────────────────────
    def find(self, **pattern) -> list[str]:
        """Find entity IDs matching all attr=value pairs.

        Special: value-as-list checks for inclusion (any match).
        """
        out = []
        for eid, attrs in self.entities.items():
            ok = True
            for k, v in pattern.items():
                actual = attrs.get(k)
                if isinstance(actual, list):
                    if v not in actual:
                        ok = False
                        break
                elif actual != v:
                    ok = False
                    break
            if ok:
                out.append(eid)
        return out

    def get(self, eid: str, attr: str = None):
        ent = self.entities.get(eid, {})
        return ent if attr is None else ent.get(attr)

    # ── Bulk operations ──────────────────────────────────────────────────
    def update_tag(self, old_tag: str, new_tag: str, page_filter: str = None) -> int:
        """Replace a tag value across :page/base-tags or :panel/tags.

        page_filter: if set, only update pages with this :db/id prefix.
        """
        ops = []
        for eid, attrs in self.entities.items():
            if page_filter and not eid.startswith(page_filter):
                continue
            for attr in (":page/base-tags", ":page/negative-tags", ":panel/tags"):
                tags = attrs.get(attr)
                if not isinstance(tags, list):
                    continue
                if old_tag not in tags:
                    continue
                new_tags = [new_tag if t == old_tag else t for t in tags]
                ops.append((":retract", eid, attr, tags))
                ops.append((":add", eid, attr, new_tags))
        if ops:
            self.transact(ops, note=f"update_tag '{old_tag}' → '{new_tag}'")
        return len(ops) // 2

    def panels_for_character(self, char: str) -> list[str]:
        """Find all panels with this character in :panel/focal."""
        return self.find(**{":panel/focal": f":character/{char}"})

    def merge_db(self, other: StoryboardDB) -> None:
        """Add other DB's entities (e.g. characters.edn) into this db.
        Skips duplicates (existing eids win)."""
        for eid, attrs in other.entities.items():
            if eid not in self.entities:
                self.entities[eid] = attrs

    def _resolve_character_tags(self, focal_refs: list) -> list[str]:
        """For each :character/<Name> ref, look up char-<name> entity tags."""
        tags = []
        for ref in focal_refs:
            ref_str = str(ref)
            # ":character/Ren" → "char-ren"
            if ref_str.startswith(":character/"):
                name = ref_str.split("/")[-1].lower()
                eid = f"char-{name}"
                ent = self.entities.get(eid, {})
                tags.extend(ent.get(":character/tags", []))
        return tags

    # ── Export to Lexicon JSON wire format ───────────────────────────────
    def export_lexicon(self, page_id: str) -> dict:
        """Build the Lexicon JSON record for one page."""
        page = self.entities.get(page_id)
        if not page:
            raise KeyError(f"no page entity: {page_id}")
        panels_out = []
        for pid in page.get(":page/panels", []):
            p = self.entities.get(pid, {})
            if not p:
                continue
            bubbles_out = []
            for bid in p.get(":panel/bubbles", []):
                b = self.entities.get(bid, {})
                if not b:
                    continue
                bub = {
                    "text": b.get(":bubble/text"),
                    "shape": b.get(":bubble/shape"),
                    "anchor": b.get(":bubble/anchor"),
                    "font": b.get(":bubble/font"),
                    "fontSize": b.get(":bubble/font-size"),
                    # renderer reads kebab key "max-chars-per-col"; pass it
                    # through so EDN can cap vertical wrapping per bubble
                    # (previously dropped → short dialogue split mid-word).
                    "max-chars-per-col": b.get(":bubble/max-chars-per-col"),
                }
                if b.get(":bubble/rotation") is not None:
                    bub["rotation"] = b[":bubble/rotation"]
                if b.get(":bubble/writing-mode"):
                    bub["writingMode"] = b[":bubble/writing-mode"]
                bubbles_out.append({k: v for k, v in bub.items() if v is not None})
            sfx_out = []
            for sid in p.get(":panel/sfx", []):
                s = self.entities.get(sid, {})
                if not s:
                    continue
                sfx = {
                    "text": s.get(":sfx/text"),
                    "pos": s.get(":sfx/pos"),
                    "rot": s.get(":sfx/rot"),
                    "scale": s.get(":sfx/scale"),
                    "style": s.get(":sfx/style"),
                }
                if s.get(":sfx/font"):
                    sfx["font"] = s[":sfx/font"]
                sfx_out.append({k: v for k, v in sfx.items() if v is not None})
            # Inline character template tags (Datomic ref expansion)
            focal_refs = p.get(":panel/focal", [])
            char_tags = self._resolve_character_tags(focal_refs)
            panel = {
                "$type": "ai.gftd.mangaka.storyboard#panel",
                "index": p.get(":panel/index"),
                "rect": p.get(":panel/rect"),
                "shot": p.get(":panel/shot"),
                "focal": [str(f).replace(":character/", "") for f in focal_refs],
                "tone": p.get(":panel/tone"),
                # Character tags first, then panel-specific tags (panel can override)
                "tags": char_tags + p.get(":panel/tags", []),
                "bubbles": bubbles_out,
                "sfx": sfx_out,
            }
            # Optional v14.5 effects
            if p.get(":panel/polygon"):
                panel["polygon"] = p[":panel/polygon"]
            if p.get(":panel/tilt"):
                panel["tilt"] = p[":panel/tilt"]
            if p.get(":panel/bleed"):
                panel["bleed"] = p[":panel/bleed"]
            if p.get(":panel/z"):
                panel["z"] = p[":panel/z"]
            if p.get(":panel/ink-style"):
                panel["inkStyle"] = p[":panel/ink-style"]
            # v15 — thoughts (no bubble, rendered as italic floating text)
            thoughts_out = []
            for tid in p.get(":panel/thoughts", []):
                t = self.entities.get(tid, {})
                if t:
                    thoughts_out.append({
                        "text": t.get(":thought/text"),
                        "pos": t.get(":thought/pos"),
                        "rot": t.get(":thought/rot", 0),
                        "scale": t.get(":thought/scale", 1.0),
                    })
            if thoughts_out:
                panel["thoughts"] = thoughts_out
            # v15 — telops (character intro corner-box)
            telops_out = []
            for tid in p.get(":panel/telops", []):
                t = self.entities.get(tid, {})
                if t:
                    telops_out.append({
                        "text": t.get(":telop/text"),
                        "anchor": t.get(":telop/anchor", "bottom-right"),
                        "fontSize": t.get(":telop/font-size", 18),
                    })
            if telops_out:
                panel["telops"] = telops_out
            # screen-overlay — legible UI vector [kind, *args] (SDXL can't draw UI text)
            if p.get(":panel/screen-overlay"):
                panel["screenOverlay"] = p[":panel/screen-overlay"]
            panel = {k: v for k, v in panel.items() if v is not None and v != []}
            panels_out.append(panel)
        return {
            "$type": "ai.gftd.mangaka.storyboard",
            "pageNumber": page.get(":page/number"),
            "pageTitle": page.get(":page/title", ""),
            "layout": page.get(":page/layout", ""),
            "baseTags": page.get(":page/base-tags", []),
            "negativeTags": page.get(":page/negative-tags", []),
            "panels": panels_out,
        }

    # ── History / time-travel ────────────────────────────────────────────
    def history_summary(self) -> list[str]:
        return [f"tx {t.tx_id} @ {time.strftime('%H:%M:%S', time.localtime(t.ts))} "
                f"{len(t.ops)} ops · {t.note}"
                for t in self.tx_log]


# ── CLI ─────────────────────────────────────────────────────────────────
def _cli():
    import argparse, sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", required=True, help="EDN file")
    ap.add_argument("--query-char", help="find panels with this character focal")
    ap.add_argument("--update-tag", nargs=2, metavar=("OLD", "NEW"),
                     help="replace tag old→new across all pages")
    ap.add_argument("--export-lexicon", metavar="PAGE_ID",
                     help="export Lexicon JSON for a page entity")
    ap.add_argument("--save-edn", metavar="PATH", help="write updated EDN")
    ap.add_argument("--history", action="store_true")
    args = ap.parse_args()

    db = StoryboardDB.load_edn(args.load)
    print(f"loaded {len(db.entities)} entities from {args.load}")

    if args.query_char:
        eids = db.panels_for_character(args.query_char)
        print(f"\n[query] panels with focal=:character/{args.query_char}:")
        for eid in eids:
            p = db.get(eid)
            print(f"  {eid}: shot={p.get(':panel/shot')}, idx={p.get(':panel/index')}")

    if args.update_tag:
        old, new = args.update_tag
        n = db.update_tag(old, new)
        print(f"\n[update] {n} updates applied: '{old}' → '{new}'")

    if args.export_lexicon:
        lex = db.export_lexicon(args.export_lexicon)
        print(f"\n[export-lexicon] {args.export_lexicon}:")
        print(json.dumps(lex, ensure_ascii=False, indent=2))

    if args.save_edn:
        db.save_edn(args.save_edn)
        print(f"\nsaved → {args.save_edn}")

    if args.history:
        print("\n[history]")
        for line in db.history_summary():
            print(f"  {line}")


if __name__ == "__main__":
    _cli()
