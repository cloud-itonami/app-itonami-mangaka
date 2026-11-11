"""StoryboardDB ↔ prolly tree adapter — branchable, content-addressed manga.

Maps the Datomic-style storyboard SSoT (storyboard_db.StoryboardDB) and the
rendered page blobs onto a prolly tree (prolly.ProllyRepo) so an episode can be
committed, branched, switched, diffed and merged like git-for-data — but with
structural sharing and history-independent content addresses.

Key namespaces inside one prolly map:
  sb/<eid>       canonical-JSON of a storyboard entity (page / panel / bubble /
                 sfx / character …). This is the editable SSoT.
  page/<rkey>    rendered-page record: {blobCid, bytes, ext, finalPng, edn,
                 width, height} — blobCid is the git-annex MD5E key (already a
                 content address), so switching branches/versions of the SAME
                 page costs nothing.
  meta/<k>       episode-level metadata (episode id, version, page list).

CLI:
  python -m lg_mangaka.storyboard_prolly status        [--store DIR]
  python -m lg_mangaka.storyboard_prolly log    [--branch B]
  python -m lg_mangaka.storyboard_prolly branches
  python -m lg_mangaka.storyboard_prolly branch  NAME  [--from COMMIT]
  python -m lg_mangaka.storyboard_prolly switch  NAME
  python -m lg_mangaka.storyboard_prolly diff    A B   (branch or commit hashes)
  python -m lg_mangaka.storyboard_prolly merge   OTHER [--into B]
  python -m lg_mangaka.storyboard_prolly checkout NAME --out-edn FILE   (page export)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from lg_mangaka.prolly import ProllyRepo, ProllyTree, canonical
from lg_mangaka.storyboard_db import StoryboardDB

DEFAULT_STORE = (".prolly")  # resolved relative to the data dir by the caller


# ── mapping: StoryboardDB + pages ⇄ prolly key→bytes map ───────────────────
def db_to_mapping(db: StoryboardDB) -> dict[str, bytes]:
    """Serialize every entity under sb/<eid>."""
    out: dict[str, bytes] = {}
    for eid, attrs in db.entities.items():
        out[f"sb/{eid}"] = canonical(attrs)
    return out


def mapping_to_db(mapping: dict[str, bytes]) -> StoryboardDB:
    """Reconstruct a StoryboardDB from the sb/ keys of a prolly map."""
    db = StoryboardDB()
    for k, v in mapping.items():
        if k.startswith("sb/"):
            db.entities[k[3:]] = json.loads(v)
    db._next_tx = 1
    return db


def annex_blob_cid(png_path: str) -> Optional[str]:
    """Return a git-annex-style content address for a final page.

    Locked annex files are symlinks whose target IS the key (e.g.
    MD5E-s3459426--<md5>.png) — reuse it verbatim. Unlocked files are plain
    bytes (the dataset can be in an unlocked/adjusted state), so compute the
    same MD5E key from content: `MD5E-s<size>--<md5hex>.<ext>`. Either path
    yields the identical, stable content address.
    """
    try:
        target = os.readlink(png_path)
        base = os.path.basename(target)
        if base.startswith(("MD5E-", "SHA256E-", "SHA256-")):
            return base
    except OSError:
        pass
    # unlocked / regular file → compute MD5E key from content
    import hashlib
    try:
        st = os.stat(png_path, follow_symlinks=True)
        h = hashlib.md5()
        with open(png_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    ext = os.path.splitext(png_path)[1].lstrip(".") or "bin"
    return f"MD5E-s{st.st_size}--{h.hexdigest()}.{ext}"


def scan_pages(v14_dir: str) -> dict[str, bytes]:
    """Build page/<rkey> records from <v14_dir>/final-pages + sidecars + edn."""
    out: dict[str, bytes] = {}
    final = Path(v14_dir) / "final-pages"
    sidecars = Path(v14_dir) / "sidecars"
    edn_dir = Path(v14_dir) / "storyboard-edn"
    if not final.is_dir():
        return out
    for png in sorted(final.glob("v14-*-final.png")):
        # v14-p04-final.png → rkey p04
        stem = png.stem                       # v14-p04-final
        rkey = stem.replace("v14-", "").replace("-final", "")
        cid = annex_blob_cid(str(png))
        try:
            nbytes = os.stat(png, follow_symlinks=True).st_size
        except OSError:
            nbytes = None
        width = height = None
        sc = sidecars / f"v14-{rkey}-sidecar.json"
        if sc.exists():
            try:
                sj = json.loads(sc.read_text())
                ps = sj.get("page_size")
                if isinstance(ps, list) and len(ps) == 2:
                    width, height = ps
            except Exception:
                pass
        edn = edn_dir / f"{rkey}-datomic.edn"
        rec = {
            "$type": "ai.gftd.mangaka.page",
            "rkey": rkey,
            "blobCid": cid,
            "bytes": nbytes,
            "ext": "png",
            "finalPng": str(png.relative_to(v14_dir)),
            "edn": str(edn.relative_to(v14_dir)) if edn.exists() else None,
            "width": width,
            "height": height,
        }
        out[f"page/{rkey}"] = canonical({k: v for k, v in rec.items() if v is not None})
    return out


def load_episode_db(edn_dir: str) -> StoryboardDB:
    """Merge every *-datomic.edn (+ characters.edn) into one StoryboardDB."""
    edn = Path(edn_dir)
    db = StoryboardDB()
    chars = edn / "characters.edn"
    if chars.exists():
        db.merge_db(StoryboardDB.load_edn(str(chars)))
    for f in sorted(edn.glob("*-datomic.edn")):
        db.merge_db(StoryboardDB.load_edn(str(f)))
    return db


def build_episode_mapping(v14_dir: str, episode: str = "ghosthacker/arc0-1-origin",
                          version: str = "v14") -> tuple[dict[str, bytes], dict]:
    """Full prolly map for an episode: entities + page blobs + meta."""
    edn_dir = os.path.join(v14_dir, "storyboard-edn")
    db = load_episode_db(edn_dir)
    mapping = db_to_mapping(db)
    pages = scan_pages(v14_dir)
    mapping.update(pages)
    page_rkeys = sorted(k[len("page/"):] for k in pages)
    meta = {
        "$type": "ai.gftd.mangaka.episode",
        "episode": episode,
        "version": version,
        "entityCount": len(db.entities),
        "pageCount": len(pages),
        "pages": page_rkeys,
    }
    mapping["meta/episode"] = canonical(meta)
    stats = {"entities": len(db.entities), "pages": len(pages),
             "pageRkeys": page_rkeys}
    return mapping, stats


# ── high-level repo ops ────────────────────────────────────────────────────
class StoryboardProlly:
    def __init__(self, store_dir: str, avg: int = 8):
        self.repo = ProllyRepo(store_dir, avg=avg)

    def commit_episode(self, v14_dir: str, note: str, branch: str = "v14",
                       episode: str = "ghosthacker/arc0-1-origin",
                       version: str = "v14") -> tuple[str, dict]:
        mapping, stats = build_episode_mapping(v14_dir, episode, version)
        ch = self.repo.commit(mapping, note=note, ts=time.time(), branch=branch,
                              meta={"episode": episode, "version": version,
                                    **{k: stats[k] for k in ("entities", "pages")}})
        # ensure HEAD tracks this branch the first time
        if self.repo.current_branch() is None:
            self.repo.store.set_head(branch)
        return ch, stats

    def status(self) -> dict:
        return {
            "currentBranch": self.repo.current_branch(),
            "headCommit": self.repo.head_commit(),
            "branches": self.repo.branches(),
        }

    def diff_refs(self, a: str, b: str) -> dict:
        ca = self.repo.store.get_ref(a) or a
        cb = self.repo.store.get_ref(b) or b
        ta = self.repo.tree_at(ca)
        tb = self.repo.tree_at(cb)
        return ta.diff(tb)

    def checkout_db(self, ref: str) -> StoryboardDB:
        commit = self.repo.store.get_ref(ref) or ref
        tree = self.repo.tree_at(commit)
        return mapping_to_db(tree.to_dict())


# ── CLI ────────────────────────────────────────────────────────────────────
def _default_store() -> str:
    """`<repo>/data/ghosthacker/.../arc0-1-origin/v14/.prolly` by default."""
    here = Path(__file__).resolve()
    # lg/lg_mangaka/storyboard_prolly.py → project root is parents[2]
    proj = here.parents[2]
    return str(proj / "data/ghosthacker/resources/episodes/arc0-1-origin/v14/.prolly")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="storyboard prolly tree — git-for-manga")
    ap.add_argument("--store", default=None, help="prolly store dir (default: v14/.prolly)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p_log = sub.add_parser("log"); p_log.add_argument("--branch", default=None)
    sub.add_parser("branches")
    p_br = sub.add_parser("branch"); p_br.add_argument("name"); p_br.add_argument("--from", dest="frm", default=None)
    p_sw = sub.add_parser("switch"); p_sw.add_argument("name")
    p_df = sub.add_parser("diff"); p_df.add_argument("a"); p_df.add_argument("b")
    p_mg = sub.add_parser("merge"); p_mg.add_argument("other"); p_mg.add_argument("--into", default=None)
    p_co = sub.add_parser("checkout"); p_co.add_argument("ref"); p_co.add_argument("--out-edn", default=None); p_co.add_argument("--page", default=None)
    args = ap.parse_args(argv)

    store = args.store or _default_store()
    sp = StoryboardProlly(store)
    repo = sp.repo

    if args.cmd == "status":
        st = sp.status()
        print(f"store:  {store}")
        print(f"branch: {st['currentBranch']}")
        print(f"head:   {st['headCommit']}")
        print(f"branches ({len(st['branches'])}):")
        for b, c in sorted(st["branches"].items()):
            mark = "*" if b == st["currentBranch"] else " "
            print(f"  {mark} {b:24s} {c}")
    elif args.cmd == "log":
        for h, c in repo.log(args.branch):
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(c.ts))
            print(f"{h}  {ts}  {c.note}  {c.meta}")
    elif args.cmd == "branches":
        cur = repo.current_branch()
        for b, c in sorted(repo.branches().items()):
            print(f"{'*' if b==cur else ' '} {b:24s} {c}")
    elif args.cmd == "branch":
        repo.create_branch(args.name, args.frm)
        print(f"created branch {args.name} -> {repo.store.get_ref(args.name)}")
    elif args.cmd == "switch":
        repo.switch(args.name)
        print(f"switched to {args.name} (head {repo.head_commit()})")
    elif args.cmd == "diff":
        d = sp.diff_refs(args.a, args.b)
        print(f"diff {args.a} -> {args.b}")
        for kind in ("added", "removed", "changed"):
            ks = d[kind]
            print(f"  {kind} ({len(ks)}): {', '.join(ks[:20])}{' …' if len(ks)>20 else ''}")
    elif args.cmd == "merge":
        ch, conflicts = repo.merge(args.other, ts=time.time(), into=args.into)
        print(f"merged {args.other} -> {args.into or repo.current_branch()} = {ch}")
        if conflicts:
            print(f"  CONFLICTS (ours kept): {', '.join(conflicts)}")
        else:
            print("  clean merge")
    elif args.cmd == "checkout":
        db = sp.checkout_db(args.ref)
        if args.page:
            # export one page's lexicon JSON
            pid = next((e for e in db.entities if e == args.page
                        or db.entities[e].get(":page/number") == int(args.page)
                        if isinstance(db.entities[e].get(":page/number"), int)
                        or e == args.page), None)
            print(json.dumps(db.export_lexicon(pid or args.page), ensure_ascii=False, indent=2))
        elif args.out_edn:
            db.save_edn(args.out_edn, header=f";; checkout {args.ref}")
            print(f"wrote {len(db.entities)} entities -> {args.out_edn}")
        else:
            print(f"checked out {args.ref}: {len(db.entities)} entities")


if __name__ == "__main__":
    main()
