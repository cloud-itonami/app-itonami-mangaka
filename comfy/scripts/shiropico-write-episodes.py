"""Write the 12-episode SHIRO & PICO season scripts + translate to en/es/ar/hi.

Uses the canonical Murakumo API. Each episode follows the canonical format of
episode-01.md (OP → cold open → ピコのやらかし型 → シロの静フォロー → 変身バンク →
two-layer action → Cパート縦軸 → 図鑑コーナー → ED), tied to its cyber topic +
monster + やらかし anti-pattern, advancing the Ghost arc / ピコの成長.

Phase 1: generate episode-NN.md (Japanese) for eps 2–12 (ep1 already exists).
Phase 2: translate every episode to episode-NN.<lang>.md (en/es/ar/hi).
"""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path
import httpx

DIR = Path(__file__).resolve().parents[2] / "data/ghosthacker-shiropico"
EP_DIR = DIR / "episodes"; EP_DIR.mkdir(exist_ok=True)
LLM = f"{os.getenv('MURAKUMO_LLM_URL', 'https://api.murakumo.cloud/v1').rstrip('/')}/chat/completions"
HDR = {"Content-Type": "application/json"}
if key := (os.getenv("MURAKUMO_API_KEY") or os.getenv("GFTD_LLM_API_KEY")):
    HDR["Authorization"] = f"Bearer {key}"
MODEL = os.getenv("MURAKUMO_LLM_MODEL", "murakumo-main")

# 12-episode season map: (num, titleJP, cyber_topic, monster, yarakashi, arc_note)
EPISODES = [
    (1, "オネムの暴走、ドバイの夜", "EDR/XDR + SIEM", "Zombie", "対症療法（1台ずつ叩く）", "（既存）"),
    (2, "よみがえるアイツ", "永続化マルウェア除去 + フォレンジック(Mandiant)", "Daemon", "慌ててDaemonを再起動して復活させる", "ピコ、しつこさに苛立つ"),
    (3, "穴とケモノはちがう", "脅威インテリ vs 脆弱性管理(Tenable→Mandiant)", "Daemon+Ghostの影", "自社の穴探しの道具で敵を追って空振り", "Ghostの“におい”初登場"),
    (4, "アラートの森で迷子", "SIEM/SOAR 相関 + アラート疲れ対策", "Zombie大群", "アラートを全部クリックしてノイズに溺れる", "シロのSIEM見せ場"),
    (5, "ひとつの門", "ゼロトラスト SASE/ZTNA", "なりすましGhost", "「コイツ味方っしょ」と信用して通す", "境界崩壊、ピコ騙される"),
    (6, "鍵をなくすな", "IAM/PAM + MFA", "鍵泥棒（新怪物）", "パスワード使い回しで突破される", "ピコの過去の手癖が伏線に"),
    (7, "空に置いた鍵", "CNAPP クラウド設定ミス", "空島の穴（新怪物）", "クラウドに鍵を置きっぱなしにする", "ムンバイ編、街を守る"),
    (8, "見えない地図", "偵察 Nmap（守る側の自己健診）", "Ghostの斥候", "攻撃スキルを攻撃に使おうとする", "ピコ、力の使い道を学ぶ"),
    (9, "あの日の手癖", "ソーシャルエンジニアリング + 被害者支援", "過去のピコ自身（幻影）", "同情で例外を作り穴を開ける", "感情ピーク：被害者と再会・贖罪"),
    (10, "釣り針の街", "フィッシング/スミッシング対策", "化けるGhost", "見た目で信じてリンクを踏む", "ドバイ再訪、Ghost核心へ"),
    (11, "情報は、消えない", "data remanence / Ghost本体接触", "Ghost（本体）", "“消した”を信じて痕跡を見落とす", "Ghost初可視化、強さの提示"),
    (12, "守る力", "NIST CSF 成熟度（シーズン締め） + 総力戦", "Ghost+Daemon+Zombie総攻撃", "（集大成）一人で抱えて空回り→仲間を頼る", "第一決戦、ピコが対等に。最後の払い"),
]
LANGS = {"en": "English", "es": "Spanish (Latin American)", "ar": "Arabic (Modern Standard, Gulf-safe neutral terms)", "hi": "Hindi"}


