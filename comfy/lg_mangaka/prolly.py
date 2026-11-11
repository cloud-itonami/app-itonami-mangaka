"""Content-addressed prolly tree (probabilistic Merkle B-tree) — git-for-data.

A prolly tree is an ordered key→value map whose *shape* is determined by the
content of its keys, not by insertion order (Dolt / Noms / Merkle-Search-Tree
family). Two trees holding the same logical map have the same node hashes and
the same root hash, regardless of how they were built. Consequences:

  - History-independence: the same storyboard set always content-addresses to
    the same root, so equal versions dedup automatically.
  - Structural sharing: editing one entity rewrites only O(log n) nodes; every
    untouched subtree keeps its hash, so it is shared across branches/commits.
  - Cheap diff/merge: comparing two trees skips any subtree whose hash matches,
    so a diff costs O(changed-keys), and 3-way merge resolves at key
    granularity.

This module is storage-agnostic and storyboard-agnostic — it maps
str-key → bytes-value. The StoryboardDB adapter lives in storyboard_prolly.py.

Layout on disk (a ProllyStore root dir, default `<dir>/.prolly`):
  objects/<hash>     content-addressed node + value blobs (immutable)
  refs/heads/<name>  one line: the commit hash a branch points at
  HEAD               one line: the current branch name (or `detached:<hash>`)

Hash = "b2-" + blake2b(blob, digest_size=20).hexdigest()  (40 hex chars).
All serialization is canonical JSON (sorted keys, no spaces, UTF-8) so a given
logical value always produces a single content address.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Iterator, Optional

# Average leaf fan-out target. A key ends a chunk with probability ~1/AVG, so
# nodes hold ~AVG entries on average. 8 keeps trees shallow for the hundreds-to
# -thousands of entities a storyboard set has while still exercising >1 level.
DEFAULT_AVG = 8


# ── canonical serialization + hashing ────────────────────────────────────
def canonical(obj) -> bytes:
    """Deterministic JSON bytes — the only serializer used for addressing."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def hash_bytes(blob: bytes) -> str:
    return "b2-" + hashlib.blake2b(blob, digest_size=20).hexdigest()


