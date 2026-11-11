"""Co-Scientist manga-panel quality loop (LangGraph).

Maps Google's AI Co-Scientist (generate → reflect → rank/tournament → evolve →
meta-review, iterated by a supervisor) onto manga-panel rendering quality:

  hypothesis  = a render RECIPE (style tags, negative, cfg, steps, sampler, extra prompt)
  experiment  = render the panel with that recipe on ComfyUI (gad, via Tailscale)
  fitness     = visual score from a gemma4 vision critic (Tailscale)
  reflection  = the critic's per-axis notes
  ranking     = absolute score + pairwise vision "debate" Elo among the leaders
  evolution   = an LLM mutates/crossbreeds the top recipes using the meta-review
  meta-review = an LLM distills "what makes high scorers win" → fed back to generation

Endpoints resolve through `llm_endpoint` (SSoT): ComfyUI via COMFY_HOST, the
text+vision LLM via the OpenAI-compatible chat endpoint. Runs entirely on the
Tailscale fleet — no RunPod.

CLI:
  python -m lg_mangaka.coscientist_quality \
      --generations 3 --candidates 4 \
      --subject "lone teenage hacker at a glowing console, dramatic rim light, close-up"
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import secrets
from typing import Annotated, Any, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph

from lg_mangaka import comfy_runner as _runner
from lg_mangaka import llm_endpoint as _ep

CKPT = os.environ.get("COMFY_DEFAULT_CKPT", "animagine-xl-4.0.safetensors")
COMFY_URL = os.environ.get("COMFY_HOST") or _runner.DEFAULT_URL

# Reaction (online) fitness — real engagement from an explicitly configured social appview is
# the GROUND TRUTH that overrides the synthetic ranking once trustworthy
# (ADR-2606181200). Off unless a manga author DID/handle is configured.
_REACTION_ACTOR = os.environ.get("MANGAKA_REACTION_ACTOR", "")
_YORO_URL = os.environ.get("YORO_APPVIEW_URL", "")

# Vision/text LLM (gemma4) via Ollama's NATIVE /api/chat. The OpenAI-compat
# /v1 path leaves `content` empty on gemma4 thinking models (the CoT goes to a
# separate `reasoning` field); native /api/chat with think=false returns clean
# content. Images ride on message.images (base64) in native format.
_LLM_BASE = (os.environ.get("OLLAMA_HOST") or _ep.base_url()).rstrip("/")
_HOST = _LLM_BASE[:-3].rstrip("/") if _LLM_BASE.endswith("/v1") else _LLM_BASE
_NATIVE_CHAT = _HOST + "/api/chat"
_LLM_MODEL = os.environ.get("OLLAMA_MODEL") or _ep.vision_model()


# ── LLM helpers (Ollama native /api/chat, thinking disabled) ─────────────────

async def _chat(messages: list[dict], *, max_tokens: int = 800, temperature: float = 0.7) -> str:
    payload = {"model": _LLM_MODEL, "messages": messages, "think": False, "stream": False,
               "options": {"num_predict": max_tokens, "temperature": temperature}}
    async with httpx.AsyncClient(timeout=240.0) as c:
        r = await c.post(_NATIVE_CHAT, json=payload, headers=_ep.auth_headers())
        r.raise_for_status()
        return (r.json().get("message") or {}).get("content") or ""


def _loads(text: str) -> Any:
    import re
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    s = (m.group(1) if m else text).strip()
    i, j = s.find("["), s.rfind("]")
    if i < 0: i, j = s.find("{"), s.rfind("}")
    try:
        return json.loads(s[i:j + 1])
    except Exception:
        return None


async def _vision_score(prompt: str, image_b64: str) -> dict:
    """gemma4 vision critic → {score 0-100, axes{}, notes}."""
    payload = {"model": _LLM_MODEL, "think": False, "stream": False,
               "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
               "options": {"num_predict": 500, "temperature": 0.2}}
    try:
        async with httpx.AsyncClient(timeout=300.0) as c:
            r = await c.post(_NATIVE_CHAT, json=payload, headers=_ep.auth_headers())
            r.raise_for_status()
            txt = (r.json().get("message") or {}).get("content") or "{}"
        d = _loads(txt) or {}
        return {"score": float(d.get("score") or 0), "axes": d.get("axes") or {}, "notes": str(d.get("notes") or "")}
    except Exception as e:  # noqa: BLE001
        return {"score": 0.0, "axes": {}, "notes": f"score-fail: {e}"}


_RUBRIC = (
    "You are a strict Weekly-Shonen-Jump art director. Score this manga panel 0-100 overall, "
    "and per axis 0-10: line_quality, tonal_balance, composition, character_anatomy, "
    "reading_clarity, mood_match. Respond with VALID JSON only: "
    '{"score":<0-100>,"axes":{"line_quality":n,...},"notes":"<1 sentence, strongest weakness>"}'
)


# ── render ──────────────────────────────────────────────────────────────────

def _workflow(positive: str, negative: str, cfg: float, steps: int, sampler: str) -> dict:
    seed = secrets.randbelow(2**32)
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 832, "height": 1216, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": int(steps), "cfg": float(cfg),
            "sampler_name": sampler, "scheduler": "karras", "denoise": 1.0,
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0]}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "coscientist", "images": ["6", 0]}},
    }


async def _render(recipe: dict, subject: str) -> str | None:
    positive = ", ".join(p for p in [
        recipe.get("style_tags", ""), subject, recipe.get("extra_prompt", ""),
        "manga panel, monochrome, sharp ink lines",
    ] if p)
    wf = _workflow(positive, recipe.get("negative", "low quality, bad anatomy, bad hands"),
                   float(recipe.get("cfg", 7.0)), int(recipe.get("steps", 26)),
                   recipe.get("sampler", "dpmpp_2m_sde"))
    sub = await _runner.submit_workflow(wf, comfy_url=COMFY_URL)
    if sub.get("status") == "error":
        return None
    poll = await _runner.poll_outputs(sub["prompt_id"], comfy_url=COMFY_URL,
                                      started_at_ms=sub.get("started_at_ms", 0), timeout_seconds=300)
    imgs = poll.get("images") or []
    return (imgs[-1].get("imageInlineB64") if imgs else None)


# ── graph state ─────────────────────────────────────────────────────────────

def _keep_last(a, b):
    return b if b is not None else a


# ── saturation / plateau guards (meta watches the PROCESS, not just candidates) ─
# A flat fitness landscape across generations is ambiguous: either the search
# converged, or the metric lost resolution (the gemma4 failure). Combined with
# the in-generation spread, a plateau + near-zero spread is the tell-tale of a
# saturated metric — meta flags it so generation distrusts the fitness.
_PLATEAU_EPS = 1.0      # best-score must move at least this much to count as progress
_PLATEAU_WINDOW = 3     # generations to look back over
_SPREAD_MIN = 3.0       # min spread among a generation's scores for a "live" signal


def _score_spread(scores: list[float]) -> float:
    return (max(scores) - min(scores)) if scores else 0.0


def _is_plateau(best_scores: list[float], eps: float = _PLATEAU_EPS,
                window: int = _PLATEAU_WINDOW) -> bool:
    """True iff the best score hasn't moved by > eps over the last `window` gens."""
    if len(best_scores) < window:
        return False
    recent = best_scores[-window:]
    return (max(recent) - min(recent)) < eps


