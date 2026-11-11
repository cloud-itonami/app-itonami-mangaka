#!/usr/bin/env python3
"""カット設計 → komawari写像 → vfx-concept keyframe生成 → 合成。
design_cuts.py が出した Cut[] を使い、(1) emphasis/duration をコマ面積へ写像して冨樫的な
リズム(見せゴマ大・速いカット小)の komawari を組み、(2) 各 Cut のカメラ(scale/angle/
camPos/lens)+ decisiveMoment + vfx で全面 keyframe を生成(人物=Ren ref のみ・背景無視)、
(3) dialogue を gaze.exit へ置いて合成する。

RUN: python3 scripts/render_cut_page.py --page 37 --cuts /tmp/cuts/p37.json \
        --style concept-keyframe --ref ../data/.../ren-jitsusha-person.png --out /tmp/cut-pages
"""
import argparse
import base64
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import compare_openrouter as C  # noqa: E402
import build_canonical_storyboard as B  # noqa: E402
import design_layers as L  # noqa: E402

EP = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                  "data/ghosthacker/resources/episodes/arc0-1-origin")
Bp, INNER, G = 17, 966, 14


def komawari(cuts):
    """emphasis 加重の RTL tier packer。hero(emph>=85)は単独 tier で大ゴマ、他は2-3詰め。"""
    tiers, cur = [], []
    for c in cuts:
        if c.get("emphasis", 50) >= 85:
            if cur:
                tiers.append(cur); cur = []
            tiers.append([c])
        else:
            cur.append(c)
            if len(cur) >= 3 or sum(x.get("emphasis", 50) for x in cur) >= 150:
                tiers.append(cur); cur = []
    if cur:
        tiers.append(cur)
    hw = [max(x.get("emphasis", 50) for x in t) ** 1.4 for t in tiers]   # hero をさらに高く
    total, avail_h, y = sum(hw), INNER - (len(tiers) - 1) * G, Bp
    rects = {}
    for t, h in zip(tiers, hw):
        rh = avail_h * h / total
        ws = [x.get("emphasis", 50) for x in t]
        sw, avail_w, x = sum(ws), INNER - (len(t) - 1) * G, Bp + INNER
        for c, w in zip(t, ws):
            cw = avail_w * w / sw
            x -= cw
            rects[c["order"]] = [round(x), round(y), round(cw), round(rh)]
            x -= G
        y += rh + G
    return rects


# gemini は一切グリフを描かない不変条件を守るため、テキスト描画を要求する上流データ
# (decisiveMoment 自由文 / vfx)を構図プロンプトに渡す前にスクラブする。タイトル/字幕/
# 描き文字は全て typeset レイヤ(写植)の担当 — ラスタへ焼き込ませない。
_TEXT_VFX = ("title-overlay", "title-card", "text-flash", "text-overlay", "caption",
             "subtitle", "logo", "credits", "kanji-overlay", "lettering", "typography")
_TEXT_RE = re.compile(
    r"\b(?:the|a|an)?\s*(?:title|titles?|text|caption|subtitle|logo|credit|word|words|"
    r"letter|lettering|kanji|typograph\w*)\b[^.,;]*", re.I)


def _scrub_text_intent(moment):
    """decisiveMoment から『文字が浮かぶ』系の語を除き、視覚演出だけ残す。"""
    out = _TEXT_RE.sub("the final image", moment or "")
    out = re.sub(r"\bthe the\b", "the", out, flags=re.I)
    return re.sub(r"\s{2,}", " ", out).strip(" ,.;")


def _scrub_vfx(vfx):
    return [v for v in (vfx or []) if not any(t in v.lower() for t in _TEXT_VFX)]


def _load_arcs():
    # EP=data/ghosthacker/resources/episodes/arc0-1-origin → ../../../character-arcs.json
    f = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(EP))), "character-arcs.json")
    try:
        return json.load(open(f))
    except Exception:
        return {"characters": {}}


def _in_pagespec(spec, pn):
    """'a-b' / 'a-' / 'a' を pn が満たすか。"""
    if "-" in spec:
        a, b = spec.split("-", 1)
        return int(a) <= pn <= (int(b) if b.strip() else 10**9)
    return int(spec) == pn


