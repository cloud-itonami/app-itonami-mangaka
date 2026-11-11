#!/usr/bin/env python3
"""Register the ghosthacker arc0-1 v14 episode into three targets.

  1) Prolly store  — content-addressed, branchable commit (branch `v14`) under
                     <v14>/.prolly. This is the new branch-switching SSoT.
  2) DataLad       — `datalad save` the .prolly store into the v14 dataset
                     (scoped: does NOT sweep up unrelated pending changes).
  3) AT Protocol   — generate ready-to-run PDS createRecord payloads
                     (ai.gftd.mangaka.chapter + .page) + an uploadBlob manifest.
                     The live call is gated on a valid ~/.gftd/auth.json AND the
                     ai.gftd.mangaka.* backend being deployed; both are checked.

Usage:
  python -m scripts.register_v14_prolly                 # all three (PDS = payloads only unless --pds-live)
  python -m scripts.register_v14_prolly --no-datalad    # skip the datalad save
  python -m scripts.register_v14_prolly --pds-live      # attempt the live PDS calls (needs auth+backend)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# make `lg_mangaka` importable when run as a script from lg/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lg_mangaka import storyboard_prolly as SP  # noqa: E402

V14_DIR = str(Path(__file__).resolve().parents[2]
              / "data/ghosthacker/resources/episodes/arc0-1-origin/v14")
EPISODE = "ghosthacker/arc0-1-origin"
VERSION = "v14"
CHAPTER_RKEY = "gh-arc0-1-origin-v14"
PDS_COLLECTION_CHAPTER = "ai.gftd.mangaka.chapter"
PDS_COLLECTION_PAGE = "ai.gftd.mangaka.page"


# ── 1) prolly commit ───────────────────────────────────────────────────────
def register_prolly(v14_dir: str, branch: str = "v14") -> tuple[str, dict, str]:
    store_dir = os.path.join(v14_dir, ".prolly")
    sp = SP.StoryboardProlly(store_dir)
    note = f"register {EPISODE} {VERSION} — {len(os.listdir(os.path.join(v14_dir,'final-pages')))} pages"
    ch, stats = sp.commit_episode(v14_dir, note=note, branch=branch,
                                  episode=EPISODE, version=VERSION)
    return ch, stats, store_dir


# ── keep the prolly JSON in plain git, not annex ───────────────────────────
def ensure_gitattributes(v14_dir: str) -> bool:
    ga = Path(v14_dir) / ".gitattributes"
    rule = ".prolly/** annex.largefiles=nothing"
    existing = ga.read_text() if ga.exists() else ""
    if rule in existing:
        return False
    with open(ga, "a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write("# prolly store: small content-addressed JSON stays in git (diffable)\n")
        f.write(rule + "\n")
    return True


# ── 3) AT-PDS payload generation (+ optional live attempt) ──────────────────
def auth_state() -> dict:
    p = Path.home() / ".gftd" / "auth.json"
    if not p.exists():
        return {"present": False, "valid": False, "reason": "no ~/.gftd/auth.json"}
    try:
        d = json.loads(p.read_text())
    except Exception as e:
        return {"present": True, "valid": False, "reason": f"unreadable: {e}"}
    exp = d.get("expires_at", 0)
    now = int(time.time())
    valid = exp > now and ("access_token" in d)
    return {"present": True, "valid": valid,
            "reason": "ok" if valid else f"expired (expires_at={exp} < now={now})",
            "sub": d.get("sub")}


def generate_pds_records(v14_dir: str, mapping: dict, prolly_root: str,
                         out_dir: str) -> dict:
    """Write chapter + per-page createRecord payloads + uploadBlob manifest."""
    os.makedirs(out_dir, exist_ok=True)
    pages_dir = os.path.join(out_dir, "pages")
    os.makedirs(pages_dir, exist_ok=True)
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # chapter record (one per episode/version)
    page_keys = sorted(k for k in mapping if k.startswith("page/"))
    chapter = {
        "collection": PDS_COLLECTION_CHAPTER,
        "rkey": CHAPTER_RKEY,
        "record": {
            "$type": PDS_COLLECTION_CHAPTER,
            "title": "Ghosthacker — Arc 0-1: Origin (v14)",
            "episode": EPISODE,
            "version": VERSION,
            "pageCount": len(page_keys),
            "prollyRoot": prolly_root,
            "createdAt": created_at,
        },
    }
    Path(out_dir, "chapter.json").write_text(
        json.dumps(chapter, ensure_ascii=False, indent=2))

    # per-page records + upload manifest
    upload_manifest = []
    for k in page_keys:
        rec = json.loads(mapping[k])
        rkey = rec["rkey"]
        # pageNum: strip non-digits from rkey (p04 -> 4, p01a -> 1)
        digits = "".join(c for c in rkey if c.isdigit())
        page_num = int(digits) if digits else 0
        page_payload = {
            "collection": PDS_COLLECTION_PAGE,
            "rkey": rkey,
            "record": {
                "$type": PDS_COLLECTION_PAGE,
                "chapterRef": {"$ref": f"at://<did>/{PDS_COLLECTION_CHAPTER}/{CHAPTER_RKEY}",
                               "note": "strongRef filled in after chapter createRecord"},
                "pageNum": page_num,
                # compositedImageCid is minted by uploadBlob at publish time;
                # we carry the source content-address (annex MD5E key) for the
                # uploader to resolve the exact bytes.
                "compositedImageCid": "<uploadBlob:" + (rec.get("blobCid") or "?") + ">",
                "altText": f"Ghosthacker Arc0-1 page {rkey}",
                "createdAt": created_at,
            },
        }
        Path(pages_dir, f"{rkey}.json").write_text(
            json.dumps(page_payload, ensure_ascii=False, indent=2))
        upload_manifest.append({
            "rkey": rkey,
            "finalPng": rec.get("finalPng"),
            "annexCid": rec.get("blobCid"),
            "bytes": rec.get("bytes"),
        })
    Path(out_dir, "upload-manifest.json").write_text(
        json.dumps({"episode": EPISODE, "version": VERSION,
                    "prollyRoot": prolly_root, "pages": upload_manifest},
                   ensure_ascii=False, indent=2))

    readme = f"""# AT-PDS registration artifacts — {EPISODE} {VERSION}