class _S(TypedDict, total=False):
    subject: str
    shots: list       # extra framings per candidate -> cross-panel consistency (MangaFlow, ADR-2606171200)
    n_candidates: int
    n_generations: int
    gen_idx: int
    meta_notes: str
    hypotheses: list  # current generation recipes
    scored: list      # [{recipe, image_b64, score, axes, notes}]
    archive: Annotated[list, lambda a, b: (a or []) + (b or [])]
    best: dict
    trajectory: Annotated[list, lambda a, b: (a or []) + (b or [])]
    control_b64: Annotated[str, _keep_last]              # off-subject negative control (rendered once)
    metric_health: Annotated[list, lambda a, b: (a or []) + (b or [])]  # per-gen discrimination probe
    saturated: bool   # set when plateau+low-spread or a degraded metric is detected
    reaction_overrides: Annotated[list, lambda a, b: (a or []) + (b or [])]  # synthetic→reaction overrides


GEN_SYS = (
    "You are the Generation agent in an AI Co-Scientist loop improving manga-panel "
    "render recipes for an SDXL (animagine) model. Propose DIVERSE recipes. Each recipe JSON: "
    '{"id":"g0-1","style_tags":"danbooru/style anchor tags","extra_prompt":"composition/lighting directives",'
    '"negative":"negative prompt","cfg":<5.0-8.0>,"steps":<22-32>,"sampler":"dpmpp_2m_sde|euler|dpmpp_3m_sde_gpu"}. '
    "Return a JSON array only."
)