def _mood_for(char, pn, arcs):
    """キャラ×ページ → 感情フェーズ(表情/血色の override)。例外優先・区間は後勝ち。"""
    c = (arcs.get("characters") or {}).get(char)
    if not c:
        return None
    exc = (c.get("exceptions") or {}).get(str(pn))
    if exc:
        return exc
    hit = None
    for ph in c.get("phases", []):
        if _in_pagespec(ph.get("pages", ""), pn):
            hit = ph
    return hit


def _mood_clause(mp, pn, arcs):
    """inFrame 主要キャラの表情/血色を arc から引き、プロンプト末尾の override 文に。
    manifest visual が一様に somber でも、ここが authoritative(最後に効く)。"""
    if not arcs:
        return ""
    inframe = mp.get("_inFrame")
    chars = [c.lower() for c in (inframe if inframe is not None else (mp.get("characters") or []))]
    foc = (mp.get("focusCharacter") or "").lower()
    appr = arcs.get("canonAppearance") or {}
    seen, bits, looks = set(), [], []
    for ch in ([foc] + chars):
        if ch in seen:
            continue
        seen.add(ch)
        if appr.get(ch):
            looks.append(f"{ch.capitalize()}: {appr[ch]}")     # 髪色など不変の外見(identity)
        m = _mood_for(ch, pn, arcs)
        if m:
            neg = (" " + m["negative"]) if m.get("negative") else ""
            bits.append(f"{ch.capitalize()}: {m.get('expression','')}.{neg}")   # ページ別の表情
    out = ""
    if looks:
        out += " Canonical appearance (MUST match exactly): " + " ".join(looks)
    if bits:
        out += (" Character mood/expression (authoritative — override any contrary cue in the "
                "scene text): " + " ".join(bits))
    return out


def _wants_title(cut):
    """cut が扉タイトル投下を意図しているか(vfx に title-overlay/title-card)。"""
    return "title" in " ".join(cut.get("vfx") or []).lower()


def _load_title(ep):
    """work/chapter の実タイトル文字列(データ)を story-outline から読む。gemini の捏造を
    使わず、これを typeset レイヤで組む。"""
    try:
        s = json.load(open(os.path.join(ep, "story-outline.jsonld")))
    except Exception:
        return {}
    raw = (s.get("dct:title") or "").strip()
    series, main = "", raw
    if "/" in raw:
        series, main = (x.strip() for x in raw.split("/", 1))
    main = main.strip("『』「」\"' ")
    return {"text": main, "series": series} if main else {}


# 静かなコマ(対話・独白・確立)用の落ち着いた構図プリアンブル。concept-keyframe の
# 「誇張アクションポーズ/スプラッシュ」を全コマに強制すると静かな場面が崩れるため、
# エネルギーに応じて使い分ける。画風(Animagine cel-shade)は identity ref で別途付与。
_CALM_PREAMBLE = (
    "A single FULL-BLEED anime illustration, faithful cinematic rendering of the scene exactly "
    "as described, natural composition matching the shot scale and mood, grounded staging, NO "
    "panel border, edge-to-edge, modern anime cel-shading — NOT an exaggerated action splash, "
    "NO gratuitous foreshortening; let the framing serve the moment.")
_DYNAMIC_IMPRESSIONS = {"impact", "speed", "awe", "action"}
_WIDE_SCALES = {"MS", "MLS", "LS", "WS"}      # スプラッシュが映える広め〜全身ショット


def _is_dynamic(cut):
    """このコマが本当にアクション(スプラッシュ)構図に値するか。全身が映る広めショット
    かつ 印象=衝撃/速度/畏怖 or climax の action/impact のみ。寄り(ECU/CU/insert)や
    大半の対話コマは calm に倒す(誇張ポーズで場面が崩れるのを防ぐ)。"""
    if cut.get("shot", {}).get("scale") not in _WIDE_SCALES:
        return False
    imp = (cut.get("gaze", {}) or {}).get("impression", "")
    return imp in _DYNAMIC_IMPRESSIONS or (
        cut.get("intent") in ("action", "impact") and cut.get("emphasis", 50) >= 82)


