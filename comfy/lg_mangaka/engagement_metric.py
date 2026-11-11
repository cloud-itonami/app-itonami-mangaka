"""Reaction-based fitness — the real-user yardstick for manga quality.

Replaces synthetic offline scores (gemma4 quality, CLIP consistency) as the
*ground truth* once a published work has accrued real engagement on a configured
social feed (ADR-2606181200). The synthetic scores remain the fast offline
pre-filter and cold-start prior; this is the slow online signal that overrides
the tournament once trustworthy.

Design choices (per user + ADR):
  - Normalise by EXPOSURE, not raw counts — a low-exposure work must not be
    unfairly beaten by a high-exposure one. We use the **Wilson lower bound** on
    the engagement rate (successes/impressions), which shrinks toward 0 when the
    sample is small, so a 2/3 with tiny n ranks below a 200/400 with large n.
  - Weight by **propagation**: reposts (spread) > replies (discussion) > likes.
  - Optional **influence weighting** (mv_weighted_in_degree): engagement from
    high-out-degree accounts counts more. Default 1.0 (author-level neutral)
    until per-liker influence is joined in.

Pure math is unit-tested; the network fetch degrades to {} offline so CI and
disconnected runs are unaffected.
"""
from __future__ import annotations

import math
import os

W_LIKE = 1.0
W_REPOST = 2.0   # a repost propagates the work → weigh highest
W_REPLY = 1.5
MIN_IMPRESSIONS = 30   # below this the rate is too noisy to trust as ground truth


def wilson_lower_bound(successes: float, trials: float, z: float = 1.96) -> float:
    """Lower bound of the Wilson score interval for a proportion, in [0,1].

    Penalises small samples: 1/1 → ~0.21, 100/100 → ~0.96. This is what stops a
    fluke 3-likes-on-4-views recipe from out-ranking a steadily-liked one."""
    if trials <= 0:
        return 0.0
    phat = max(0.0, min(1.0, successes / trials))
    z2 = z * z
    denom = 1.0 + z2 / trials
    center = phat + z2 / (2.0 * trials)
    margin = z * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * trials)) / trials)
    return max(0.0, (center - margin) / denom)


def engagement_weighted(likes: float = 0, reposts: float = 0, replies: float = 0) -> float:
    return W_LIKE * likes + W_REPOST * reposts + W_REPLY * replies


def _influence_norm(influence: float) -> float:
    # influence is a multiplier ~1.0 (1.0 = average account). Clamp so a single
    # whale or a dead account can't dominate / zero the signal.
    try:
        return max(0.5, min(2.0, float(influence)))
    except (TypeError, ValueError):
        return 1.0


def reaction_fitness(*, likes: float = 0, reposts: float = 0, replies: float = 0,
                     impressions: float | None = None, influence: float = 1.0) -> float | None:
    """Reaction fitness 0-100, or None when there is no usable signal yet.

    - impressions known (>0): Wilson lower bound of weighted-engagement rate.
    - impressions unknown but some engagement: log-shrunk count (saturating), so
      the signal is usable before view tracking lands, just coarser.
    - nothing at all: None (caller keeps the synthetic score)."""
    eng = engagement_weighted(likes, reposts, replies)
    if impressions is not None and impressions > 0:
        succ = min(eng, impressions)          # weighted eng can exceed views; cap
        base = wilson_lower_bound(succ, impressions)   # 0..1
    elif eng > 0:
        base = 1.0 - 1.0 / (1.0 + math.log1p(eng))     # 0..1, saturating
    else:
        return None
    return round(min(100.0, 100.0 * base * _influence_norm(influence)), 1)


def is_reaction_trustworthy(impressions: float | None, engagement: float = 0.0,
                            min_impressions: float = MIN_IMPRESSIONS) -> bool:
    """Gate before the online signal is allowed to OVERRIDE the synthetic score:
    enough exposure to be ground truth, not a cold-start fluke."""
    if impressions is not None:
        return impressions >= min_impressions
    return engagement >= min_impressions   # no view tracking → require raw volume


# ── thin yoro AppView client (graceful: returns {} on any failure) ───────────

_LIKE_C = "app.bsky.feed.like"
_REPOST_C = "app.bsky.feed.repost"
_POST_C = "app.bsky.feed.post"


def merge_recordlog_rows(uris: list[str], reaction_rows: list[dict] | None,
                         reply_rows: list[dict] | None) -> dict:
    """Pure: fold recordlog GROUP-BY rows into {uri: {likes,reposts,replies,views}}.
    `reaction_rows` are like/repost rows ({p, collection, n}); `reply_rows` are
    reply-post rows ({p, n}). views is None (no impression tracking in the log)."""
    out = {u: {"likes": 0, "reposts": 0, "replies": 0, "views": None} for u in uris}
    for row in reaction_rows or []:
        p = row.get("p")
        if p not in out:
            continue
        n = max(0, int(row.get("n") or 0))   # net create-delete; clamp (can't be <0)
        if row.get("collection") == _LIKE_C:
            out[p]["likes"] += n
        elif row.get("collection") == _REPOST_C:
            out[p]["reposts"] += n
    for row in reply_rows or []:
        p = row.get("p")
        if p in out:
            out[p]["replies"] += max(0, int(row.get("n") or 0))
    return out