async def _node_generate(state: _S) -> dict:
    gi = state.get("gen_idx", 0)
    n = state.get("n_candidates", 4)
    subject = state["subject"]
    if gi == 0:
        user = (f"Subject panel: {subject}\nPropose {n} diverse manga-ink render recipes "
                f"(varied style anchors, negatives, cfg/steps/sampler). JSON array of {n}.")
        out = _loads(await _chat([{"role": "system", "content": GEN_SYS}, {"role": "user", "content": user}],
                                 max_tokens=1200, temperature=0.9))
    else:
        # EVOLUTION: mutate/crossbreed top recipes using meta-review.
        top = sorted(state.get("archive", []), key=lambda x: x["score"], reverse=True)[:3]
        top_brief = [{"recipe": t["recipe"], "score": t["score"], "notes": t.get("notes", "")} for t in top]
        user = (f"Subject panel: {subject}\nMeta-review of what wins: {state.get('meta_notes','')}\n"
                f"Top recipes so far (with scores): {json.dumps(top_brief, ensure_ascii=False)[:1500]}\n"
                f"EVOLVE: produce {n} improved recipes (mutate winners, crossbreed, fix the weaknesses in notes). "
                f"JSON array of {n}, ids prefixed g{gi}-.")
        out = _loads(await _chat([{"role": "system", "content": GEN_SYS}, {"role": "user", "content": user}],
                                 max_tokens=1200, temperature=0.85))
    recipes = out if isinstance(out, list) else []
    # fallback recipe so the loop never stalls
    if not recipes:
        recipes = [{"id": f"g{gi}-fallback", "style_tags": "masterpiece, best quality, manga, monochrome",
                    "extra_prompt": "dramatic lighting", "negative": "low quality, bad hands",
                    "cfg": 7.0, "steps": 26, "sampler": "dpmpp_2m_sde"}]
    return {"hypotheses": recipes[:n]}


async def _consistency_score(images_b64: list[str]) -> float | None:
    """Cross-panel consistency via CLIP image-embedding cosine (None if <2).

    Replaces the earlier gemma4 vision rating, which saturated ~95-98 and could
    not discriminate (ADR-2606171200 experiment). CLIP gives a continuous,
    discriminating signal (same character/style ~70-76, different ~32-41) and is
    CPU-bound, so run it off the event loop.
    """
    if len(images_b64) < 2:
        return None
    try:
        from lg_mangaka import consistency_metric as _cm
        return await asyncio.to_thread(_cm.consistency_b64, images_b64)
    except Exception:  # noqa: BLE001
        return None


def _blend_fitness(quality: float, consistency: float | None) -> float:
    """Fitness = quality alone, or 0.65*quality + 0.35*consistency when a
    cross-panel consistency score is available (ADR-2606171200)."""
    if consistency is None:
        return round(quality, 1)
    return round(0.65 * quality + 0.35 * consistency, 1)


_CONTROL_SUBJECT = "an empty wooden ramen bowl on a plain table, still life, no people"