def cut_prompt(cut, mp, style, pn=0, arcs=None):
    s = cut.get("shot", {})
    if _is_dynamic(cut):
        preamble, _ = C.STYLES.get(style, C.STYLES["concept-keyframe"])
    else:
        preamble = _CALM_PREAMBLE
    # inFrame = 画面内キャラ(配役の部分集合)。director 指定 or staging射影で決まる。
    inframe = mp.get("_inFrame")
    chars = [c.lower() for c in (inframe if inframe is not None else (mp.get("characters") or []))]
    who = "; ".join(C.CHAR.get(c, c) for c in chars) or "a japanese teenager"
    if any(c in ("daemon", "ghost") for c in chars):
        who += "; a menacing dark digital Daemon entity, glitch corruption, glowing cyan circuit eyes"
    only = (f" ONLY these characters are in frame: {', '.join(c.capitalize() for c in chars)} — "
            "absolutely NO other named characters appear in this panel. ") if chars else ""
    staging = (f" Staging/placement: {mp['_staging']}. " if mp.get("_staging") else "")
    vfx = ", ".join(_scrub_vfx(cut.get("vfx")))
    # SFX を構図の前に渡す: 大描き文字用の余白を空けて構図させる(描き文字自体は描かない)
    _, _, sfxl = L.layers_for_cut(cut, mp, climax=(cut.get("intent") == "impact"))
    bigsfx = [x for x in sfxl if x.get("bleed") or x.get("scale", 0) >= 100]
    sfxhint = ""
    if bigsfx:
        side = "left" if (cut.get("gaze", {}).get("exitX", 200) < 500) else "right"
        sfxhint = (f"Compose with a CLEAR negative-space area on the {side} side / one edge for a "
                   "LARGE hand-drawn manga sound-effect to be placed later — keep that area "
                   "uncluttered (do NOT draw the text itself). ")
    # マニフェストの visual = 各コマの正規シーン記述(設定・場所・動作)。これを authoritative な
    # 場面として渡すと、ページ内のコマが同じ設定に留まり継続性が保たれる(decisiveMoment は
    # design_cuts が足した『瞬間』の演出で、抽象的すぎると gemini が別シーンへ飛ぶ)。両方 scrub。
    visual = _scrub_text_intent(mp.get("visual", ""))
    scene = f"Scene/setting (authoritative): {visual}. " if visual else \
            f"Scene: {mp.get('sceneSubject','')}. "
    return (f"{preamble}. {s.get('scale','MS')} shot, {s.get('angle','eye')} angle, camera "
            f"{s.get('camPos','three-quarter')}, {s.get('lens','normal-50')} lens, "
            f"{s.get('move','static')}. {scene}"
            f"Key moment within that scene: {_scrub_text_intent(cut.get('decisiveMoment',''))}. "
            f"Characters: {who}.{only}{staging}"
            + _mood_clause(mp, pn, arcs) + " "
            + (f"VFX clearly visible (do NOT make mundane): {vfx}. " if vfx else "")
            + (f"Foreground: {cut.get('fgElement','')}. " if cut.get("fgElement") else "")
            + sfxhint
            + f"Mood: {cut.get('gaze',{}).get('impression','tension')}. FULL-BLEED, edge-to-edge, "
            "NO panel border, manga-cool cinematic composition. "
            "CLEAN BASE ART for layer compositing: NO speech bubbles, NO dialogue text, NO "
            "captions, NO sound-effect lettering, NO words; AND NO screentone / halftone dot "
            "shading, NO manga speed-lines, NO focus concentration-lines (these tone/effect/SFX "
            "layers are composited separately afterward). DO render the scene, characters, "
            "lighting, and any energy / sci-fi VFX as clean painted art — just without the "
            "manga screentone & line-effect overlays.")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", type=int, default=37)
    ap.add_argument("--cuts", default="")
    ap.add_argument("--style", default="concept-keyframe")
    ap.add_argument("--model", default="gemini-3.1-flash")
    ap.add_argument("--ref", default="")
    ap.add_argument("--refchar", default="ren")
    ap.add_argument("--refdir", default="",
                    help="character-refs dir — 各登場キャラの identity ref を焦点キャラに付与")
    ap.add_argument("--styleref", default="",
                    help="Animagine 画風の style anchor 画像。gemini keyframe を Animagine風に揃える")
    ap.add_argument("--reuse", action="store_true", help="既存 keyframe を再利用(再生成しない)")
    ap.add_argument("--facescache", default="", help="顔キャッシュ(modal_face_detect)で face-aware 配置")
    ap.add_argument("--pagelayout", default="",
                    help="design_pagelayout dir — ネーム設計(段/サイズ/断ち切り)で komawari を駆動")
    ap.add_argument("--dialogue", default="",
                    help="polish_dialogue dir — 説明口調を自然なセリフに差し替え")
    ap.add_argument("--directives", default="",
                    help="director 指定 dir(p{N}.json: panelごと inFrame/staging を clamp)")
    ap.add_argument("--out", default="/tmp/cut-pages")
    args = ap.parse_args(argv)
    pn = args.page
    cuts = json.load(open(args.cuts or f"/tmp/cuts/p{pn}.json"))["cuts"]
    arcs = _load_arcs()                       # キャラ感情アーク(表情/血色の page 別 override)
    cuts.sort(key=lambda c: c.get("order", 0))
    # ページ割り(ネーム L4): pagelayout があればそれで komawari を駆動、無ければ emphasis packer
    plbleed = {}
    plf = os.path.join(args.pagelayout, f"p{pn}.json") if args.pagelayout else ""
    if plf and os.path.exists(plf):
        import design_pagelayout as PL
        packed = PL.pack(json.load(open(plf)))
        rects = {o: rb[0] for o, rb in packed.items()}
        plbleed = {o: rb[1] for o, rb in packed.items()}
    else:
        rects = komawari(cuts)
    key = (subprocess.run(["security", "find-generic-password", "-s", "gftd.openrouter", "-w"],
                          capture_output=True, text=True).stdout.strip()
           or os.environ.get("OPENROUTER_APIKEY"))
    midname = next((mid for short, mid in C.MODELS if short == args.model), args.model)
    ref_b64 = (base64.b64encode(open(args.ref, "rb").read()).decode()
               if args.ref and os.path.exists(args.ref) else None)
    # 各キャラの identity ref マップ (concept-keyframe は illustrated なのでアニメrefで統一、
    # ただし ren は実写 person-ref で「その人物」を固定)
    refmap = {}
    if args.refdir and os.path.isdir(args.refdir):
        for ch in ("yuto", "ren", "nei", "akira", "saki", "mei", "daemon"):
            cand = (os.path.join(args.refdir, "ren-jitsusha-person.png") if ch == "ren"
                    else os.path.join(args.refdir, f"{ch}.png"))
            if not os.path.exists(cand):
                cand = os.path.join(args.refdir, f"{ch}.png")
            if os.path.exists(cand):
                refmap[ch] = base64.b64encode(open(cand, "rb").read()).decode()
    m = json.load(open(os.path.join(EP, "image-gen-manifest.json")))
    mpanels = {p.get("panelIndex"): p for p in m["panels"] if p["pageNum"] == pn}
    # 仕上げ済みセリフ(polish_dialogue)があれば manifest の台詞を差し替える(説明口調→自然)
    dlf = os.path.join(args.dialogue, f"p{pn}.json") if args.dialogue else ""
    if dlf and os.path.exists(dlf):
        pol = json.load(open(dlf))
        for idx, mp in mpanels.items():
            ds = pol.get(str(idx)) or pol.get(idx)
            if ds is None:
                continue
            foc = (mp.get("focusCharacter") or "").lower()
            new = []
            for d in ds:
                sp = (d.get("speaker") or "").lower()
                kind = d.get("kind", "speech")
                if sp in ("monologue", "narration", "narrator", "") or kind == "thought":
                    sp = foc or sp                         # 心の声 = 焦点キャラの内語に帰属
                new.append({"speaker": sp, "text": d.get("text", ""),
                            "emotion": "thought" if kind == "thought" else d.get("kind", "")})
            mp["dialogues"] = new                          # SFX は keep されないが design_layers が別途生成
    # director 指定(細かい制約の clamp): inFrame(画面内キャラ) + staging(配置)を panel に固定
    drf = os.path.join(args.directives, f"p{pn}.json") if args.directives else ""
    if drf and os.path.exists(drf):
        dr = json.load(open(drf))
        # _scene: シーン共有 staging(character→world位置)。全パネルに伝播=低ランク因子。
        scene = dr.get("_scene") or {}
        scene_stage = scene.get("staging", "")
        positions = scene.get("positions") or {}        # {character: world位置}
        for idx, mp in mpanels.items():
            spec = dr.get(str(idx)) or dr.get(idx) or {}
            inf = spec.get("inFrame")
            if inf is not None:
                mp["_inFrame"] = [c.lower() for c in inf]
            # 画面内キャラの world 位置をシーン staging から引いて一貫させる
            framed = mp.get("_inFrame") or [c.lower() for c in (mp.get("characters") or [])]
            pos_bits = "; ".join(f"{c.capitalize()} is {positions[c]}" for c in framed if c in positions)
            parts = [p for p in (spec.get("staging", ""), pos_bits, scene_stage) if p]
            if parts:
                mp["_staging"] = ". ".join(parts)
    imgdir = os.path.join(args.out, f"p{pn}-panels")
    os.makedirs(imgdir, exist_ok=True)

    styleref_b64 = (base64.b64encode(open(args.styleref, "rb").read()).decode()
                    if args.styleref and os.path.exists(args.styleref) else None)

    def gen_one(cut):
        mp = mpanels.get(cut["order"], {})
        prompt = cut_prompt(cut, mp, args.style, pn, arcs)
        chars = [c.lower() for c in (mp.get("characters") or [])]
        # 焦点キャラの identity ref を優先(無ければ refchar / 単一 --ref)
        foc = (mp.get("focusCharacter") or "").lower()
        rc = foc if foc in refmap else next((c for c in chars if c in refmap), None)
        idref = refmap.get(rc) if rc else (ref_b64 if (args.refchar in chars) else None)
        if idref and rc:
            prompt += (f" The character {rc.capitalize()} MUST match the identity (face, "
                       "hairstyle, vibe) of the PERSON in the FIRST reference image ONLY; "
                       "IGNORE that reference's background. Other characters keep their own "
                       "distinct identities — do NOT copy the reference person's face onto them.")
        elif idref:
            prompt += (f" The character {args.refchar.capitalize()} must match the person in the "
                       "first reference photo (face & hairstyle ONLY); IGNORE its background.")
        # 画風アンカー: キャラ identity ref 自体が Animagine 画風なので、それを画風源にする。
        # 別 styleref(中立アンカー)があれば最後に足すが、キャラ肖像を styleref にすると identity
        # が漏れるため rollout では使わない。Animagine 指示は ref の有無に依らず付与。
        use_ref = [r for r in [idref, styleref_b64] if r] or None
        anchor = "LAST" if styleref_b64 else "FIRST"
        prompt += (f" Render the ENTIRE image in modern anime art style matching the {anchor} "
                   "reference: Animagine-XL cel-shading, crisp clean thin line weight, flat cel "
                   "coloring, soft anime rendering — NOT photorealistic.")
        fp = os.path.join(imgdir, f"p{pn}-panel{cut['order']}.png")
        if args.reuse and os.path.exists(fp):
            return cut["order"], fp
        try:
            open(fp, "wb").write(C.gen(midname, prompt, key, ref_b64=use_ref))
            return cut["order"], fp
        except Exception as e:
            print(f"  cut{cut['order']} ERR {str(e)[:70]}")
            return cut["order"], None
    print(f"p{pn}: generating {len(cuts)} cut-keyframes ({args.style}/{args.model})…")
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        imgs = dict(ex.map(gen_one, cuts))

    # face-aware にする場合は modal 顔キャッシュを build_canonical に差し込む
    facemode = bool(args.facescache and os.path.exists(args.facescache))
    if facemode:
        B._FACES = json.load(open(args.facescache))

    def _gaze_bubbles(mp, gz):
        out = []
        for d in (mp.get("dialogues") or []):
            sp = (d.get("speaker") or "").lower()
            if B._is_narration(sp) or sp == "sfx" or not d.get("text"):
                continue
            # split_dialogue の各 chunk は『別の吹き出し』。1 chunk=1 bubble、列は≤10字に wrap。
            for chunk in B.split_dialogue(B._en2kana(d["text"]), 16):
                if len(out) >= 4:                          # 1コマ最大4吹き出し
                    break
                lines, mcpc = B._wrap_chunk(chunk, 10)     # 1列≤10字 制約
                k = len(out)
                out.append({"text": chunk, "lines": lines, "shape": "round", "font": "mincho",
                            "writingMode": "vertical-rtl", "maxCharsPerCol": min(10, mcpc),
                            "speaker": sp, "order": k + 1, "anchor": "free",
                            "posX": gz.get("exitX", 200) + (k % 2) * 80,
                            "posY": gz.get("exitY", 200) + k * 90,
                            "tailX": gz.get("focusX", 500), "tailY": gz.get("focusY", 460)})
        return out

    worktitle = _load_title(EP)
    panels = []
    for cut in cuts:
        o, r, mp, gz = cut["order"], rects[cut["order"]], mpanels.get(cut["order"], {}), cut.get("gaze", {})
        imgp = imgs.get(o) or ""
        faces, cropx, cropy = [], 0.5, 0.5
        if facemode and imgp:
            cropx, cropy, faces = B._crop_and_faces(imgp, r[2], r[3], 0.7)   # 顔寄せクロップ
        if faces:                                            # face-aware (build_bubbles + focus尻尾)
            bubs = B.build_bubbles(mp, mp.get("tone"), faces)
            foc = (mp.get("focusCharacter") or "").lower()
            focf = next((b for b in faces if len(b) > 5 and (b[5] or "").lower() == foc), None)
            for bub in bubs:
                if "linkTo" in bub or bub.get("shape") in ("rect", "whisper") or "faceIndex" in bub:
                    continue
                if focf is not None:
                    bub["tailX"], bub["tailY"] = B._mouth(focf)
        else:
            bubs = _gaze_bubbles(mp, gz)
        # 層分離: cut から tone/effectLine/sfx を導出(各層は手続き型コンポジタが描く)
        tones, eff, sfx = L.layers_for_cut(cut, mp, climax=(cut.get("intent") == "impact"))
        bleed = plbleed.get(o) if plbleed else (
            ["top", "left", "right"] if cut.get("intent") == "establish" and r[2] >= 0.9 * INNER
            else [])
        pdct = {"order": o, "x": r[0], "y": r[1], "w": r[2], "h": r[3],
                "bleed": bleed,
                "_imagePath": imgp, "_cropX": cropx, "_cropY": cropy, "faces": faces,
                "bubbles": bubs, "shot": cut.get("shot", {}), "gaze": gz,
                "sfx": sfx, "effectLines": eff, "tones": tones}
        # 扉タイトル写植: cut が title 投下を意図し、実タイトル文字列があれば typeset レイヤ化。
        # 配置は被写体の反対側(negative space)へ。RTL なので既定は右、被写体が右寄りなら左。
        if _wants_title(cut) and worktitle.get("text"):
            side = "left" if gz.get("focusX", 500) > 550 else "right"
            pdct["title"] = {**worktitle, "placement": side, "scale": 74,
                             "color": "white", "font": "bold-mincho"}
        panels.append(pdct)
    title = mpanels.get(1, {}).get("pageTitle", f"p{pn}").split("[")[0].strip()
    doc = {"episode": "ghosthacker/arc0-1-origin", "pages": [
        {"pageNum": pn, "pageTitle": f"{title} [cut-design]", "panels": panels}]}
    pj = os.path.join(args.out, f"p{pn}-cut.page.json")
    json.dump(doc, open(pj, "w"), ensure_ascii=False)
    out_pdf = os.path.join(args.out, f"p{pn}-cut.pdf")
    subprocess.run([sys.executable, os.path.join(HERE, "komawari_blueprint_pdf.py"),
                    "--in", pj, "--out", out_pdf], env={**os.environ, "KOMA_CLEAN": "1"},
                   capture_output=True)
    png = out_pdf.replace(".pdf", ".p1.png")
    print(f"scales={[c['shot']['scale'] for c in cuts]}  -> {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
