"""Upload SHIRO & PICO Episode 1 (ja/en/hi/ar) to YouTube (anime channel).

Raw OAuth (refresh-token → access-token) + resumable upload — no googleapiclient
needed. Credentials from k8s secret lg-yukkuri-youtube (anime channel uses
YOUTUBE_REFRESH_TOKEN_ANIME). Privacy via argv (default unlisted).

Usage: python3 shiropico-youtube-upload.py [privacy] [lang ...]
       privacy = unlisted|public|private (default unlisted)
       lang    = which versions (default: en hi ar ja)
"""
from __future__ import annotations
import base64, json, os, subprocess, sys
from pathlib import Path
import httpx

EP = Path(__file__).resolve().parents[2] / "data/ghosthacker-shiropico/resources/episode"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"

META = {
    "ja": {"file": "sp-ep01-v3-ja.mp4",
           "title": "SHIRO & PICO ゴーストハッカー｜第1話「オネムの暴走、ドバイの夜」",
           "desc": ("白帽ハッカーの少女シロと、天才だけど少し抜けてる少年ピコ。ネオン輝くドバイの夜、"
                    "無人カーが次々と眠りに落ちる怪事件——犯人は Zombie を操る何者か。\n\n"
                    "EDR で端末を隔離し、SIEM でログを相関させて、街を救え！倒すのではなく、救う。\n\n"
                    "#アニメ #サイバーセキュリティ #SHIROandPICO #GhostHacker"),
           "tags": ["アニメ", "サイバーセキュリティ", "SHIRO and PICO", "Ghost Hacker", "EDR", "SIEM"], "lang": "ja"},
    "en": {"file": "sp-ep01-v3-en.mp4",
           "title": "SHIRO & PICO — Ghost Hacker | Ep.1: Onem's Rampage, Dubai by Night",
           "desc": ("Shiro, a white-hat hacker girl, and Pico, a genius-but-goofy boy. In neon-lit "
                    "Dubai, self-driving cars fall asleep one by one — someone is commanding a Zombie.\n\n"
                    "Isolate the endpoints with EDR, correlate the logs with SIEM, and save the city! "
                    "Not destroy — protect.\n\n#anime #cybersecurity #SHIROandPICO #GhostHacker"),
           "tags": ["anime", "cybersecurity", "SHIRO and PICO", "Ghost Hacker", "EDR", "SIEM", "kids anime"], "lang": "en"},
    "hi": {"file": "sp-ep01-v3-hi.mp4",
           "title": "SHIRO & PICO — Ghost Hacker | भाग 1: ओनेम का कहर, दुबई की रात",
           "desc": ("Shiro, एक white-hat hacker लड़की, और Pico, एक जीनियस पर थोड़ा भोला लड़का। नियॉन से "
                    "जगमगाते दुबई में, self-driving कारें एक-एक करके सो रही हैं — कोई Zombie को चला रहा है।\n\n"
                    "EDR से endpoints अलग करो, SIEM से logs जोड़ो, और शहर को बचाओ! नष्ट नहीं — रक्षा।\n\n"
                    "#anime #cybersecurity #SHIROandPICO #GhostHacker"),
           "tags": ["anime", "cybersecurity", "SHIRO and PICO", "Ghost Hacker", "hindi anime"], "lang": "hi"},
    "ar": {"file": "sp-ep01-v3-ar.mp4",
           "title": "SHIRO & PICO — Ghost Hacker | الحلقة 1: هياج أونيم، دبي ليلاً",
           "desc": ("Shiro، فتاة هاكر أخلاقية، وPico، فتى عبقري لكنه طائش قليلاً. في دبي المضيئة بالنيون، "
                    "تغفو السيارات ذاتية القيادة واحدة تلو الأخرى — شخص ما يتحكم في Zombie.\n\n"
                    "اعزل الأجهزة بـ EDR، واربط السجلات بـ SIEM، وأنقذ المدينة! ليس التدمير — بل الحماية.\n\n"
                    "#anime #cybersecurity #SHIROandPICO #GhostHacker"),
           "tags": ["anime", "cybersecurity", "SHIRO and PICO", "Ghost Hacker", "arabic anime"], "lang": "ar"},
    "es": {"file": "sp-ep01-v3-es.mp4",
           "title": "SHIRO & PICO — Ghost Hacker | Ep.1: El caos de Onem, Dubái de noche",
           "desc": ("Shiro, una hacker de sombrero blanco, y Pico, un niño genio pero despistado. En el "
                    "Dubái de neón, los autos autónomos se duermen uno a uno: alguien controla un Zombie.\n\n"
                    "¡Aísla los dispositivos con EDR, correlaciona los registros con SIEM y salva la ciudad! "
                    "No destruir, sino proteger.\n\n#anime #ciberseguridad #SHIROandPICO #GhostHacker"),
           "tags": ["anime", "ciberseguridad", "SHIRO and PICO", "Ghost Hacker"], "lang": "es"},
    "fr": {"file": "sp-ep01-v3-fr.mp4",
           "title": "SHIRO & PICO — Ghost Hacker | Ép.1 : Le déchaînement d'Onem, Dubaï la nuit",
           "desc": ("Shiro, une hackeuse au chapeau blanc, et Pico, un garçon génie mais étourdi. Dans le "
                    "Dubaï néon, les voitures autonomes s'endorment une à une : quelqu'un commande un Zombie.\n\n"
                    "Isole les appareils avec EDR, corrèle les journaux avec SIEM, et sauve la ville ! "
                    "Pas détruire — protéger.\n\n#anime #cybersécurité #SHIROandPICO #GhostHacker"),
           "tags": ["anime", "cybersécurité", "SHIRO and PICO", "Ghost Hacker"], "lang": "fr"},
    "pt": {"file": "sp-ep01-v3-pt.mp4",
           "title": "SHIRO & PICO — Ghost Hacker | Ep.1: O caos de Onem, Dubai à noite",
           "desc": ("Shiro, uma hacker do bem, e Pico, um menino gênio mas distraído. Na Dubai de neon, "
                    "os carros autônomos dormem um a um — alguém controla um Zombie.\n\n"
                    "Isole os dispositivos com EDR, correlacione os logs com SIEM e salve a cidade! "
                    "Não destruir — proteger.\n\n#anime #cibersegurança #SHIROandPICO #GhostHacker"),
           "tags": ["anime", "cibersegurança", "SHIRO and PICO", "Ghost Hacker"], "lang": "pt"},
    "de": {"file": "sp-ep01-v3-de.mp4",
           "title": "SHIRO & PICO — Ghost Hacker | Folge 1: Onems Amoklauf, Dubai bei Nacht",
           "desc": ("Shiro, ein White-Hat-Hacker-Mädchen, und Pico, ein genialer, aber tollpatschiger Junge. "
                    "Im Neon-Dubai schlafen selbstfahrende Autos eins nach dem anderen ein — jemand steuert einen Zombie.\n\n"
                    "Isoliere die Geräte mit EDR, korreliere die Logs mit SIEM und rette die Stadt! "
                    "Nicht zerstören — beschützen.\n\n#anime #cybersicherheit #SHIROandPICO #GhostHacker"),
           "tags": ["anime", "cybersicherheit", "SHIRO and PICO", "Ghost Hacker"], "lang": "de"},
    "zh": {"file": "sp-ep01-v3-zh.mp4",
           "title": "SHIRO & PICO — Ghost Hacker | 第1集：欧念失控，迪拜之夜",
           "desc": ("白帽黑客女孩 Shiro 和天才却有点呆萌的男孩 Pico。霓虹迪拜之夜，无人驾驶汽车一辆辆睡着——"
                    "有人在操控 Zombie。\n\n用 EDR 隔离终端，用 SIEM 关联日志，拯救城市！不是消灭，而是守护。\n\n"
                    "#动画 #网络安全 #SHIROandPICO #GhostHacker"),
           "tags": ["动画", "网络安全", "SHIRO and PICO", "Ghost Hacker"], "lang": "zh"},
    "bn": {"file": "sp-ep01-v3-bn.mp4",
           "title": "SHIRO & PICO — Ghost Hacker | পর্ব ১: ওনেমের তাণ্ডব, রাতের দুবাই",
           "desc": ("Shiro, একজন white-hat hacker মেয়ে, আর Pico, একটি জিনিয়াস কিন্তু একটু বোকা ছেলে। "
                    "নিয়ন দুবাইয়ে self-driving গাড়িগুলো একে একে ঘুমিয়ে পড়ছে — কেউ একজন Zombie চালাচ্ছে।\n\n"
                    "EDR দিয়ে ডিভাইস আলাদা করো, SIEM দিয়ে log মেলাও, আর শহর বাঁচাও! ধ্বংস নয় — রক্ষা।\n\n"
                    "#anime #cybersecurity #SHIROandPICO #GhostHacker"),
           "tags": ["anime", "cybersecurity", "SHIRO and PICO", "Ghost Hacker"], "lang": "bn"},
    "ta": {"file": "sp-ep01-v3-ta.mp4",
           "title": "SHIRO & PICO — Ghost Hacker | பகுதி 1: ஓனெமின் கொந்தளிப்பு, இரவு துபாய்",
           "desc": ("Shiro, ஒரு white-hat hacker பெண், மற்றும் Pico, ஒரு மேதை ஆனால் கொஞ்சம் கவனமற்ற சிறுவன். "
                    "நியான் துபாயில் self-driving கார்கள் ஒவ்வொன்றாக தூங்குகின்றன — யாரோ ஒரு Zombie-ஐ இயக்குகிறார்கள்.\n\n"
                    "EDR மூலம் சாதனங்களைத் தனிமைப்படுத்து, SIEM மூலம் log-களை இணை, நகரத்தைக் காப்பாற்று! "
                    "அழிப்பது அல்ல — பாதுகாப்பது.\n\n#anime #cybersecurity #SHIROandPICO #GhostHacker"),
           "tags": ["anime", "cybersecurity", "SHIRO and PICO", "Ghost Hacker"], "lang": "ta"},
}