async def _node_experiment(state: _S) -> dict:
    """Render each hypothesis across the configured shots, vision-score quality,
    and (when >1 shot) score cross-panel character consistency; blend into fitness.

    Also runs a NEGATIVE-CONTROL discrimination probe on the consistency metric:
    a 'good' pair (same character across shots, should be high) vs a 'bad' pair
    (that character vs a totally different subject, should be low). If the metric
    can't separate them the loop is optimising a broken signal (the gemma4
    failure) — meta flags `saturated` (ADR-2606171200)."""
    subject = state["subject"]
    shots = state.get("shots") or [""]
    scored = []
    for rec in state.get("hypotheses", []):
        imgs = []
        for shot in shots:
            subj = f"{subject}, {shot}" if shot else subject
            img = await _render(rec, subj)
            if img:
                imgs.append(img)
        if not imgs:
            continue
        qs = [(await _vision_score(_RUBRIC, im))["score"] for im in imgs]
        quality = sum(qs) / len(qs)
        consistency = await _consistency_score(imgs)
        fitness = _blend_fitness(quality, consistency)
        last = await _vision_score(_RUBRIC, imgs[0])  # keep per-axis notes for meta
        scored.append({"recipe": rec, "image_b64": imgs[0], "images": imgs,
                       "score": fitness, "quality": round(quality, 1),
                       "consistency": consistency, "axes": last["axes"], "notes": last["notes"]})

    out: dict = {"scored": scored, "archive": scored}

    # Metric-health probe — only meaningful with multi-shot consistency scoring.
    if len(shots) > 1 and scored:
        from lg_mangaka import consistency_metric as _cm
        control = state.get("control_b64")
        if not control:  # render the off-subject control ONCE, reuse across gens
            control = await _render({"cfg": 7.0, "steps": 24, "sampler": "dpmpp_2m_sde"},
                                    _CONTROL_SUBJECT)
            if control:
                out["control_b64"] = control
        cand = max(scored, key=lambda s: s.get("quality", 0))
        good = cand.get("consistency")                         # same char across shots → expect high
        bad = (await _consistency_score([cand["images"][0], control])
               if control and cand.get("images") else None)   # char vs ramen → expect low
        sep = _cm.metric_separation(good, bad)
        ok = _cm.is_discriminating(good, bad)
        out["metric_health"] = [{"gen": state.get("gen_idx", 0), "good": good,
                                 "bad": bad, "separation": sep, "ok": ok}]

    return out


def _aggregate_engagement(idx: dict, post_uris: list[str]) -> dict | None:
    """Sum engagement across every published post of one style fingerprint."""
    rows = [idx[u] for u in post_uris if u in idx]
    if not rows:
        return None
    views = [r.get("views") for r in rows if r.get("views") is not None]
    return {"likes": sum(r.get("likes") or 0 for r in rows),
            "reposts": sum(r.get("reposts") or 0 for r in rows),
            "replies": sum(r.get("replies") or 0 for r in rows),
            "impressions": (sum(views) if views else None),
            "posts": len(rows)}


async def _node_online_review(state: _S) -> dict:
    """Two-layer fitness (ADR-2606181200): the synthetic gemma4+CLIP score is the
    fast offline pre-filter / cold-start prior; once a recipe's STYLE FINGERPRINT
    has accrued REAL, trustworthy engagement on its published works (yoro /
    socialpost), the crowd's reaction OVERRIDES that score — the audience replaces
    the LLM judge. No author configured, offline, or no trustworthy data → no-op,
    so the synthetic ranking stands and offline/CI runs are unaffected."""
    if not _REACTION_ACTOR:
        return {}
    try:
        from lg_mangaka import engagement_metric as _em
        from lg_mangaka import recipe_fingerprint as _fp
        from lg_mangaka import recipe_ledger as _rl
    except Exception:  # noqa: BLE001
        return {}
    scored = state.get("scored", [])
    # Gather every published post URI for the candidates' style fingerprints.
    all_uris: list[str] = []
    for s in scored:
        all_uris += _rl.post_uris_for(_fp.fingerprint(s["recipe"]))
    # Prefer the recordlog D1 (RW-independent); fall back to the AppView feed.
    idx: dict = {}
    if all_uris and os.environ.get("SHINSHI_D1_WRITER_URL"):
        idx = await _em.fetch_engagement_recordlog(list(dict.fromkeys(all_uris)))
    if not idx:
        idx = await _em.fetch_author_engagement(_REACTION_ACTOR, base_url=_YORO_URL)
    if not idx:
        return {}
    overrides = []
    for s in scored:
        fp = _fp.fingerprint(s["recipe"])
        agg = _aggregate_engagement(idx, _rl.post_uris_for(fp))
        if not agg:
            continue
        eng = _em.engagement_weighted(agg["likes"], agg["reposts"], agg["replies"])
        if not _em.is_reaction_trustworthy(agg["impressions"], eng):
            continue  # too little exposure to be ground truth — keep synthetic
        rf = _em.reaction_fitness(likes=agg["likes"], reposts=agg["reposts"],
                                  replies=agg["replies"], impressions=agg["impressions"])
        if rf is None:
            continue
        s["synthetic_score"] = s["score"]
        s["reaction_score"] = rf
        s["score"] = rf
        overrides.append({"fingerprint": fp, "reaction": rf,
                          "synthetic": s["synthetic_score"], **agg})
    return {"scored": state.get("scored", []), "reaction_overrides": overrides}


