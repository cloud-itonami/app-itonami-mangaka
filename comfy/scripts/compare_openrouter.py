#!/usr/bin/env python3
"""構図画像生成 AI の比較 — process は『構図画像生成 model → ControlNet → Animagine XL』。
ここでは ControlNet 入力となる『構図画像』を OpenRouter 上の各モデルで生成し、どれが
最も良いコマ構図(shot framing / 人物配置 / 透視 / シーンの読み取りやすさ)を作るかを
p0/p1 で比較する。生成画像は後段で canny/depth 化して Animagine の ControlNet に渡す。

RUN: python3 scripts/compare_openrouter.py --pages 0,1 --out /tmp/orcmp
"""
import argparse
import base64
import concurrent.futures as cf
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                  "data/ghosthacker/resources/episodes/arc0-1-origin")

# OpenRouter 上の image-output モデル(全てプロプライエタリ)。OSS は Animagine(Modal)で別途。
MODELS = [
    ("gemini-2.5-flash", "google/gemini-2.5-flash-image"),
    ("gemini-3-pro",     "google/gemini-3-pro-image-preview"),
    ("gemini-3.1-flash", "google/gemini-3.1-flash-image-preview"),
    ("gpt-5-image",      "openai/gpt-5-image"),
    ("gpt-5.4-image-2",  "openai/gpt-5.4-image-2"),
]

STYLES = {  # スタイル名 → (preamble, color?)
    "manga": ("A single black-and-white japanese manga panel, screentone shading, clean ink "
              "lineart", False),
    "jitsusha": ("A photorealistic live-action cinematic film still, realistic skin and "
                 "lighting, shot on film, shallow depth of field, color grade", True),
    "hollywood-cg": ("A polished Hollywood 3D CG animated film still, Pixar/cinematic quality "
                     "render, volumetric lighting, subsurface scattering, detailed textures", True),
    "artwork": ("A detailed digital painting illustration, concept art, painterly brushwork, "
                "dramatic cinematic lighting, rich color", True),
    "kyoani": ("A Kyoto Animation cel-shaded anime still, KyoAni style, soft cel shading, "
               "delicate clean linework, pastel palette, lush detailed background", True),
    # --- プロ制作工程アーティファクト ---
    "storyboard": ("A rough film production storyboard frame, loose black-and-white pencil "
                   "sketch, quick gestural drawing, simple value blocking, shot framing", False),
    "previs": ("A 3D previsualization frame, untextured gray clay-render blockout, rough "
               "low-detail CG figures and set, camera blocking, Unreal Engine previs, neutral "
               "gray lighting, no textures", True),
    "postviz": ("A postvisualization composite frame, rough CG characters composited over a "
                "photographic plate, temporary lighting, film postviz look", True),
    "virtual-prod": ("A virtual production cinematic still, real-time Unreal Engine render on "
                     "an LED volume, photoreal set, in-camera VFX, cinematic film lighting", True),
    "ekonte": ("A Japanese anime ekonte storyboard panel (絵コンテ), rough monochrome pencil, "
               "loose hand-drawn linework, simple director's framing, quick sketch", False),
    "layout": ("An anime production layout drawing (レイアウト), clean precise pencil lineart, "
               "accurate perspective and detailed background, character key positions, "
               "genga-style monochrome layout", False),
    "pixar": ("A Pixar-style 3D animated film still, polished stylized 3D characters with "
              "appealing proportions, warm cinematic lighting, subsurface scattering, "
              "RenderMan quality, expressive", True),
    # --- アクション・キーフレーム(コマ枠なし全面・決め画。漫画的に格好いい実写/illust) ---
    "vfx-keyframe": ("A single FULL-BLEED cinematic action keyframe, photorealistic VFX "
                     "blockbuster film still, NO panel border, NO frame, edge-to-edge image, "
                     "extreme dynamic low or dutch camera angle, strong foreshortening, motion "
                     "blur and speed, impact moment, hero silhouette against light, dramatic "
                     "negative space, Hollywood action cinematography. HEAVY SCI-FI VFX "
                     "COMPOSITED AND CLEARLY VISIBLE: glowing energy blade / digital slash arc, "
                     "holographic cyber glitch effects, particle and spark FX, supernatural "
                     "power made visible (do NOT make it mundane)", True),
    "concept-keyframe": ("A single FULL-BLEED dynamic concept keyframe illustration, painterly "
                         "cinematic key art, NO panel border, NO frame, edge-to-edge, "
                         "exaggerated dynamic action pose, heavy foreshortening, sweeping motion "
                         "lines, impact frame, dramatic angle, splash composition, bold "
                         "silhouette and negative space", True),
    "cinema-keyframe": ("A single FULL-BLEED cinematic film keyframe, photorealistic movie still, "
                        "NO panel border, NO frame, edge-to-edge image, expressive cinematic "
                        "lighting and lens, intentional composition matched to the scene's "
                        "emotion (calm/tense as fitting), shallow depth of field, film color "
                        "grade", True),
}