_NET = "SUM(CASE action WHEN 'create' THEN 1 WHEN 'delete' THEN -1 ELSE 0 END)"


async def fetch_engagement_recordlog(post_uris: list[str], *, writer_url: str = "",
                                     secret: str = "", timeout: float = 30.0) -> dict:
    """Count likes/reposts/replies per post URI straight from the PDS commit log
    D1 (`vertex_repo_commit` via the `recordlog_query` op). RW-independent — the
    yoro AppView feed degraded after RW was decommissioned, so this is the durable
    read path. Returns {uri: {likes,reposts,replies,views=None}}; {} on missing
    config or any error.

    Reads `vertex_repo_commit` (not the posts-only `vertex_repo_record` mirror):
    it is append-only and captures ALL federated collections — like/repost/follow
    included — so engagement is netted as creates minus deletes (an unlike/unrepost
    is a `delete` commit). bsky social records are stored flat, so the subject is
    at `$.subject.uri` (like/repost) and `$.reply.parent.uri` (reply)."""
    writer_url = writer_url or os.environ.get("SHINSHI_D1_WRITER_URL", "")
    secret = (secret or os.environ.get("SHINSHI_D1_WRITER_SECRET")
              or os.environ.get("DISPATCHER_INTERNAL_SECRET") or "")
    uris = [u for u in (post_uris or []) if u]
    if not uris or not writer_url or not secret:
        return {}
    ph = ",".join("?" * len(uris))
    # json_valid() guards malformed value_json (some legacy/domain rows aren't
    # valid JSON) — without it one bad row fails the whole json_extract scan.
    reaction_sql = (
        f"SELECT json_extract(value_json,'$.subject.uri') AS p, collection, {_NET} AS n "
        f"FROM vertex_repo_commit WHERE collection IN ('{_LIKE_C}','{_REPOST_C}') "
        f"AND json_valid(value_json) "
        f"AND json_extract(value_json,'$.subject.uri') IN ({ph}) GROUP BY p, collection")
    reply_sql = (
        f"SELECT json_extract(value_json,'$.reply.parent.uri') AS p, {_NET} AS n "
        f"FROM vertex_repo_commit WHERE collection='{_POST_C}' AND json_valid(value_json) "
        f"AND json_extract(value_json,'$.reply.parent.uri') IN ({ph}) GROUP BY p")
    try:
        import httpx
        url = writer_url.rstrip("/")
        headers = {"x-internal-trust": secret, "content-type": "application/json"}
        async with httpx.AsyncClient(timeout=timeout) as c:
            async def _rows(sql: str) -> list[dict]:
                # each query is independent: a failure yields [] (zeros), not a
                # void result that would mask the others.
                try:
                    r = await c.post(url, json={"op": "recordlog_query", "sql": sql, "params": uris},
                                     headers=headers)
                    r.raise_for_status()
                    d = r.json()
                    return (d.get("rows") or []) if d.get("ok") else []
                except Exception:  # noqa: BLE001
                    return []
            reaction_rows = await _rows(reaction_sql)
            reply_rows = await _rows(reply_sql)
        return merge_recordlog_rows(uris, reaction_rows, reply_rows)
    except Exception:  # noqa: BLE001
        return {}


async def fetch_author_engagement(actor: str, *, base_url: str = "",
                                  limit: int = 100, timeout: float = 20.0) -> dict:
    """Pull an author's posts with engagement counts via
    ai.gftd.yoro.feed.getAuthorFeed → {post_uri: {likes,reposts,replies,views,indexedAt}}.

    Any error (offline, auth, MV down) → {} so the loop simply keeps the
    synthetic ranking. No exceptions escape."""
    if not actor or not base_url:
        return {}
    url = base_url.rstrip("/") + "/xrpc/ai.gftd.yoro.feed.getAuthorFeed"
    try:
        import httpx
        out: dict = {}
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(url, params={"actor": actor, "limit": limit})
            r.raise_for_status()
            for item in (r.json().get("feed") or []):
                post = item.get("post") or {}
                uri = post.get("uri")
                if not uri:
                    continue
                out[uri] = {
                    "likes": post.get("likeCount") or 0,
                    "reposts": post.get("repostCount") or 0,
                    "replies": post.get("replyCount") or 0,
                    "views": post.get("viewCount"),
                    "indexedAt": post.get("indexedAt"),
                }
        return out
    except Exception:  # noqa: BLE001
        return {}