async def _node_tournament(state: _S) -> dict:
    """Pairwise vision 'debate' between the two leaders → confirm the winner."""
    scored = sorted(state.get("scored", []), key=lambda x: x["score"], reverse=True)
    if len(scored) >= 2:
        a, b = scored[0], scored[1]
        text = ("Two manga panels are attached (first = A, second = B). Which is the better "
                'Weekly-Jump-quality panel? Reply JSON only: {"winner":"A|B","why":"<short>"}.')
        try:
            payload = {"model": _LLM_MODEL, "think": False, "stream": False,
                       "messages": [{"role": "user", "content": text,
                                     "images": [a["image_b64"], b["image_b64"]]}],
                       "options": {"num_predict": 150, "temperature": 0.2}}
            async with httpx.AsyncClient(timeout=300.0) as c:
                r = await c.post(_NATIVE_CHAT, json=payload, headers=_ep.auth_headers())
                d = _loads((r.json().get("message") or {}).get("content") or "{}") or {}
            # small Elo-like nudge so debate can override a near-tie
            if d.get("winner") == "B" and (a["score"] - b["score"]) < 5:
                a["score"], b["score"] = b["score"], a["score"]
        except Exception:  # noqa: BLE001
            pass
    return {}


async def _node_meta(state: _S) -> dict:
    arch = sorted(state.get("archive", []), key=lambda x: x["score"], reverse=True)
    hi = arch[:3]
    lo = arch[-2:] if len(arch) > 3 else []
    user = ("Distil the meta-review: what distinguishes the HIGH scorers from the LOW? "
            "Give 2-3 concrete recipe rules to apply next generation (1 sentence each).\n"
            f"HIGH: {json.dumps([{'recipe':h['recipe'],'score':h['score']} for h in hi], ensure_ascii=False)[:1200]}\n"
            f"LOW: {json.dumps([{'recipe':l['recipe'],'score':l['score']} for l in lo], ensure_ascii=False)[:600]}")
    notes = await _chat([{"role": "system", "content": "You are the Meta-review agent in an AI Co-Scientist loop."},
                         {"role": "user", "content": user}], max_tokens=300, temperature=0.4)
    best = arch[0] if arch else {}
    gi = state.get("gen_idx", 0)

    # SUPERVISOR guard: is the loop optimising a real signal, or a saturated one?
    best_scores = [t["best_score"] for t in state.get("trajectory", [])] + [best.get("score", 0)]
    spread = _score_spread([s["score"] for s in state.get("scored", [])])
    plateau = _is_plateau(best_scores)
    mh = state.get("metric_health") or []
    metric_ok = bool(mh[-1].get("ok", True)) if mh else True
    saturated = (plateau and spread < _SPREAD_MIN) or (not metric_ok)
    if saturated:
        why = ("the consistency metric FAILED its discrimination probe (good≈bad — it may be "
               "saturated like the old gemma4 rating)" if not metric_ok
               else f"best score has plateaued and this generation's spread is only {spread:.1f}")
        notes = (f"[SUPERVISOR] Treat the current fitness with suspicion: {why}. "
                 "Force MAXIMALLY DIVERGENT recipes next generation (new style anchors, "
                 "different samplers/cfg) rather than fine-tuning the leaders.\n" + (notes or ""))

    return {"meta_notes": notes, "best": best, "saturated": saturated,
            "gen_idx": gi + 1,
            "trajectory": [{"generation": gi, "best_score": best.get("score", 0),
                            "best_recipe_id": best.get("recipe", {}).get("id"),
                            "spread": round(spread, 1),
                            "metric_ok": metric_ok}]}


