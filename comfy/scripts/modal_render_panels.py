#!/usr/bin/env python3
"""検証用: p2 の各パネルを Animagine XL 4.0 で「Civitai 品質」生成 (Modal GPU)。

ユーザー提示の設定に合わせる: Animagine XL 4.0 / Euler A / steps 20 / CFG 7 /
seed 251123 / modern anime coloring・natural skin shading・soft shadows。
storyboard ではなく素のクリーンな SDXL パネルを出す検証。

RUN:
  MODAL_PROFILE=jun784 /tmp/modalenv/bin/modal run scripts/modal_render_panels.py \
      [--seed 251123]
出力: /tmp/p2-render/p2-panelN.png + contact sheet p2-contact.png
"""
import base64
import io
import json
import os

import modal

MODEL = "cagliostrolab/animagine-xl-4.0"
app = modal.App("mangaka-panel-render")
hf_cache = modal.Volume.from_name("mangaka-sdxl-cache", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("torch", "diffusers>=0.31.0", "transformers>=4.45.0", "accelerate>=0.34.0",
                 "pillow", "sentencepiece", "invisible-watermark")
    .env({"HF_HOME": "/cache/hf", "HF_HUB_ENABLE_HF_TRANSFER": "0"})
)

# ── キャラ記述 (v10 CHAR_COLOR + Mei) ───────────────────────────────────────
CHAR = {  # 男子は学生服(黒の詰襟 gakuran)、女子はセーラー服
    "Yuto":  "messy black hair, dark eyes, black gakuran high-collar school uniform, slim build",
    "Ren":   "messy black hair with subtle blue highlights, sleepy half-lidded tired eyes, "
             "black gakuran high-collar school uniform, pale skin",
    "Nei":   "long platinum blonde hair, blue eyes, navy sailor uniform with red ribbon",
    "Akira": "short brown hair, mischievous expression, black gakuran high-collar school uniform",
    "Saki":  "shoulder-length brown hair, skeptical expression, navy sailor uniform",
    "Mei":   "black hair in a high ponytail, bright cheerful eyes, navy sailor uniform",
    "Daemon": "dark digital demon entity, black hooded cloak, glowing cyan circuit-pattern "
              "eyes, glitch corruption aura, menacing cyber spectre",
}
GENDER = {"Yuto": "1boy", "Ren": "1boy", "Akira": "1boy", "Daemon": "1other",
          "Nei": "1girl", "Saki": "1girl", "Mei": "1girl"}
SCENE = ("japanese high school classroom interior, wooden desks, blackboard, "
         "west window with afternoon sunlight, lunch break")
# ユーザー提示スクショ準拠の品質/スタイル
QUALITY = "masterpiece, high score, great score, absurdres, "
STYLE = ("modern anime coloring, natural skin shading, soft shadows, "
         "shallow depth of field, background blur, consistent clothing, detailed face")
NEG = ("lowres, bad anatomy, bad hands, deformed, mutated, malformed hands, fused fingers, "
       "extra limbs, extra arms, disfigured, distorted face, asymmetric eyes, long neck, "
       "text, error, missing finger, extra digits, fewer digits, cropped, worst quality, "
       "low quality, low score, bad score, average score, signature, watermark, "
       "username, blurry")
SHOT = {  # shot → (framing tag, w, h)
    "close up":    ("close-up portrait, bust shot, expressive face", 832, 1216),
    "medium":      ("medium shot, upper body", 896, 1152),
    "film-medium": ("cinematic medium shot, upper body", 896, 1152),
    "wide":        ("wide establishing shot, full bodies, group", 1216, 832),
}


@app.cls(gpu="L40S", image=image, volumes={"/cache/hf": hf_cache},
         secrets=[modal.Secret.from_name("huggingface")],
         timeout=1800, scaledown_window=120)
class Renderer:
    @modal.enter()
    def load(self):
        import torch
        from diffusers import EulerAncestralDiscreteScheduler, StableDiffusionXLPipeline
        self.torch = torch
        self.pipe = StableDiffusionXLPipeline.from_pretrained(
            MODEL, torch_dtype=torch.float16, use_safetensors=True,
            add_watermarker=False).to("cuda")
        self.pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(
            self.pipe.scheduler.config)
        self.pipe.set_progress_bar_config(disable=True)

    @modal.method()
    def render(self, prompt, neg, w, h, seed, steps=20, cfg=7.0):
        g = self.torch.Generator("cuda").manual_seed(int(seed))
        im = self.pipe(prompt=prompt, negative_prompt=neg, width=w, height=h,
                       num_inference_steps=steps, guidance_scale=cfg, generator=g).images[0]
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()


@app.cls(gpu="L40S", image=image, volumes={"/cache/hf": hf_cache},
         secrets=[modal.Secret.from_name("huggingface")],
         timeout=1800, scaledown_window=120)
class IPRenderer:
    """Animagine XL 4.0 + IP-Adapter Plus (ViT-H) — キャラ参照画像で identity 固定。"""
    @modal.enter()
    def load(self):
        import torch
        from diffusers import EulerAncestralDiscreteScheduler, StableDiffusionXLPipeline
        from transformers import CLIPVisionModelWithProjection
        self.torch = torch
        enc = CLIPVisionModelWithProjection.from_pretrained(
            "h94/IP-Adapter", subfolder="models/image_encoder", torch_dtype=torch.float16)
        self.pipe = StableDiffusionXLPipeline.from_pretrained(
            MODEL, image_encoder=enc, torch_dtype=torch.float16,
            use_safetensors=True, add_watermarker=False).to("cuda")
        self.pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(
            self.pipe.scheduler.config)
        self.pipe.load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models",
                                  weight_name="ip-adapter-plus_sdxl_vit-h.safetensors")
        self.pipe.set_progress_bar_config(disable=True)

    @modal.method()
    def render(self, prompt, neg, w, h, seed, ref_b64, scale=0.6):
        from PIL import Image
        ref = Image.open(io.BytesIO(base64.b64decode(ref_b64))).convert("RGB")
        self.pipe.set_ip_adapter_scale(float(scale))
        g = self.torch.Generator("cuda").manual_seed(int(seed))
        im = self.pipe(prompt=prompt, negative_prompt=neg, ip_adapter_image=ref,
                       width=w, height=h, num_inference_steps=24, guidance_scale=7.0,
                       generator=g).images[0]
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()


seg_image = image.pip_install("dghs-imgutils", "onnxruntime", "numpy")


@app.cls(gpu="L40S", image=seg_image, volumes={"/cache/hf": hf_cache},
         secrets=[modal.Secret.from_name("huggingface")],
         timeout=1800, scaledown_window=120)