CHAR = {
    "yuto": "a 17-year-old japanese teenage boy with neat short black hair and tired shadowed eyes",
    "ren": "a 17-year-old japanese teenage boy with messy black hair and sleepy half-lidded eyes",
    "akira": "a 17-year-old japanese teenage boy with short brown hair and a lively grin",
    "nei": "a 16-year-old japanese teenage girl with long platinum blonde hair and blue eyes",
    "saki": "a 16-year-old japanese teenage girl with a brown bob and skeptical eyes",
    "mei": "a 16-year-old japanese teenage girl with black hair in a high ponytail",
}
SHOT_FRAMING = {
    "extreme close up": "extreme close-up, face fills the frame",
    "insert": "tight insert shot of an object, shallow focus",
    "close up": "close-up portrait, head and shoulders, rule of thirds",
    "medium": "medium shot, upper body, balanced composition with environment",
    "over the shoulder": "over-the-shoulder shot, foreground shoulder framing the subject",
    "wide": "wide establishing shot, full figures, strong sense of place and depth",
}


def _aspect(shot):
    return "wide cinematic 16:9 horizontal" if "wide" in shot.lower() else \
        ("tall vertical 3:4" if any(k in shot.lower() for k in ("close", "insert")) else "4:3")


ACTION_BOOST = (" DYNAMIC ACTION: explosive motion, dynamic exaggerated pose, foreshortening, "
                "speed lines and motion blur, energy effects and glowing slash/impact, debris "
                "and sparks, dramatic dutch/low angle, high-tension shonen battle composition, "
                "sense of force and momentum.")


def build_prompt(p, style="manga", action=False):
    shot = (p.get("shot") or "medium").lower()
    framing = next((v for k, v in SHOT_FRAMING.items() if k in shot), SHOT_FRAMING["medium"])
    chars = [c.lower() for c in (p.get("characters") or [])]
    who = "; ".join(CHAR.get(c, c) for c in chars) or "a japanese teenager"
    # Daemon(Ghost)を明示(敵キャラ)
    if any(c in ("daemon", "ghost") for c in chars) or "daemon" in (p.get("sceneSubject") or "").lower():
        who += "; a menacing dark digital demon entity (Daemon) with glitch corruption and glowing cyan circuit eyes"
    subj = p.get("sceneSubject") or ""
    vis = (p.get("visual") or "")[:240]
    preamble, _ = STYLES.get(style, STYLES["manga"])
    boost = ACTION_BOOST if action else ""
    return (f"{preamble}, clear readable composition. {framing}, {_aspect(shot)} framing. "
            f"Characters: {who}. Scene: {subj}. {vis}{boost} "
            f"Focus on strong cinematic composition: clear character placement, "
            f"depth, perspective, eye-flow. No speech bubbles, no text.")