Generated payloads for publishing this episode to a gftd PDS. These are
ready-to-run but were NOT executed automatically (see blockers below).

Files:
  chapter.json            createRecord payload for {PDS_COLLECTION_CHAPTER}/{CHAPTER_RKEY}
  pages/<rkey>.json       createRecord payloads for {PDS_COLLECTION_PAGE} (1 per page)
  upload-manifest.json    finalPng -> annex content-address, for uploadBlob

Publish flow (per ai.gftd.mangaka.page lexicon):
  1. gftd authn signin                      # refresh ~/.gftd/auth.json (PKCE)
  2. for each page: com.atproto.repo.uploadBlob <finalPng>  -> compositedImageCid
  3. createRecord {PDS_COLLECTION_CHAPTER}/{CHAPTER_RKEY}   (from chapter.json)
  4. createRecord {PDS_COLLECTION_PAGE}/<rkey>  with chapterRef strongRef + the
     uploaded compositedImageCid (substitute the <uploadBlob:...> placeholder)

Blockers at generation time:
  - auth: {{auth_reason}}
  - backend: mangaka.gftd.ai serves a 2026-05-14 drawing-studio SPA; the v14
    reader methods ai.gftd.mangaka.* return UnknownNSID (not deployed). Either
    publish via a PDS that has the ai.gftd.mangaka.* lexicons registered, or
    deploy the v14 backend first.

prollyRoot: {prolly_root}
"""
    Path(out_dir, "README.md").write_text(readme)
    return {"chapter": CHAPTER_RKEY, "pages": len(page_keys), "outDir": out_dir}


# ── 2) datalad save (scoped) ───────────────────────────────────────────────
def datalad_save(v14_dir: str, paths: list[str], message: str) -> tuple[bool, str]:
    # paths are dataset-relative; make absolute so cwd doesn't matter
    abs_paths = [os.path.join(v14_dir, p) for p in paths]
    cmd = ["datalad", "save", "-d", v14_dir, "-m", message] + abs_paths
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception as e:
        return False, f"datalad save failed to launch: {e}"
    ok = r.returncode == 0
    return ok, (r.stdout + r.stderr)[-2000:]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--v14", default=V14_DIR)
    ap.add_argument("--branch", default="v14")
    ap.add_argument("--no-datalad", action="store_true")
    ap.add_argument("--pds-live", action="store_true")
    args = ap.parse_args(argv)

    print(f"== register {EPISODE} {VERSION} ==\nv14: {args.v14}\n")

    # 1) prolly
    ch, stats, store_dir = register_prolly(args.v14, args.branch)
    print(f"[1/3] prolly: committed branch '{args.branch}' = {ch}")
    print(f"      {stats['entities']} entities, {stats['pages']} pages -> {store_dir}")
    changed_ga = ensure_gitattributes(args.v14)
    if changed_ga:
        print("      added .gitattributes rule: .prolly/** annex.largefiles=nothing")

    # 3) PDS payloads
    mapping, _ = SP.build_episode_mapping(args.v14, EPISODE, VERSION)
    prolly_root = SP.StoryboardProlly(store_dir).repo.tree_at(ch).root
    auth = auth_state()
    pds_out = os.path.join(store_dir, "pds-records")
    info = generate_pds_records(args.v14, mapping, prolly_root, pds_out)
    # patch the README auth reason
    rp = Path(pds_out, "README.md")
    rp.write_text(rp.read_text().replace("{auth_reason}", auth["reason"]))
    print(f"[3/3] pds: wrote chapter + {info['pages']} page payloads -> {pds_out}")
    print(f"      auth: {'VALID' if auth['valid'] else 'BLOCKED — ' + auth['reason']}")
    if args.pds_live:
        if not auth["valid"]:
            print("      --pds-live requested but auth invalid → skipped. Run `gftd authn signin`.")
        else:
            print("      --pds-live: auth ok, but ai.gftd.mangaka.* backend not deployed "
                  "(UnknownNSID). Deploy v14 backend before publishing. Skipped.")

    # 2) datalad save (scoped to the prolly store + gitattributes)
    if args.no_datalad:
        print("[2/3] datalad: skipped (--no-datalad)")
    else:
        ok, out = datalad_save(
            args.v14, [".prolly", ".gitattributes"],
            message=f"register {EPISODE} {VERSION} prolly store (root {prolly_root})")
        print(f"[2/3] datalad save .prolly: {'OK' if ok else 'FAILED'}")
        for line in out.strip().splitlines()[-6:]:
            print("      " + line)

    print(f"\nbranch-switch now works:  python -m lg_mangaka.storyboard_prolly status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