class Method2:
    """シーン先行 → 人物セグメント → 人物mask だけ IPAdapter inpaint で identity 更新。
    pass1 で構図/ポーズ/引き寄りを prompt 主導で確定 → 人物 alpha を isnetis で抽出 →
    その領域だけ inpaint(+IPAdapter)で顔/キャラを寄せる。IPAdapter は人物に限局される
    ので構図を引っ張らない。"""
    @modal.enter()
    def load(self):
        import torch
        from diffusers import (EulerAncestralDiscreteScheduler,
                               StableDiffusionXLInpaintPipeline, StableDiffusionXLPipeline)
        from transformers import CLIPVisionModelWithProjection
        self.torch = torch
        enc = CLIPVisionModelWithProjection.from_pretrained(
            "h94/IP-Adapter", subfolder="models/image_encoder", torch_dtype=torch.float16)
        self.pipe = StableDiffusionXLPipeline.from_pretrained(
            MODEL, image_encoder=enc, torch_dtype=torch.float16,
            use_safetensors=True, add_watermarker=False).to("cuda")
        self.pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(self.pipe.scheduler.config)
        # 先に IPAdapter を載せてから inpaint を派生 → inpaint も image_encoder/adapter を継承。
        # IPAdapter は共有 UNet に載るので、pass1(txt2img)は scale 0 で無効化して使う。
        self.pipe.load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models",
                                  weight_name="ip-adapter-plus_sdxl_vit-h.safetensors")
        self.inpaint = StableDiffusionXLInpaintPipeline.from_pipe(self.pipe)
        self.pipe.set_progress_bar_config(disable=True)
        self.inpaint.set_progress_bar_config(disable=True)

    @modal.method()
    def gen(self, scene_prompt, id_prompt, neg, w, h, seed, ref_b64, ip_scale=0.75):
        from PIL import Image, ImageFilter
        from imgutils.segment import segment_rgba_with_isnetis
        ref = Image.open(io.BytesIO(base64.b64decode(ref_b64))).convert("RGB")
        # ── pass1: 構図(identity 無し, IPAdapter scale 0) ──
        self.pipe.set_ip_adapter_scale(0.0)
        g1 = self.torch.Generator("cuda").manual_seed(int(seed))
        scene = self.pipe(prompt=scene_prompt, negative_prompt=neg, ip_adapter_image=ref,
                          width=w, height=h, num_inference_steps=26, guidance_scale=7.0,
                          generator=g1).images[0]
        # ── 人物 alpha 抽出 → mask(膨張+ぼかし) ──
        try:
            _, rgba = segment_rgba_with_isnetis(scene)
            mask = rgba.getchannel("A").resize(scene.size)
        except Exception:
            mask = Image.new("L", scene.size, 255)        # 失敗時は全面
        mask = mask.point(lambda v: 255 if v > 90 else 0)
        mask = mask.filter(ImageFilter.MaxFilter(13)).filter(ImageFilter.GaussianBlur(5))
        # ── pass2: 人物mask だけ inpaint で identity 更新(IPAdapter は人物に限局) ──
        self.pipe.set_ip_adapter_scale(float(ip_scale))
        g2 = self.torch.Generator("cuda").manual_seed(int(seed) + 1)
        out = self.inpaint(prompt=id_prompt, negative_prompt=neg, image=scene, mask_image=mask,
                           ip_adapter_image=ref, strength=0.6, num_inference_steps=32,
                           guidance_scale=7.0, generator=g2).images[0]

        def _j(im):                                       # JPEG で小さく返す(blob回避)
            bb = io.BytesIO()
            im.convert("RGB").save(bb, "JPEG", quality=92)
            return bb.getvalue()
        return _j(scene), _j(out)

    @modal.method()
    def detail(self, img_b64, faces, ref_b64, id_prompt, scale=0.5, denoise=0.42):
        """フェイス・ディテーラ: 各検出顔を 1024 に拡大→楕円マスクで inpaint(+IPAdapter)
        し直してディテールを上げ、元位置へ縮小して貼り戻す(ADetailer 方式)。"""
        from PIL import Image, ImageDraw, ImageFilter
        im = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")
        W, H = im.size
        ref = Image.open(io.BytesIO(base64.b64decode(ref_b64))).convert("RGB")
        self.pipe.set_ip_adapter_scale(float(scale))
        changed = False
        for f in faces:
            x, y, w, h = f[:4]
            if w < 42 or h < 42:                          # 小さすぎる顔はスキップ
                continue
            px, py = int(w * 0.45), int(h * 0.55)
            x0, y0 = max(0, x - px), max(0, y - py)
            x1, y1 = min(W, x + w + px), min(H, y + h + py)
            crop = im.crop((x0, y0, x1, y1))
            cw, ch = crop.size
            s = 1024.0 / max(cw, ch)
            up = crop.resize((max(8, int(cw * s)), max(8, int(ch * s))))
            mask = Image.new("L", up.size, 0)
            ImageDraw.Draw(mask).ellipse(
                [(x - x0) * s, (y - y0) * s, (x + w - x0) * s, (y + h - y0) * s], fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(max(2, int(up.width * 0.04))))
            g = self.torch.Generator("cuda").manual_seed(12345)
            out = self.inpaint(
                prompt="detailed face, sharp clean eyes, high detail anime face, " + id_prompt,
                negative_prompt="blurry, deformed face, bad eyes, extra eyes, lowres",
                image=up, mask_image=mask, ip_adapter_image=ref, strength=float(denoise),
                num_inference_steps=22, guidance_scale=6.5, generator=g).images[0]
            im.paste(out.resize((cw, ch)), (x0, y0))
            changed = True
        bb = io.BytesIO()
        im.save(bb, "JPEG", quality=92)
        return bb.getvalue(), changed


cn_image = seg_image.pip_install("opencv-python-headless")
CN_CANNY = "xinsir/controlnet-canny-sdxl-1.0"


@app.cls(gpu="L40S", image=cn_image, volumes={"/cache/hf": hf_cache},
         secrets=[modal.Secret.from_name("huggingface")], timeout=1800, scaledown_window=120)