async def _chat(client, system, user, max_tokens=7000):
    for attempt in range(4):
        try:
            r = await client.post(LLM, headers=HDR, timeout=300, json={
                "model": MODEL, "max_tokens": max_tokens, "temperature": 0.7,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
            if r.status_code < 400:
                return (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            print(f"  llm {r.status_code}: {r.text[:120]}")
        except Exception as exc:
            print(f"  llm exc a{attempt}: {exc}")
        await asyncio.sleep(8 * (attempt + 1))
    return ""


async def gen_episode(client, bible, fmt, ep):
    num, title, topic, monster, yarakashi, arc = ep
    out = EP_DIR / f"episode-{num:02d}.md"
    if num == 1 or out.exists():
        print(f"  ep{num}: skip (exists)"); return
    system = (
        "あなたは『SHIRO & PICO』(ゴーストハッカー) の脚本家です。以下のシリーズ設定資料に厳密に従い、"
        "第1話と同じ構成・トーン・フォーマットで各話のフル脚本を書きます。\n\n"
        "【シリーズ設定資料】\n" + bible[:6000] + "\n\n【第1話のフォーマット（これに倣う）】\n" + fmt[:4000])
    user = (
        f"第{num}話「{title}」のフル脚本をMarkdownで書いてください。\n"
        f"- 今日のサイバー: {topic}\n- 今回の怪物: {monster}\n- ピコのやらかし: {yarakashi}\n- 縦軸/成長: {arc}\n"
        "- 尺 約11分（本編10＋図鑑コーナー1）、7+/TV-Y7-FV。\n"
        "- 必ず含める: OP(共通) / コールドオープン / ピコのやらかしの型(イキり→やらかし→慌て) / "
        "シロの静フォロー＋変身バンク「シロピコ、オン！」/ 二層アクション(情報空間＋物理) / "
        "Cパート(Ghost縦軸＋ピコの成長の種まき) / 図鑑コーナー(30秒、実ツール/カテゴリ解説→ゆっくりサイバーch送客) / ED。\n"
        "- シロ=女の子(四国めたん声・冷静)、ピコ=男の子(ずんだもん声・元気で少し抜けてる天才キッズ、たまにキラッと)。\n"
        "- 倒す≠救う、流血・恐怖・宗教/オカルト意匠なし。台詞は自然な日本語で、技名・溜め・解放・余韻のアクション作法を入れる。")
    body = await _chat(client, system, user)
    if body:
        out.write_text(body); print(f"  ep{num}: written ({len(body)} chars)")
    else:
        print(f"  ep{num}: FAILED")


async def translate_episode(client, num, lang_code, lang_name):
    src = EP_DIR / f"episode-{num:02d}.md"
    if not src.exists():
        src = DIR / "episode-01.md" if num == 1 else None
    if not src or not src.exists():
        return
    out = EP_DIR / f"episode-{num:02d}.{lang_code}.md"
    if out.exists():
        return
    system = (
        f"You are a professional anime script translator localizing into {lang_name} for a 7+ kids "
        "cyber-action series aired worldwide. Translate the script faithfully, keeping the Markdown "
        "structure, scene headers, character names (SHIRO, PICO), technique names, and the cyber-tool "
        "education. Keep cybersecurity terms (EDR, SIEM, Ghost, Daemon, Zombie, MFA, Zero Trust) as-is. "
        "For Arabic, avoid religiously heavy words (use neutral tech phrasing; عفريت/مارد not شيطان for 'demon').")
    body = await _chat(client, system, f"Translate this episode script to {lang_name}:\n\n{src.read_text()[:12000]}")
    if body:
        out.write_text(body); print(f"  ep{num}.{lang_code}: written")


async def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    bible = (DIR / "SERIES-BIBLE.md").read_text()
    fmt = (DIR / "episode-01.md").read_text()
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient() as client:
        async def guarded(coro):
            async with sem: return await coro
        if phase in ("all", "scripts"):
            print("=== Phase 1: generate episodes 2–12 ===")
            await asyncio.gather(*[guarded(gen_episode(client, bible, fmt, ep)) for ep in EPISODES])
        if phase in ("all", "translate"):
            print("=== Phase 2: translate all to en/es/ar/hi ===")
            tasks = [guarded(translate_episode(client, num, lc, ln))
                     for num, *_ in EPISODES for lc, ln in LANGS.items()]
            await asyncio.gather(*tasks)
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