# ── object store (content-addressed blobs + refs) ─────────────────────────
class ProllyStore:
    """File-backed content-addressed object store with git-style refs."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.obj_dir = os.path.join(self.root, "objects")
        self.refs_dir = os.path.join(self.root, "refs", "heads")
        os.makedirs(self.obj_dir, exist_ok=True)
        os.makedirs(self.refs_dir, exist_ok=True)
        self._cache: dict[str, bytes] = {}

    # objects ---------------------------------------------------------------
    def put(self, blob: bytes) -> str:
        """Write a blob, return its hash. No-op if already present (dedup)."""
        h = hash_bytes(blob)
        self._cache[h] = blob
        path = self._obj_path(h)
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(blob)
            os.replace(tmp, path)
        return h

    def get(self, h: str) -> bytes:
        if h in self._cache:
            return self._cache[h]
        with open(self._obj_path(h), "rb") as f:
            blob = f.read()
        self._cache[h] = blob
        return blob

    def has(self, h: str) -> bool:
        return h in self._cache or os.path.exists(self._obj_path(h))

    def _obj_path(self, h: str) -> str:
        # fan out by 2 hex chars after the "b2-" prefix to avoid huge dirs
        body = h[3:]
        return os.path.join(self.obj_dir, body[:2], body)

    # refs ------------------------------------------------------------------
    def set_ref(self, branch: str, commit_hash: str) -> None:
        path = os.path.join(self.refs_dir, branch)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(commit_hash + "\n")

    def get_ref(self, branch: str) -> Optional[str]:
        path = os.path.join(self.refs_dir, branch)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return f.read().strip() or None

    def list_refs(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if not os.path.isdir(self.refs_dir):
            return out
        for dirpath, _, files in os.walk(self.refs_dir):
            for fn in files:
                full = os.path.join(dirpath, fn)
                name = os.path.relpath(full, self.refs_dir)
                with open(full) as f:
                    val = f.read().strip()
                if val:
                    out[name] = val
        return out

    def delete_ref(self, branch: str) -> None:
        path = os.path.join(self.refs_dir, branch)
        if os.path.exists(path):
            os.remove(path)

    # HEAD ------------------------------------------------------------------
    def set_head(self, value: str) -> None:
        with open(os.path.join(self.root, "HEAD"), "w") as f:
            f.write(value + "\n")

    def get_head(self) -> Optional[str]:
        path = os.path.join(self.root, "HEAD")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return f.read().strip() or None


# ── prolly tree node ──────────────────────────────────────────────────────
@dataclass
class _Node:
    level: int                       # 0 = leaf
    entries: list[tuple[str, str]]   # sorted (key, ref) — ref = value/child hash

    def to_blob(self) -> bytes:
        return canonical({"level": self.level,
                          "entries": [[k, r] for k, r in self.entries]})


def _is_boundary(key: str, level: int, avg: int) -> bool:
    """Probabilistic chunk boundary — depends only on key + level.

    Because the decision ignores the value, changing a value never moves a
    boundary: only the leaf containing it (and its ancestors) get rehashed.
    Salting by level guarantees higher levels chunk differently from lower
    ones, so the tree strictly shrinks and the build terminates.
    """
    h = hashlib.blake2b(f"{level}\x00{key}".encode("utf-8"), digest_size=8)
    return int.from_bytes(h.digest(), "big") % avg == 0


def _build(store: ProllyStore, items: list[tuple[str, str]],
           level: int, avg: int) -> str:
    """Chunk sorted (key, ref) entries into nodes; recurse up to a single root."""
    chunks: list[list[tuple[str, str]]] = []
    cur: list[tuple[str, str]] = []
    for k, r in items:
        cur.append((k, r))
        if _is_boundary(k, level, avg):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)

    node_refs: list[tuple[str, str]] = []   # (first_key, node_hash) per chunk
    for chunk in chunks:
        node = _Node(level, chunk)
        h = store.put(node.to_blob())
        node_refs.append((chunk[0][0], h))

    if len(node_refs) == 1:
        return node_refs[0][1]
    return _build(store, node_refs, level + 1, avg)


class ProllyTree:
    """An immutable content-addressed ordered map. `root` is its hash (or None
    for the empty map). Mutations return a NEW root via build_from_dict."""

    def __init__(self, store: ProllyStore, root: Optional[str], avg: int = DEFAULT_AVG):
        self.store = store
        self.root = root
        self.avg = avg

    # construction ----------------------------------------------------------
    @classmethod
    def build_from_dict(cls, store: ProllyStore, mapping: dict[str, bytes],
                        avg: int = DEFAULT_AVG) -> "ProllyTree":
        """Build a tree from key→value-bytes. Values are stored as blobs and
        referenced by hash, so identical values dedup across keys/branches."""
        if not mapping:
            return cls(store, None, avg)
        items = []
        for k in sorted(mapping.keys()):
            vref = store.put(mapping[k])
            items.append((k, vref))
        root = _build(store, items, 0, avg)
        return cls(store, root, avg)

    # reads -----------------------------------------------------------------
    def _load(self, h: str) -> _Node:
        d = json.loads(self.store.get(h))
        return _Node(d["level"], [(k, r) for k, r in d["entries"]])

    def items(self) -> Iterator[tuple[str, bytes]]:
        """Yield (key, value-bytes) in sorted key order."""
        if self.root is None:
            return
        yield from self._walk(self.root)

    def _walk(self, h: str) -> Iterator[tuple[str, bytes]]:
        node = self._load(h)
        if node.level == 0:
            for k, vref in node.entries:
                yield k, self.store.get(vref)
        else:
            for _k, child in node.entries:
                yield from self._walk(child)

    def to_dict(self) -> dict[str, bytes]:
        return {k: v for k, v in self.items()}

    def get(self, key: str) -> Optional[bytes]:
        if self.root is None:
            return None
        h = self.root
        while True:
            node = self._load(h)
            if node.level == 0:
                for k, vref in node.entries:
                    if k == key:
                        return self.store.get(vref)
                return None
            # descend into the last child whose first_key <= key
            child = None
            for fk, c in node.entries:
                if fk <= key:
                    child = c
                else:
                    break
            if child is None:
                return None
            h = child

    # diff ------------------------------------------------------------------
    def diff(self, other: "ProllyTree") -> dict[str, list]:
        """Structural diff self→other. Returns {added, removed, changed} where
        each is a list of keys. Subtrees with equal hashes are skipped wholesale.
        """
        added: list[str] = []
        removed: list[str] = []
        changed: list[str] = []
        self._diff_nodes(self.root, other.root, other, added, removed, changed)
        return {"added": sorted(added), "removed": sorted(removed),
                "changed": sorted(changed)}

    def _leaf_map(self, h: Optional[str]) -> dict[str, str]:
        """Flatten a subtree to {key: value_ref}."""
        out: dict[str, str] = {}
        if h is None:
            return out
        node = self._load(h)
        if node.level == 0:
            for k, vref in node.entries:
                out[k] = vref
        else:
            for _k, child in node.entries:
                out.update(self._leaf_map(child))
        return out

    def _diff_nodes(self, a: Optional[str], b: Optional[str], other: "ProllyTree",
                    added: list, removed: list, changed: list) -> None:
        if a == b:
            return                       # identical subtree → nothing changed
        amap = self._leaf_map(a)
        bmap = other._leaf_map(b)
        for k, vref in bmap.items():
            if k not in amap:
                added.append(k)
            elif amap[k] != vref:
                changed.append(k)
        for k in amap:
            if k not in bmap:
                removed.append(k)

    # 3-way merge -----------------------------------------------------------
    def three_way_merge(self, base: "ProllyTree", other: "ProllyTree"
                        ) -> tuple["ProllyTree", list[str]]:
        """Merge `other` into `self` relative to common ancestor `base`.

        Returns (merged_tree, conflicts). A conflict is a key both sides changed
        to different values; on conflict, `self` (ours) wins and the key is
        reported. Non-conflicting changes from both sides are applied.
        """
        base_map = {k: hash_bytes(v) for k, v in base.items()}
        ours = self.to_dict()
        theirs = other.to_dict()
        ours_h = {k: hash_bytes(v) for k, v in ours.items()}
        theirs_h = {k: hash_bytes(v) for k, v in theirs.items()}

        merged: dict[str, bytes] = dict(ours)
        conflicts: list[str] = []
        all_keys = set(base_map) | set(ours_h) | set(theirs_h)
        for k in all_keys:
            b = base_map.get(k)
            o = ours_h.get(k)
            t = theirs_h.get(k)
            ours_changed = o != b
            theirs_changed = t != b
            if not theirs_changed:
                continue                 # only we (maybe) touched it → keep ours
            if not ours_changed:
                # only they changed → take theirs (add/modify/delete)
                if t is None:
                    merged.pop(k, None)
                else:
                    merged[k] = theirs[k]
            else:
                # both changed
                if o == t:
                    continue             # same result → no conflict
                conflicts.append(k)      # divergent → ours wins
        out = ProllyTree.build_from_dict(self.store, merged, self.avg)
        return out, sorted(conflicts)


# ── commits + branch operations ───────────────────────────────────────────
@dataclass
class Commit:
    tree: Optional[str]
    parents: list[str]
    note: str
    ts: float
    meta: dict

    def to_blob(self) -> bytes:
        return canonical({"tree": self.tree, "parents": self.parents,
                          "note": self.note, "ts": self.ts, "meta": self.meta,
                          "$type": "prolly.commit"})


class ProllyRepo:
    """Branch/commit layer over a ProllyStore — the git-like front door."""

    def __init__(self, root: str, avg: int = DEFAULT_AVG):
        self.store = ProllyStore(root)
        self.avg = avg

    # branches --------------------------------------------------------------
    def current_branch(self) -> Optional[str]:
        head = self.store.get_head()
        if head and not head.startswith("detached:"):
            return head
        return None

    def branches(self) -> dict[str, str]:
        return self.store.list_refs()

    def head_commit(self) -> Optional[str]:
        head = self.store.get_head()
        if head is None:
            return None
        if head.startswith("detached:"):
            return head.split(":", 1)[1]
        return self.store.get_ref(head)

    def create_branch(self, name: str, from_commit: Optional[str] = None) -> None:
        start = from_commit if from_commit is not None else self.head_commit()
        if start is None:
            raise ValueError("nothing to branch from (no commits yet)")
        if self.store.get_ref(name) is not None:
            raise ValueError(f"branch already exists: {name}")
        self.store.set_ref(name, start)

    def switch(self, name: str) -> None:
        if self.store.get_ref(name) is None:
            raise ValueError(f"no such branch: {name}")
        self.store.set_head(name)

    def delete_branch(self, name: str) -> None:
        if self.current_branch() == name:
            raise ValueError(f"cannot delete current branch: {name}")
        self.store.delete_ref(name)

    # commits ---------------------------------------------------------------
    def read_commit(self, commit_hash: str) -> Commit:
        d = json.loads(self.store.get(commit_hash))
        return Commit(d["tree"], d["parents"], d["note"], d["ts"], d["meta"])

    def tree_at(self, commit_hash: Optional[str]) -> ProllyTree:
        if commit_hash is None:
            return ProllyTree(self.store, None, self.avg)
        return ProllyTree(self.store, self.read_commit(commit_hash).tree, self.avg)

    def commit(self, mapping: dict[str, bytes], note: str, ts: float,
               branch: Optional[str] = None, meta: Optional[dict] = None,
               extra_parents: Optional[list[str]] = None) -> str:
        """Build a tree from `mapping`, write a commit, advance the branch ref.

        ts must be supplied by the caller (workflow scripts forbid wall-clock);
        pass time.time() from a normal CLI/script context.
        """
        branch = branch or self.current_branch() or "main"
        tree = ProllyTree.build_from_dict(self.store, mapping, self.avg)
        parents: list[str] = []
        cur = self.store.get_ref(branch)
        if cur:
            parents.append(cur)
        if extra_parents:
            parents.extend(extra_parents)
        commit = Commit(tree.root, parents, note, ts, meta or {})
        ch = self.store.put(commit.to_blob())
        self.store.set_ref(branch, ch)
        if self.current_branch() is None:
            self.store.set_head(branch)
        return ch

    def log(self, branch: Optional[str] = None, limit: int = 50) -> list[tuple[str, Commit]]:
        start = self.store.get_ref(branch) if branch else self.head_commit()
        out: list[tuple[str, Commit]] = []
        seen: set[str] = set()
        frontier = [start] if start else []
        while frontier and len(out) < limit:
            h = frontier.pop(0)
            if h is None or h in seen:
                continue
            seen.add(h)
            c = self.read_commit(h)
            out.append((h, c))
            frontier.extend(c.parents)
        return out

    def merge_base(self, a: str, b: str) -> Optional[str]:
        """Lowest common ancestor of two commits (BFS ancestor-set intersect)."""
        def ancestors(start: str) -> set[str]:
            seen, stack = set(), [start]
            while stack:
                h = stack.pop()
                if h in seen:
                    continue
                seen.add(h)
                stack.extend(self.read_commit(h).parents)
            return seen
        anc_a = ancestors(a)
        # walk b's history; first commit also in anc_a is a common ancestor.
        seen, frontier = set(), [b]
        while frontier:
            h = frontier.pop(0)
            if h in seen:
                continue
            seen.add(h)
            if h in anc_a:
                return h
            frontier.extend(self.read_commit(h).parents)
        return None

    def merge(self, other_branch: str, ts: float,
              into: Optional[str] = None, note: Optional[str] = None
              ) -> tuple[str, list[str]]:
        """3-way merge other_branch into `into` (default current). Returns
        (merge_commit_hash, conflicts). Records both parents."""
        into = into or self.current_branch()
        if into is None:
            raise ValueError("no target branch to merge into")
        ours_c = self.store.get_ref(into)
        theirs_c = self.store.get_ref(other_branch)
        if theirs_c is None:
            raise ValueError(f"no such branch: {other_branch}")
        if ours_c is None:
            raise ValueError(f"target branch has no commits: {into}")
        if ours_c == theirs_c:
            return ours_c, []
        base_c = self.merge_base(ours_c, theirs_c)
        ours_t = self.tree_at(ours_c)
        theirs_t = self.tree_at(theirs_c)
        base_t = self.tree_at(base_c)
        merged_t, conflicts = ours_t.three_way_merge(base_t, theirs_t)
        commit = Commit(merged_t.root, [ours_c, theirs_c],
                        note or f"merge {other_branch} into {into}", ts,
                        {"conflicts": conflicts})
        ch = self.store.put(commit.to_blob())
        self.store.set_ref(into, ch)
        return ch, conflicts