def creds():
    raw = subprocess.run(["kubectl", "get", "secret", "lg-yukkuri-youtube", "-n", "mitama-udf", "-o", "json"],
                         capture_output=True, text=True, check=True).stdout
    d = {k: base64.b64decode(v).decode() for k, v in json.loads(raw)["data"].items()}
    return d

def access_token(c, refresh):
    r = httpx.post(TOKEN_URL, data={"client_id": c["YOUTUBE_CLIENT_ID"], "client_secret": c["YOUTUBE_CLIENT_SECRET"],
                                    "refresh_token": refresh, "grant_type": "refresh_token"}, timeout=60)
    r.raise_for_status(); return r.json()["access_token"]

def upload(tok, mp4: Path, meta, privacy):
    body = {"snippet": {"title": meta["title"][:100], "description": meta["desc"], "tags": meta["tags"],
                        "categoryId": "1", "defaultLanguage": meta["lang"], "defaultAudioLanguage": meta["lang"]},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "embeddable": True}}
    size = mp4.stat().st_size
    init = httpx.post(UPLOAD_URL, headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                                           "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"},
                      content=json.dumps(body).encode("utf-8"), timeout=60)
    if init.status_code not in (200, 201):
        print(f"  init FAIL {init.status_code}: {init.text[:200]}"); return None
    loc = init.headers.get("location")
    with open(mp4, "rb") as f:
        put = httpx.put(loc, headers={"Authorization": f"Bearer {tok}", "Content-Type": "video/mp4", "Content-Length": str(size)},
                        content=f.read(), timeout=600)
    if put.status_code in (200, 201):
        vid = put.json()["id"]; print(f"  ✓ {meta['lang']}: https://youtu.be/{vid}  ({privacy})"); return vid
    print(f"  PUT FAIL {put.status_code}: {put.text[:200]}"); return None


def main():
    privacy = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("unlisted", "public", "private") else "unlisted"
    langs = [a for a in sys.argv[2:] if a in META] or ["en", "hi", "ar", "ja"]
    c = creds()
    refresh = c.get("YOUTUBE_REFRESH_TOKEN_ANIME") or c["YOUTUBE_REFRESH_TOKEN"]
    tok = access_token(c, refresh)
    print(f"uploading to anime channel, privacy={privacy}, langs={langs}")
    results = {}
    for lang in langs:
        m = META[lang]; mp4 = EP / m["file"]
        if not mp4.exists(): print(f"  {lang}: MISSING {mp4}"); continue
        print(f"[{lang}] {mp4.name} ({mp4.stat().st_size//1024//1024} MB)")
        vid = upload(tok, mp4, m, privacy)
        if vid: results[lang] = f"https://youtu.be/{vid}"
    print("RESULTS:", json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