def _route(state: _S) -> str:
    return "generate" if state.get("gen_idx", 0) < state.get("n_generations", 3) else "finish"


def build():
    g: StateGraph = StateGraph(_S)
    g.add_node("generate", _node_generate)
    g.add_node("experiment", _node_experiment)
    g.add_node("online_review", _node_online_review)
    g.add_node("tournament", _node_tournament)
    g.add_node("meta", _node_meta)
    g.add_edge(START, "generate")
    g.add_edge("generate", "experiment")
    g.add_edge("experiment", "online_review")   # two-layer: real reactions override synthetic
    g.add_edge("online_review", "tournament")
    g.add_edge("tournament", "meta")
    g.add_conditional_edges("meta", _route, {"generate": "generate", "finish": END})
    return g.compile(name="coscientist_quality")


GRAPH = build()


async def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=3)
    ap.add_argument("--candidates", type=int, default=4)
    ap.add_argument("--subject", default="lone teenage hacker at a glowing holographic console, dramatic rim light, close-up")
    ap.add_argument("--shots", default="", help="comma-separated framings per candidate; >1 enables cross-panel consistency fitness")
    ap.add_argument("--save-best", default="/tmp/coscientist-best.png")
    a = ap.parse_args()
    shots = [s.strip() for s in a.shots.split(",") if s.strip()]
    print(f"[co-scientist] comfy={COMFY_URL} llm={_NATIVE_CHAT} model={_LLM_MODEL}")
    print(f"[co-scientist] {a.generations} generations x {a.candidates} candidates"
          + (f" x shots={shots} (consistency fitness)" if len(shots) > 1 else ""))
    final = await GRAPH.ainvoke(
        {"subject": a.subject, "shots": shots, "n_candidates": a.candidates,
         "n_generations": a.generations, "gen_idx": 0},
        {"recursion_limit": 100})
    print("\n=== trajectory (best score per generation) ===")
    for t in final.get("trajectory", []):
        flag = "" if t.get("metric_ok", True) else "  ⚠ METRIC NOT DISCRIMINATING"
        print(f"  gen {t['generation']}: best={t['best_score']:.0f}  spread={t.get('spread',0):.1f}  ({t['best_recipe_id']}){flag}")
    for h in final.get("metric_health", []):
        print(f"  [health] gen {h['gen']}: good={h['good']} bad={h['bad']} sep={h['separation']} "
              + ("OK" if h["ok"] else "DEGRADED ⚠"))
    if final.get("saturated"):
        print("  ⚠ SUPERVISOR flagged saturation — fitness was treated with suspicion (see meta).")
    ovr = final.get("reaction_overrides", [])
    if ovr:
        print(f"\n=== reaction overrides (crowd > LLM judge) — {len(ovr)} ===")
        for o in ovr:
            print(f"  fp {o['fingerprint']}: synthetic={o['synthetic']:.0f} → reaction={o['reaction']:.0f}  "
                  f"(L{o['likes']}/RP{o['reposts']}/RE{o['replies']}, imp={o['impressions']}, {o['posts']} posts)")
    elif _REACTION_ACTOR:
        print(f"\n[reaction] actor={_REACTION_ACTOR}: no trustworthy engagement yet (synthetic ranking stands)")
    best = final.get("best", {})
    print(f"\n=== BEST overall: score={best.get('score',0):.0f} ===")
    print(f"  recipe: {json.dumps(best.get('recipe',{}), ensure_ascii=False)}")
    print(f"  notes:  {best.get('notes','')}")
    print(f"  meta:   {final.get('meta_notes','')[:400]}")
    if best.get("image_b64"):
        open(a.save_best, "wb").write(base64.b64decode(best["image_b64"]))
        print(f"  saved best panel → {a.save_best}")


if __name__ == "__main__":
    asyncio.run(_main())