def gen(model_id, prompt, key, ref_b64=None, timeout=180):
    content = [{"type": "text", "text": prompt}]
    refs = ref_b64 if isinstance(ref_b64, list) else ([ref_b64] if ref_b64 else [])
    for b in refs:                                 # identity ref + style ref(Animagine画風) 等
        if b:
            content.append({"type": "image_url",
                            "image_url": {"url": "data:image/png;base64," + b}})
    body = json.dumps({"model": model_id, "messages": [{"role": "user", "content": content}],
                       "modalities": ["image", "text"]}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", body,
                                 {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    msg = r["choices"][0]["message"]
    imgs = msg.get("images") or []
    if not imgs:
        raise RuntimeError("no image: " + str(msg.get("content"))[:120])
    return base64.b64decode(imgs[0]["image_url"]["url"].split(",", 1)[1])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="0,1")
    ap.add_argument("--out", default="/tmp/orcmp")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--models", default="", help="カンマ区切りで MODELS の short 名を絞り込み")
    ap.add_argument("--styles", default="manga", help="カンマ区切り or 'all'")
    ap.add_argument("--action", action="store_true", help="アクション・ブーストを全プロンプトに付与")
    ap.add_argument("--refchar", default="", help="この char(例 ren)の実写 ref で identity 固定")
    ap.add_argument("--refimg", default="", help="ref 画像パス")
    args = ap.parse_args(argv)
    ref_b64 = None
    if args.refchar and args.refimg and os.path.exists(args.refimg):
        ref_b64 = base64.b64encode(open(args.refimg, "rb").read()).decode()
    models = MODELS if not args.models else [m for m in MODELS if m[0] in args.models.split(",")]
    styles = list(STYLES) if args.styles == "all" else args.styles.split(",")
    import subprocess
    key = (subprocess.run(["security", "find-generic-password", "-s", "gftd.openrouter", "-w"],
                          capture_output=True, text=True).stdout.strip()
           or os.environ.get("OPENROUTER_APIKEY"))
    m = json.load(open(os.path.join(EP, "image-gen-manifest.json")))
    want = {int(x) for x in args.pages.split(",")}
    panels = sorted([p for p in m["panels"] if p["pageNum"] in want],
                    key=lambda z: (z["pageNum"], z.get("panelIndex", 0)))
    os.makedirs(args.out, exist_ok=True)
    jobs = []
    for p in panels:
        chars = [c.lower() for c in (p.get("characters") or [])]
        use_ref = ref_b64 if (args.refchar and args.refchar.lower() in chars) else None
        rp = (f" The character {args.refchar.capitalize()} must match the person in the reference "
              f"photo (same face, hairstyle, vibe).") if use_ref else ""
        for st in styles:
            prompt = build_prompt(p, st, action=args.action) + rp
            for short, mid in models:
                jobs.append((st, short, mid, p["pageNum"], p.get("panelIndex"), prompt, use_ref))

    def run(job):
        st, short, mid, pn, idx, prompt, use_ref = job
        # style ごとにサブフォルダ(manga は従来通り out/<model> で互換維持)
        d = os.path.join(args.out, short) if st == "manga" else os.path.join(args.out, f"{st}__{short}")
        os.makedirs(d, exist_ok=True)
        fp = os.path.join(d, f"p{pn}-panel{idx}.png")
        try:
            data = gen(mid, prompt, key, ref_b64=use_ref)
            open(fp, "wb").write(data)
            return f"OK  {st}/{short:16s} p{pn}#{idx}"
        except Exception as e:
            return f"ERR {st}/{short:16s} p{pn}#{idx}: {str(e)[:70]}"
    print(f"generating {len(jobs)} images ({len(models)} models × {len(styles)} styles × {len(panels)} panels)…")
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for res in ex.map(run, jobs):
            print(" ", res)
    print(f"done -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