class Harmonizer:
    """仕上げ統一 — Animagine img2img を低 denoise でかけ、内容を保持したまま描画タッチ/
    パレットをページ全体で統一する(全パネル同一モデル+共通 style anchor)。gemini を使わ
    ないので画風は Animagine のまま。"""
    @modal.enter()
    def load(self):
        import torch
        from diffusers import (EulerAncestralDiscreteScheduler,
                               StableDiffusionXLImg2ImgPipeline)
        self.torch = torch
        self.pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
            MODEL, torch_dtype=torch.float16, use_safetensors=True,
            add_watermarker=False).to("cuda")
        self.pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(self.pipe.scheduler.config)
        self.pipe.set_progress_bar_config(disable=True)

    @modal.method()
    def gen(self, img_b64, prompt, neg, seed, strength=0.32, steps=30):
        from PIL import Image
        im = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")
        w, h = im.size                                     # SDXL 寸法へ(長辺1216, /8)
        lng = 1216
        W, H = (lng, int(lng * h / w)) if w >= h else (int(lng * w / h), lng)
        W, H = max(768, (W // 8) * 8), max(768, (H // 8) * 8)
        im = im.resize((W, H), Image.LANCZOS)
        gen = self.torch.Generator("cuda").manual_seed(int(seed))
        out = self.pipe(prompt=prompt, negative_prompt=neg, image=im,
                        strength=float(strength), num_inference_steps=int(steps),
                        guidance_scale=7.0, generator=gen).images[0]
        bb = io.BytesIO()
        out.convert("RGB").save(bb, "PNG")
        return bb.getvalue()


@app.cls(gpu="L40S", image=cn_image, volumes={"/cache/hf": hf_cache},
         secrets=[modal.Secret.from_name("huggingface")],
         timeout=1800, scaledown_window=120)
class Method3:
    """方法③: 正規版パネルから canny(線画)→ ControlNet で構図ロック → IPAdapter で
    identity。構図は ControlNet が固定するので IPAdapter を効かせても崩れない。"""
    @modal.enter()
    def load(self):
        import torch
        from diffusers import (ControlNetModel, EulerAncestralDiscreteScheduler,
                               StableDiffusionXLControlNetPipeline)
        from transformers import CLIPVisionModelWithProjection
        self.torch = torch
        enc = CLIPVisionModelWithProjection.from_pretrained(
            "h94/IP-Adapter", subfolder="models/image_encoder", torch_dtype=torch.float16)
        cn = ControlNetModel.from_pretrained(CN_CANNY, torch_dtype=torch.float16)
        self.pipe = StableDiffusionXLControlNetPipeline.from_pretrained(
            MODEL, controlnet=cn, image_encoder=enc, torch_dtype=torch.float16,
            use_safetensors=True, add_watermarker=False).to("cuda")
        self.pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(self.pipe.scheduler.config)
        self.pipe.load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models",
                                  weight_name="ip-adapter-plus_sdxl_vit-h.safetensors")
        self.pipe.set_progress_bar_config(disable=True)

    @modal.method()
    def gen(self, prompt, neg, orig_b64, seed, ref_b64, cn_scale=0.7, ip_scale=0.55, steps=28):
        import cv2
        import numpy as np
        from PIL import Image
        orig = Image.open(io.BytesIO(base64.b64decode(orig_b64))).convert("RGB")
        w, h = orig.size                                  # 元アスペクトを SDXL 寸法へ
        lng = 1216
        W, H = (lng, int(lng * h / w)) if w >= h else (int(lng * w / h), lng)
        W, H = max(512, (W // 8) * 8), max(512, (H // 8) * 8)
        g0 = np.array(orig.resize((W, H)).convert("L"))
        g0 = cv2.bilateralFilter(g0, 7, 60, 60)           # トーン点を均して主線を残す
        canny = cv2.Canny(g0, 90, 190)
        cn_img = Image.fromarray(np.stack([canny] * 3, -1))
        ref = Image.open(io.BytesIO(base64.b64decode(ref_b64))).convert("RGB")
        self.pipe.set_ip_adapter_scale(float(ip_scale))
        gen = self.torch.Generator("cuda").manual_seed(int(seed))
        out = self.pipe(prompt=prompt, negative_prompt=neg, image=cn_img,
                        controlnet_conditioning_scale=float(cn_scale), ip_adapter_image=ref,
                        width=W, height=H, num_inference_steps=int(steps), guidance_scale=7.0,
                        generator=gen).images[0]

        def _j(im):
            bb = io.BytesIO()
            im.convert("RGB").save(bb, "JPEG", quality=92)
            return bb.getvalue()
        return _j(out), _j(cn_img)


CN_DEPTH = "diffusers/controlnet-depth-sdxl-1.0"

# shot → 構図(framing)言語。canny で旧構図をなぞる代わりに、シーンごとの構図を
# プロンプト + depth で設計する(構図再設計)。
COMPOSE = {
    "ECU": "extreme close-up, face fills frame, intense detailed eyes, shallow depth of field",
    "CU":  "close-up portrait, head and shoulders, rule of thirds, soft background bokeh",
    "MCU": "medium close-up, chest up, three-quarter view, cinematic framing",
    "MS":  "medium shot, upper body, balanced composition, environmental context",
    "MLS": "medium long shot, full body, character in lower frame, depth layers",
    "LS":  "wide long shot, small full-body figure in lower third, vast environment, "
           "atmospheric perspective, cinematic establishing composition",
    "WS":  "wide establishing shot, tiny figure dwarfed by scenery, low horizon, "
           "expansive background, cinematic wide angle, sense of place and air",
    "OTS": "over-the-shoulder shot, foreground shoulder framing, facing character in focus",
    "insert": "insert close-up of object, detailed, shallow focus",
    "POV": "first-person point of view shot, immersive perspective",
}


def _compose_tag(shot):
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from compose_blueprint import _shot_key
    return COMPOSE.get(_shot_key(shot), COMPOSE["MS"])


# shot 別 (cn_scale, ip_scale): 引き(WS/LS)は depth で構図を支配し顔の引きを抑える、
# 寄り(CU/ECU)は逆に depth を弱め IPAdapter で identity を効かせる。構図破綻の主因
# (IPAdapter の顔ポートレート偏重)を shot ごとに調整する。
SHOT_STRENGTH = {
    "WS":  (0.90, 0.22), "LS": (0.85, 0.28), "MLS": (0.72, 0.40), "POV": (0.85, 0.25),
    "MS":  (0.58, 0.50), "MCU": (0.52, 0.55), "insert": (0.70, 0.35),
    "CU":  (0.42, 0.60), "ECU": (0.36, 0.62), "OTS": (0.60, 0.50),
}


def _shot_strength(shot, cn_def, ip_def):
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from compose_blueprint import _shot_key
    return SHOT_STRENGTH.get(_shot_key(shot), (cn_def, ip_def))


@app.cls(gpu="L40S", image=cn_image, volumes={"/cache/hf": hf_cache},
         secrets=[modal.Secret.from_name("huggingface")],
         timeout=1800, scaledown_window=120)
class Method4:
    """方法④(構図再設計): シーン構図設計図(depth blueprint, ARIA実アスペクト)を
    ControlNet-depth で『人物と地面の配置』だけ拘束し、線は再生成。canny の旧構図/旧
    アスペクト引きずりを排除。identity は IPAdapter。"""
    @modal.enter()
    def load(self):
        import torch
        from diffusers import (ControlNetModel, EulerAncestralDiscreteScheduler,
                               StableDiffusionXLControlNetPipeline)
        from transformers import CLIPVisionModelWithProjection
        self.torch = torch
        enc = CLIPVisionModelWithProjection.from_pretrained(
            "h94/IP-Adapter", subfolder="models/image_encoder", torch_dtype=torch.float16)
        cn = ControlNetModel.from_pretrained(CN_DEPTH, torch_dtype=torch.float16)
        self.pipe = StableDiffusionXLControlNetPipeline.from_pretrained(
            MODEL, controlnet=cn, image_encoder=enc, torch_dtype=torch.float16,
            use_safetensors=True, add_watermarker=False).to("cuda")
        self.pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(self.pipe.scheduler.config)
        self.pipe.load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models",
                                  weight_name="ip-adapter-plus_sdxl_vit-h.safetensors")
        self.pipe.set_progress_bar_config(disable=True)

    @modal.method()
    def gen(self, prompt, neg, depth_b64, W, H, seed, ref_b64, cn_scale=0.55,
            ip_scale=0.5, steps=30):
        from PIL import Image
        depth = Image.open(io.BytesIO(base64.b64decode(depth_b64))).convert("RGB").resize((W, H))
        ref = Image.open(io.BytesIO(base64.b64decode(ref_b64))).convert("RGB")
        self.pipe.set_ip_adapter_scale(float(ip_scale))
        gen = self.torch.Generator("cuda").manual_seed(int(seed))
        out = self.pipe(prompt=prompt, negative_prompt=neg, image=depth,
                        controlnet_conditioning_scale=float(cn_scale), ip_adapter_image=ref,
                        width=W, height=H, num_inference_steps=int(steps), guidance_scale=7.0,
                        generator=gen).images[0]
        bb = io.BytesIO()
        out.convert("RGB").save(bb, "JPEG", quality=92)
        return bb.getvalue()


@app.cls(image=seg_image, volumes={"/cache/hf": hf_cache}, cpu=4.0,
         timeout=1800, scaledown_window=120)
class Aesthetic:
    """imgutils のアニメ美的スコア — best-of-N の客観選択に使う(0=worst..6=masterpiece)。"""
    _ORDER = {"worst": 0, "low": 1, "normal": 2, "good": 3, "great": 4,
              "best": 5, "masterpiece": 6}

    @modal.enter()
    def load(self):
        from imgutils.metrics import anime_dbaesthetic
        from PIL import Image as _I
        self._a = anime_dbaesthetic
        self._a(_I.new("RGB", (64, 64)))                  # warm/DL

    @modal.method()
    def score(self, img_b64):
        from PIL import Image
        im = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")
        try:
            res = self._a(im)                             # 既定: (label, percentile)
            if isinstance(res, tuple):
                rating = res[0]
                extra = res[1] if len(res) > 1 else 0
                pct = extra.get(rating, 0) if isinstance(extra, dict) else float(extra)
            else:
                rating, pct = res, 0.0
            return self._ORDER.get(rating, 2) + float(pct)
        except Exception as e:
            print("aesthetic error:", e)
            return 2.0


@app.cls(image=seg_image, volumes={"/cache/hf": hf_cache}, cpu=4.0,
         timeout=1800, scaledown_window=120)
class IdentifyFaces:
    """CCIP(アニメキャラ同一性)で検出顔をキャラ参照に同定 → face↔character 紐付け。"""
    @modal.enter()
    def load(self):
        from imgutils.metrics import ccip_default_threshold, ccip_extract_feature
        from PIL import Image as _I
        self._extract = ccip_extract_feature
        self._thr = ccip_default_threshold()
        self._extract(_I.new("RGB", (64, 64)))            # warm/DL

    @modal.method()
    def extract_refs(self, refs_b64):
        from PIL import Image
        out = {}
        for n, b in refs_b64.items():
            im = Image.open(io.BytesIO(base64.b64decode(b))).convert("RGB")
            out[n] = self._extract(im).tolist()
        return out

    @modal.method()
    def identify(self, img_b64, faces, reffeat, candidates=None):
        import numpy as np
        from imgutils.metrics import ccip_difference
        from PIL import Image
        im = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")
        W, H = im.size
        cand = candidates or list(reffeat)                # パネル登場キャラに限定すると精度↑
        rf = {n: np.array(reffeat[n], dtype="float32") for n in cand if n in reffeat}
        thr = self._thr * (1.6 if candidates else 1.0)    # 候補を絞れば閾値を緩める
        labels = []
        for f in faces:
            x, y, w, h = f[:4]
            ex, ey = int(w * 0.6), int(h * 0.7)           # 上半身まで広げると CCIP 精度↑
            crop = im.crop((max(0, x - ex), max(0, y - ey),
                            min(W, x + w + ex), min(H, y + h + ey)))
            try:
                ff = self._extract(crop)
                best, bd = "", 9e9
                for n, v in rf.items():
                    dd = float(ccip_difference(ff, v))
                    if dd < bd:
                        bd, best = dd, n
                labels.append(best if bd < thr else "")
            except Exception:
                labels.append("")
        return labels


@app.local_entrypoint()
def identify(faces_json: str = "/tmp/m3-faces.json", out: str = "/tmp/m3-faces-id.json"):
    """faces キャッシュの各顔を CCIP でキャラ同定 → faces を [x,y,w,h,dir,character] に拡張。"""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    refsdir = os.path.join(base, "data/ghosthacker/character-refs")
    refb64 = {n: base64.b64encode(open(os.path.join(refsdir, f"{n}.png"), "rb").read()).decode()
              for n in ("yuto", "ren", "nei", "akira", "saki", "mei", "daemon")}
    # 画像ファイル名 p{N}-panel{M} → manifest の登場キャラ(候補)を引く
    import re as _re
    m = json.load(open(os.path.join(
        base, "data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")))
    mp = {(p["pageNum"], p.get("panelIndex")): [c.lower() for c in (p.get("characters") or [])]
          for p in m["panels"]}

    def _cand(path):
        mt = _re.search(r"p(\d+)-panel(\d+)", os.path.basename(path))
        return mp.get((int(mt.group(1)), int(mt.group(2)))) if mt else None

    cache = json.load(open(faces_json))
    idf = IdentifyFaces()
    reffeat = idf.extract_refs.remote(refb64)
    paths = [p for p in cache if cache[p].get("faces")]
    jobs = [(base64.b64encode(open(p, "rb").read()).decode(), cache[p]["faces"], reffeat, _cand(p))
            for p in paths]
    print(f"identifying faces on {len(paths)} panels (CCIP)…")
    for p, labels in zip(paths, idf.identify.starmap(jobs)):
        cache[p]["faces"] = [list(f[:5]) + [lab] for f, lab in zip(cache[p]["faces"], labels)]
    json.dump(cache, open(out, "w"))
    nid = sum(1 for v in cache.values() for f in v.get("faces", []) if len(f) > 5 and f[5])
    nt = sum(len(v.get("faces", [])) for v in cache.values())
    print(f"done: {nid}/{nt} faces identified -> {out}")


def _panel_prompt(panel):
    chars = panel.get("characters") or panel.get("allCharacters") or []
    chars = [c for c in chars if c in CHAR][:3]
    # 焦点キャラ優先で並べる(主役を先頭に → 属性ブリードを減らす)
    fc = panel.get("focusCharacter")
    if fc in chars:
        chars = [fc] + [c for c in chars if c != fc]
    cnt_b = sum(1 for c in chars if GENDER[c] == "1boy")
    cnt_g = sum(1 for c in chars if GENDER[c] == "1girl")
    lead = []
    if cnt_b:
        lead.append({1: "1boy", 2: "2boys"}.get(cnt_b, "multiple boys"))
    if cnt_g:
        lead.append({1: "1girl", 2: "2girls"}.get(cnt_g, "multiple girls"))
    # 性別の明示(Animagine は girl 偏重なので男子は male focus を強める)
    focus = "male focus" if (cnt_b and cnt_b >= cnt_g) else "female focus"
    male_neg = ", breasts, cleavage, 1girl" if focus == "male focus" else ""
    # 性別タグ先頭 + 説明(括弧/性別接頭辞なし)で属性を明確化
    who = ", ".join(CHAR[c] for c in chars) or "japanese teen"
    shot_tag, w, h = SHOT.get(panel.get("shot", "medium"), SHOT["medium"])
    subj = panel.get("sceneSubject", "")
    prompt = (QUALITY + ", ".join(lead) + f", {focus}, " + who
              + f", {shot_tag}, {SCENE}, " + (f"{subj}, " if subj else "") + STYLE)
    return prompt, NEG + male_neg, w, h


# IPAdapter 用キャラ固定リファレンス (正面・ニュートラル・上半身・無地背景)。
# (name -> gender, desc, fixed_seed)。男子は学生服(黒詰襟 gakuran)。
REF = {
    "yuto":  ("1boy", "17 year old japanese teen boy, neat short black hair, calm dark eyes, "
              "black gakuran high-collar school uniform, slim, gentle serious face", 704),
    "ren":   ("1boy", "17 year old japanese teen boy, messy black hair with subtle blue "
              "highlights, sleepy half-lidded tired eyes, pale skin, black gakuran high-collar "
              "school uniform, calm aloof face", 705),
    "akira": ("1boy", "17 year old japanese teen boy, short brown hair, mischievous friendly "
              "eyes, black gakuran high-collar school uniform, lively face", 700),
    "nei":   ("1girl", "16 year old japanese teen girl, long straight platinum blonde hair, "
              "blue eyes, navy sailor uniform with red ribbon, elegant calm face", 702),
    "saki":  ("1girl", "16 year old japanese teen girl, shoulder-length brown bob hair, "
              "skeptical calm eyes, navy sailor uniform", 703),
    "mei":   ("1girl", "16 year old japanese teen girl, black hair in a high ponytail, "
              "bright cheerful eyes, navy sailor uniform", 701),
    "daemon": ("1other", "dark digital demon entity, black hooded cloak, glowing cyan "
               "circuit-pattern eyes, glitch corruption aura, menacing cyber spectre, "
               "dark background", 706),
}


@app.local_entrypoint()
def refs(only: str = ""):
    """各キャラの固定用リファレンス顔を生成 (front/neutral/plain bg)。--only "yuto,ren,akira"
    で対象を絞れる(他キャラの seed/見た目を変えない)。"""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    outdir = os.path.join(base, "data/ghosthacker/character-refs")
    os.makedirs(outdir, exist_ok=True)
    sel = [n.strip() for n in only.split(",") if n.strip()] or list(REF)
    framing = ("front view, looking at viewer, neutral expression, upper body portrait, "
               "simple plain white background, character reference, clean lighting, detailed face")
    r = Renderer()
    jobs, names = [], []
    for name in sel:
        g, desc, s = REF[name]
        prompt = QUALITY + f"{g}, solo, " + desc + ", " + framing + ", " + STYLE
        neg = NEG + (", breasts, cleavage, 1girl" if g == "1boy" else "")
        jobs.append((prompt, neg, 832, 1216, s))
        names.append(name)
    print(f"generating {len(jobs)} character refs (Animagine XL 4.0): {names}")
    for name, png in zip(names, r.render.starmap(jobs)):
        fn = os.path.join(outdir, f"{name}.png")
        open(fn, "wb").write(png)
        print(f"  {name} -> {fn}")
    print(f"done. refs in {outdir}")


# shot 別 IPAdapter scale: 寄り=identity 強め / 引き=composition 優先で弱め。
# (ip-adapter-plus は参照の構図まで引っ張るので、引きほど下げて prompt を効かせる)
SHOT_IP = {
    "Extreme Close Up": 0.50, "close up": 0.45, "Close Up": 0.45, "Insert": 0.22,
    "Medium": 0.34, "medium": 0.34, "film-medium": 0.34, "Over the Shoulder": 0.34,
    "Wide": 0.20, "wide": 0.20,
}


@app.local_entrypoint()
def pages(pages: str = "0,1,2", seed: int = 251123, scale: float = 1.0):
    """p0/p1/p2 を IPAdapter でキャラ固定して再生成。各パネルは focusCharacter の
    リファレンスを参照(無ければ登場キャラの先頭)。IPAdapter scale は shot 別
    (SHOT_IP × --scale)で、寄りは強く引きは弱くして構図を保つ。出力 /tmp/ip-render/pN/。"""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    m = json.load(open(os.path.join(
        base, "data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")))
    refsdir = os.path.join(base, "data/ghosthacker/character-refs")
    refb64 = {n: base64.b64encode(open(os.path.join(refsdir, f"{n}.png"), "rb").read()).decode()
              for n in ("yuto", "ren", "nei", "akira", "saki", "mei", "daemon")}
    want = [int(x) for x in pages.split(",")]
    r = IPRenderer()
    for pn in want:
        panels = sorted([p for p in m["panels"] if p["pageNum"] == pn],
                        key=lambda z: z.get("panelIndex", 0))
        jobs, metas = [], []
        for p in panels:
            prompt, neg, w, h = _panel_prompt(p)
            fc = (p.get("focusCharacter") or "").lower()
            if fc not in refb64:                       # shared/unknown → 登場キャラ先頭
                cand = [c.lower() for c in (p.get("characters") or []) if c.lower() in refb64]
                fc = cand[0] if cand else "yuto"
            ip = round(SHOT_IP.get(p.get("shot", "medium"), 0.34) * scale, 3)
            jobs.append((prompt, neg, w, h, seed + p.get("panelIndex", 0), refb64[fc], ip))
            metas.append((pn, p.get("panelIndex"), fc, p.get("shot"), ip))
        outdir = f"/tmp/ip-render/p{pn}"
        os.makedirs(outdir, exist_ok=True)
        print(f"p{pn}: rendering {len(jobs)} IPAdapter panels (scale ×{scale})…")
        for (pn_, idx, fc, shot, ip), png in zip(metas, r.render.starmap(jobs)):
            open(f"{outdir}/p{pn_}-panel{idx}.png", "wb").write(png)
            print(f"  p{pn_} panel{idx} [{shot}] ref={fc} ip={ip}")
    print("done -> /tmp/ip-render/")


@app.local_entrypoint()
def method2(pages: str = "0,1,2", seed: int = 251123, ip_scale: float = 0.75):
    """方法②: シーン先行→人物mask→identity更新 で p0/p1/p2 を生成。
    出力 /tmp/m2-render/pN/ (panel=最終, -scene/-mask は中間)。"""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    m = json.load(open(os.path.join(
        base, "data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")))
    refsdir = os.path.join(base, "data/ghosthacker/character-refs")
    refb64 = {n: base64.b64encode(open(os.path.join(refsdir, f"{n}.png"), "rb").read()).decode()
              for n in ("yuto", "ren", "nei", "akira", "saki", "mei", "daemon")}
    r = Method2()
    for pn in [int(x) for x in pages.split(",")]:
        panels = sorted([p for p in m["panels"] if p["pageNum"] == pn],
                        key=lambda z: z.get("panelIndex", 0))
        jobs, metas = [], []
        for p in panels:
            scene_prompt, neg, w, h = _panel_prompt(p)
            fc = (p.get("focusCharacter") or "").lower()
            if fc not in refb64:
                cand = [c.lower() for c in (p.get("characters") or []) if c.lower() in refb64]
                fc = cand[0] if cand else "yuto"
            g = GENDER.get(fc.capitalize(), "1boy")
            idp = (QUALITY + f"{g}, solo, " + CHAR.get(fc.capitalize(), "") +
                   ", detailed face, upper body, " + STYLE)
            jobs.append((scene_prompt, idp, neg, w, h, seed + p.get("panelIndex", 0),
                         refb64[fc], ip_scale))
            metas.append((pn, p.get("panelIndex"), fc, p.get("shot")))
        outdir = f"/tmp/m2-render/p{pn}"
        os.makedirs(outdir, exist_ok=True)
        print(f"p{pn}: method2 on {len(jobs)} panels (ip_scale {ip_scale})…")
        for (pn_, idx, fc, shot), (scene, out) in zip(metas, r.gen.starmap(jobs)):
            open(f"{outdir}/p{pn_}-panel{idx}.jpg", "wb").write(out)
            open(f"{outdir}/p{pn_}-panel{idx}-scene.jpg", "wb").write(scene)
            print(f"  p{pn_} panel{idx} [{shot}] ref={fc}")
    print("done -> /tmp/m2-render/")


@app.local_entrypoint()
def method3(pages: str = "0,1,2", seed: int = 251123, cn_scale: float = 0.7,
            ip_scale: float = 0.55, steps: int = 28):
    """方法③: 正規版パネルの canny を ControlNet で構図ロック + IPAdapter で identity。
    正規版の構図を再現する。出力 /tmp/m3-render/pN/ (panel=最終, -canny=制御線画)。"""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sb = json.load(open(os.path.join(
        base, "data/ghosthacker/resources/episodes/arc0-1-origin/storyboard.komawari.page.json")))
    refsdir = os.path.join(base, "data/ghosthacker/character-refs")
    refb64 = {n: base64.b64encode(open(os.path.join(refsdir, f"{n}.png"), "rb").read()).decode()
              for n in ("yuto", "ren", "nei", "akira", "saki", "mei", "daemon")}
    _renc = os.path.join(refsdir, "ren-tshirt-original.png")    # 私服 Ren(家シーン用)
    ren_casual = (base64.b64encode(open(_renc, "rb").read()).decode()
                  if os.path.exists(_renc) else refb64["ren"])
    m = json.load(open(os.path.join(
        base, "data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")))
    mpanels = {(p["pageNum"], p.get("panelIndex")): p for p in m["panels"]}
    r = Method3()
    for pn in [int(x) for x in pages.split(",")]:
        pg = [p for p in sb["pages"] if p["pageNum"] == pn][0]
        panels = sorted(pg["panels"], key=lambda z: z["order"])
        jobs, metas = [], []
        for i, p in enumerate(panels):
            orig = p.get("_imagePath")
            if not orig or not os.path.exists(orig):
                continue
            mp = mpanels.get((pn, i + 1), {})              # 同 panelIndex の manifest 情報
            prompt, neg, _, _ = _panel_prompt(mp or {"shot": p.get("shot", {}).get("scale")})
            fc = (mp.get("focusCharacter") or "").lower()
            if fc not in refb64:
                cand = [c.lower() for c in (mp.get("characters") or []) if c.lower() in refb64]
                fc = cand[0] if cand else "yuto"
            ref = refb64[fc]
            title = mp.get("pageTitle", "") or ""
            if any(kw in title for kw in ("部屋", "自宅", "room", "Room", "bedroom", "の家")):
                prompt = (prompt
                          .replace("black gakuran high-collar school uniform",
                                   "casual t-shirt and hoodie, relaxed home clothes")
                          .replace("navy sailor uniform with red ribbon", "casual home clothes")
                          .replace("navy sailor uniform", "casual home clothes")
                          + ", at home, private room")
                if fc == "ren":
                    ref = ren_casual                       # 私服 Ren ref
            ob = base64.b64encode(open(orig, "rb").read()).decode()
            jobs.append((prompt, neg, ob, seed + i, ref, cn_scale, ip_scale, steps))
            metas.append((pn, i + 1, fc))
        outdir = f"/tmp/m3-render/p{pn}"
        os.makedirs(outdir, exist_ok=True)
        print(f"p{pn}: method3 (ControlNet-canny) on {len(jobs)} panels "
              f"(cn {cn_scale} ip {ip_scale})…")
        for (pn_, idx, fc), (out, canny) in zip(metas, r.gen.starmap(jobs)):
            open(f"{outdir}/p{pn_}-panel{idx}.jpg", "wb").write(out)
            open(f"{outdir}/p{pn_}-panel{idx}-canny.jpg", "wb").write(canny)
            print(f"  p{pn_} panel{idx} ref={fc}")
    print("done -> /tmp/m3-render/")


STYLE_ANCHOR = (
    "consistent unified art style across the whole page, single-artist cohesion, crisp modern "
    "anime cel shading, clean thin even line weight, cohesive cool color grade (teal and indigo "
    "with magenta accents), dramatic rim lighting, flat anime coloring")


@app.local_entrypoint()
def pipeline(pages: str = "0", compmodel: str = "gemini-3.1-flash", compstyle: str = "manga",
             compdir: str = "", outdir: str = "/tmp/pipe-render", styleanchor: str = STYLE_ANCHOR,
             seed: int = 251123, cn_scale: float = 0.62, ip_scale: float = 0.5, steps: int = 28):
    """構図/cut → canny ControlNet → Animagine(IPAdapter identity)。compdir 指定時は
    {compdir}/p{N}-panels/p{N}-panel{o}.png を canny 源にする(cut keyframe 用)。
    出力 {outdir}/pN/。"""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    epdir = os.path.join(base, "data/ghosthacker/resources/episodes/arc0-1-origin")
    refsdir = os.path.join(base, "data/ghosthacker/character-refs")
    refb64 = {n: base64.b64encode(open(os.path.join(refsdir, f"{n}.png"), "rb").read()).decode()
              for n in ("yuto", "ren", "nei", "akira", "saki", "mei", "daemon")}
    m = json.load(open(os.path.join(epdir, "image-gen-manifest.json")))
    mpanels = {(p["pageNum"], p.get("panelIndex")): p for p in m["panels"]}
    cdir0 = (f"/tmp/orcmp/{compmodel}" if compstyle == "manga"
             else f"/tmp/orcmp/{compstyle}__{compmodel}")
    import shutil

    def _is_graphic(mp, scale):
        """グラフィック/抽象コマ判定 — タイトル/通知/スマホ画面/insert/無キャラ は Animagine が
        崩すので gemini cut keyframe をそのまま採用する(ControlNet→Animagine をスキップ)。"""
        subj = ((mp.get("sceneSubject") or "") + " " + (mp.get("visual") or "")).lower()
        kw = ("title", "notification", "logo", "screen", "drop", "text overlay", "通知",
              "タイトル", "ロゴ", "画面")
        if (scale or "").lower() == "insert":
            return True
        if any(k in subj for k in kw):
            return True
        if not (mp.get("characters") or []):
            return True
        return False

    r = Method3()
    for pn in [int(x) for x in pages.split(",")]:
        srcdir = f"{compdir}/p{pn}-panels" if compdir else cdir0
        idxs = sorted(int(re.search(r"panel(\d+)", os.path.basename(f)).group(1))
                      for f in __import__("glob").glob(f"{srcdir}/p{pn}-panel*.png"))
        cutfile = f"/tmp/cuts/p{pn}.json"
        cutscale = {}
        if os.path.exists(cutfile):
            for c in json.load(open(cutfile)).get("cuts", []):
                cutscale[c.get("order")] = c.get("shot", {}).get("scale")
        od = f"{outdir}/p{pn}-panels" if compdir else f"{outdir}/p{pn}"
        os.makedirs(od, exist_ok=True)
        ext = "png" if compdir else "jpg"
        jobs, metas, kept = [], [], []
        for idx in idxs:
            comp = f"{srcdir}/p{pn}-panel{idx}.png"
            mp = mpanels.get((pn, idx), {})
            scale = cutscale.get(idx) or mp.get("shot")
            if compdir and _is_graphic(mp, scale):           # グラフィックコマ → gemini そのまま
                shutil.copy(comp, f"{od}/p{pn}-panel{idx}.{ext}")
                kept.append(idx)
                continue
            prompt, neg, _, _ = _panel_prompt(mp or {})
            prompt = prompt + ", " + _compose_tag((mp.get("shot") or "medium"))
            if styleanchor:                              # 全パネル共通スタイルで Animagine 統一
                prompt = prompt + ", " + styleanchor
            fc = (mp.get("focusCharacter") or "").lower()
            if fc not in refb64:
                cand = [c.lower() for c in (mp.get("characters") or []) if c.lower() in refb64]
                fc = cand[0] if cand else "yuto"
            ob = base64.b64encode(open(comp, "rb").read()).decode()
            jobs.append((prompt, neg, ob, seed + idx, refb64[fc], cn_scale, ip_scale, steps))
            metas.append((pn, idx, fc))
        print(f"p{pn}: {len(jobs)} char→Animagine, {len(kept)} graphic→gemini-direct {kept}")
        for (pn_, idx, fc), (out, canny) in zip(metas, r.gen.starmap(jobs)):
            open(f"{od}/p{pn_}-panel{idx}.{ext}", "wb").write(out)
            print(f"  p{pn_} panel{idx} ref={fc}")
    print(f"done -> {outdir}/")


import re  # noqa: E402 (pipeline entrypoint で使用)


@app.local_entrypoint()
def harmonize(pages: str = "37", indir: str = "/tmp/cleanfinal37", outdir: str = "/tmp/harm",
              strength: float = 0.32, seed: int = 4242, steps: int = 30):
    """仕上げ統一パス: {indir}/p{N}-panels の各パネルを Animagine img2img(低 denoise)で
    共通 style anchor に揃える。内容保持・画風 Animagine 統一。出力 {outdir}/p{N}-panels/。"""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    epdir = os.path.join(base, "data/ghosthacker/resources/episodes/arc0-1-origin")
    m = json.load(open(os.path.join(epdir, "image-gen-manifest.json")))
    mpanels = {(p["pageNum"], p.get("panelIndex")): p for p in m["panels"]}
    h = Harmonizer()
    for pn in [int(x) for x in pages.split(",")]:
        srcdir = f"{indir}/p{pn}-panels"
        idxs = sorted(int(re.search(r"panel(\d+)", os.path.basename(f)).group(1))
                      for f in __import__("glob").glob(f"{srcdir}/p{pn}-panel*.png"))
        jobs, metas = [], []
        for idx in idxs:
            mp = mpanels.get((pn, idx), {})
            # プロンプト = 共通 style anchor を先頭(統一を効かせる) + 軽いシーン語(内容保持)
            who = ", ".join(c for c in (mp.get("characters") or [])) or "character"
            prompt = STYLE_ANCHOR + f", {who}, {(mp.get('sceneSubject') or '')[:40]}, " + STYLE
            ob = base64.b64encode(open(f"{srcdir}/p{pn}-panel{idx}.png", "rb").read()).decode()
            jobs.append((ob, prompt, NEG, seed + idx, strength, steps))
            metas.append(idx)
        od = f"{outdir}/p{pn}-panels"
        os.makedirs(od, exist_ok=True)
        print(f"p{pn}: harmonize (Animagine img2img, denoise {strength}) on {len(jobs)} panels…")
        for idx, out in zip(metas, h.gen.starmap(jobs)):
            open(f"{od}/p{pn}-panel{idx}.png", "wb").write(out)
            print(f"  p{pn} panel{idx}")
    print(f"done -> {outdir}/")


@app.local_entrypoint()
def method4(pages: str = "6", seed: int = 251123, cn_scale: float = 0.55,
            ip_scale: float = 0.5, steps: int = 30):
    """方法④(構図再設計): シーン構図設計図(depth)を ControlNet-depth で配置拘束し、
    線は再生成。ARIA 実アスペクトで生成。出力 /tmp/m4-render/pN/(panel=最終, -depth=設計図)。"""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from compose_blueprint import _gaze_dir, _gen_dims, blueprint
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    epdir = os.path.join(base, "data/ghosthacker/resources/episodes/arc0-1-origin")
    sb = json.load(open(os.path.join(epdir, "storyboard.komawari.page.json")))
    refsdir = os.path.join(base, "data/ghosthacker/character-refs")
    refb64 = {n: base64.b64encode(open(os.path.join(refsdir, f"{n}.png"), "rb").read()).decode()
              for n in ("yuto", "ren", "nei", "akira", "saki", "mei", "daemon")}
    _renc = os.path.join(refsdir, "ren-tshirt-original.png")
    ren_casual = (base64.b64encode(open(_renc, "rb").read()).decode()
                  if os.path.exists(_renc) else refb64["ren"])
    m = json.load(open(os.path.join(epdir, "image-gen-manifest.json")))
    mpanels = {(p["pageNum"], p.get("panelIndex")): p for p in m["panels"]}
    r = Method4()
    for pn in [int(x) for x in pages.split(",")]:
        pg = [p for p in sb["pages"] if p["pageNum"] == pn][0]
        panels = sorted(pg["panels"], key=lambda z: z["order"])
        jobs, metas, depths = [], [], []
        for i, p in enumerate(panels):
            mp = mpanels.get((pn, i + 1), {})
            shot = (p.get("shot") or {}).get("scale") or "MS"
            prompt, neg, _, _ = _panel_prompt(mp or {"shot": shot})
            prompt = prompt + ", " + _compose_tag(shot)        # シーン構図を言語でも設計
            fc = (mp.get("focusCharacter") or "").lower()
            if fc not in refb64:
                cand = [c.lower() for c in (mp.get("characters") or []) if c.lower() in refb64]
                fc = cand[0] if cand else "yuto"
            ref = refb64[fc]
            title = mp.get("pageTitle", "") or ""
            if any(kw in title for kw in ("部屋", "自宅", "room", "Room", "bedroom", "の家")):
                prompt = (prompt.replace("black gakuran high-collar school uniform",
                                         "casual t-shirt and hoodie, relaxed home clothes")
                          .replace("navy sailor uniform with red ribbon", "casual home clothes")
                          .replace("navy sailor uniform", "casual home clothes") + ", at home")
                if fc == "ren":
                    ref = ren_casual
            w_, h_ = p.get("w", 500), p.get("h", 500)
            aspect = max(0.45, min(2.4, (w_ / 1000 * 182) / (h_ / 1000 * 257)))
            W, H = _gen_dims(aspect)
            nfaces = max(1, len(p.get("faces") or []) or len(mp.get("characters") or []) or 1)
            bp = blueprint(W, H, shot, _gaze_dir(p), nfaces, establishing=(w_ >= 930))
            bb = io.BytesIO(); bp.convert("RGB").save(bb, "PNG")
            dep = base64.b64encode(bb.getvalue()).decode()
            cn_s, ip_s = _shot_strength(shot, cn_scale, ip_scale)   # shot 適応強度
            jobs.append((prompt, neg, dep, W, H, seed + i, ref, cn_s, ip_s, steps))
            metas.append((pn, i + 1, fc, shot))
            depths.append(bp)
        outdir = f"/tmp/m4-render/p{pn}"
        os.makedirs(outdir, exist_ok=True)
        print(f"p{pn}: method4 (ControlNet-depth, 構図再設計) on {len(jobs)} panels "
              f"(cn {cn_scale} ip {ip_scale})…")
        for (pn_, idx, fc, shot), out, bp in zip(metas, r.gen.starmap(jobs), depths):
            open(f"{outdir}/p{pn_}-panel{idx}.jpg", "wb").write(out)
            bp.convert("RGB").save(f"{outdir}/p{pn_}-panel{idx}-depth.jpg", "JPEG")
            print(f"  p{pn_} panel{idx} ref={fc} shot={shot}")
    print("done -> /tmp/m4-render/")


@app.local_entrypoint()
def bestof(k: int = 30, variants: int = 2, seed: int = 251123):
    """best-of-N: 現行パネルをアニメ美的スコアで評価 → 最も崩れた k 枚を別シードで
    variants 回ずつ再生成し、美的スコアが上回ればその最良に差し替え(/tmp/m3-render)。"""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sb = json.load(open(os.path.join(
        base, "data/ghosthacker/resources/episodes/arc0-1-origin/storyboard.komawari.page.json")))
    m = json.load(open(os.path.join(
        base, "data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")))
    mpanels = {(p["pageNum"], p.get("panelIndex")): p for p in m["panels"]}
    refsdir = os.path.join(base, "data/ghosthacker/character-refs")
    refb64 = {n: base64.b64encode(open(os.path.join(refsdir, f"{n}.png"), "rb").read()).decode()
              for n in ("yuto", "ren", "nei", "akira", "saki", "mei", "daemon")}
    reg = []
    for pg in sb["pages"]:
        pn = pg["pageNum"]
        for i, p in enumerate(sorted(pg["panels"], key=lambda z: z["order"])):
            ppath = f"/tmp/m3-render/p{pn}/p{pn}-panel{i + 1}.jpg"
            orig = p.get("_imagePath")
            if not os.path.exists(ppath) or not orig or not os.path.exists(orig):
                continue
            mp = mpanels.get((pn, i + 1), {})
            prompt, neg, _, _ = _panel_prompt(mp or {})
            fc = (mp.get("focusCharacter") or "").lower()
            if fc not in refb64:
                cand = [c.lower() for c in (mp.get("characters") or []) if c.lower() in refb64]
                fc = cand[0] if cand else "yuto"
            reg.append((pn, i + 1, ppath, base64.b64encode(open(orig, "rb").read()).decode(),
                        prompt, neg, refb64[fc]))
    aes, m3 = Aesthetic(), Method3()
    print(f"scoring {len(reg)} panels (anime aesthetic)…")
    cur = list(aes.score.map([base64.b64encode(open(r[2], "rb").read()).decode() for r in reg]))
    worst = sorted(zip(cur, reg), key=lambda x: x[0])[:k]
    print(f"worst {k} aesthetic: {[round(s, 2) for s, _ in worst[:10]]}…")
    # variant ごとに生成設定(cn/ip)を振り、固定設定の品質 plateau を脱出する
    SETTINGS = [(0.65, 0.45), (0.80, 0.55), (0.72, 0.40), (0.70, 0.55), (0.60, 0.50)]
    vjobs, vmeta = [], []
    for cur_s, (pn, idx, ppath, ob, prompt, neg, ref) in worst:
        for v in range(variants):
            cn, ip = SETTINGS[v % len(SETTINGS)]
            vjobs.append((prompt, neg, ob, seed + 5000 * (v + 1) + idx, ref, cn, ip, 36))
            vmeta.append((pn, idx, ppath, cur_s))
    print(f"re-rolling {len(vjobs)} variants…")
    vouts = list(m3.gen.starmap(vjobs))
    vscores = list(aes.score.map([base64.b64encode(o[0]).decode() for o in vouts]))
    bypanel = {}
    for (pn, idx, ppath, cur_s), (out, _), vs in zip(vmeta, vouts, vscores):
        key = (pn, idx, ppath, cur_s)
        if key not in bypanel or vs > bypanel[key][0]:
            bypanel[key] = (vs, out)
    improved = 0
    for (pn, idx, ppath, cur_s), (vs, out) in bypanel.items():
        if vs > cur_s + 0.05:
            open(ppath, "wb").write(out)
            improved += 1
            print(f"  p{pn} panel{idx}: {cur_s:.2f} -> {vs:.2f}")
    print(f"best-of-N improved {improved}/{len(bypanel)} worst panels")


@app.local_entrypoint()
def facedetail(k: int = 40, faces_json: str = "/tmp/m3full-faces-id.json"):
    """フェイス・ディテーラ: 美的スコア最下位 k 枚の検出顔を inpaint で高精細化し、
    スコアが下がらなければ採用(/tmp/m3-render を上書き)。character_anatomy 軸を直撃。"""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sb = json.load(open(os.path.join(
        base, "data/ghosthacker/resources/episodes/arc0-1-origin/storyboard.komawari.page.json")))
    m = json.load(open(os.path.join(
        base, "data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")))
    mpanels = {(p["pageNum"], p.get("panelIndex")): p for p in m["panels"]}
    refsdir = os.path.join(base, "data/ghosthacker/character-refs")
    refb64 = {n: base64.b64encode(open(os.path.join(refsdir, f"{n}.png"), "rb").read()).decode()
              for n in ("yuto", "ren", "nei", "akira", "saki", "mei", "daemon")}
    fcache = json.load(open(faces_json))
    reg = []
    for pg in sb["pages"]:
        pn = pg["pageNum"]
        for i, p in enumerate(sorted(pg["panels"], key=lambda z: z["order"])):
            ppath = f"/tmp/m3-render/p{pn}/p{pn}-panel{i + 1}.jpg"
            faces = fcache.get(ppath, {}).get("faces", [])
            if not os.path.exists(ppath) or not faces:
                continue
            mp = mpanels.get((pn, i + 1), {})
            foc = (mp.get("focusCharacter") or "").lower()
            if foc not in refb64:
                cand = [c.lower() for c in (mp.get("characters") or []) if c.lower() in refb64]
                foc = cand[0] if cand else "yuto"
            reg.append((pn, i + 1, ppath, faces, refb64[foc], CHAR.get(foc.capitalize(), "")))
    aes, det = Aesthetic(), Method2()
    print(f"scoring {len(reg)} face-bearing panels…")
    cur = list(aes.score.map([base64.b64encode(open(r[2], "rb").read()).decode() for r in reg]))
    worst = sorted(zip(cur, reg), key=lambda x: x[0])[:k]
    print(f"face-detailing worst {len(worst)} panels…")
    jobs = [(base64.b64encode(open(r[2], "rb").read()).decode(), r[3], r[4], r[5])
            for _, r in worst]
    results = list(det.detail.starmap(jobs))
    newsc = list(aes.score.map([base64.b64encode(o[0]).decode() for o in results]))
    improved = 0
    for (cur_s, (pn, idx, ppath, *_)), (jpg, changed), ns in zip(worst, results, newsc):
        if changed and ns >= cur_s - 0.02:
            open(ppath, "wb").write(jpg)
            improved += 1
            print(f"  p{pn} panel{idx}: {cur_s:.2f} -> {ns:.2f}")
    print(f"face-detail kept {improved}/{len(worst)}")


@app.local_entrypoint()
def scorecmp(dirs: str = "/tmp/m3-render/p6,/tmp/m4-render/p6"):
    """複数の出力ディレクトリの panel*.jpg を anime_dbaesthetic で採点して比較する。"""
    import glob
    aes = Aesthetic()
    for d in dirs.split(","):
        files = sorted(f for f in glob.glob(f"{d}/**/*.jpg", recursive=True)
                       if "-depth" not in f and "-canny" not in f)
        if not files:
            print(f"{d}: (no panels)")
            continue
        b64 = [base64.b64encode(open(f, "rb").read()).decode() for f in files]
        sc = list(aes.score.map(b64))
        avg = sum(sc) / len(sc)
        worst = sorted(zip(files, sc), key=lambda z: z[1])[:3]
        print(f"\n{d}: {len(files)} panels  AESTHETIC avg {avg:.2f}")
        for f, s in zip(files, sc):
            print(f"   {os.path.basename(f):22s} {s:.2f}")
        print("   worst:", ", ".join(f"{os.path.basename(f)}={s:.2f}" for f, s in worst))


@app.local_entrypoint()
def main(seed: int = 251123):
    EP = "data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json"
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    m = json.load(open(os.path.join(base, EP)))
    p2 = sorted([p for p in m["panels"] if p["pageNum"] == 2],
                key=lambda z: z.get("panelIndex", 0))
    outdir = "/tmp/p2-render"
    os.makedirs(outdir, exist_ok=True)
    r = Renderer()
    jobs, metas = [], []
    for p in p2:
        prompt, neg, w, h = _panel_prompt(p)
        metas.append((p.get("panelIndex"), w, h, p.get("shot"), prompt))
        jobs.append((prompt, neg, w, h, seed + p.get("panelIndex", 0)))
    print(f"rendering {len(jobs)} p2 panels on Modal (Animagine XL 4.0, L40S, EulerA s20 cfg7)…")
    imgs = list(r.render.starmap(jobs))
    from PIL import Image
    saved = []
    for (idx, w, h, shot, prompt), png in zip(metas, imgs):
        fn = f"{outdir}/p2-panel{idx}.png"
        open(fn, "wb").write(png)
        saved.append((idx, w, h, Image.open(io.BytesIO(png))))
        print(f"  panel {idx} [{shot} {w}x{h}] -> {fn}")
    # contact sheet (4 cols)
    th = 360
    cols = 4
    rows = (len(saved) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (th + 8) + 8, rows * (th + 8) + 8), (24, 24, 28))
    for i, (idx, w, h, im) in enumerate(saved):
        t = im.copy()
        t.thumbnail((th, th))
        cx = 8 + (i % cols) * (th + 8) + (th - t.width) // 2
        cy = 8 + (i // cols) * (th + 8) + (th - t.height) // 2
        sheet.paste(t, (cx, cy))
    sheet.save(f"{outdir}/p2-contact.png")
    print(f"done -> {outdir}/p2-contact.png ({len(saved)} panels)")
