"""v11 — Sui Ishida (石田スイ) / Tokyo Ghoul (東京喰種) style profile.

Characteristics:
  - Sharp triangular shadow hatching
  - Dark moody urban atmosphere
  - Asymmetric heavy ink
  - Intense emotional eyes (often shaded heavily)
  - Quick sketchy linework with rough confident strokes
  - Cool dark palette (color) / heavy black + screentone (mono)
"""

QUALITY_INK = (
    "professional Japanese manga panel, monochrome B&W only, "
    "Sui Ishida Tokyo Ghoul aesthetic, sharp triangular shadow hatching, "
    "asymmetric heavy ink, intense moody expression, sketchy confident strokes, "
    "dark urban atmosphere, dense screentone with high contrast, "
)
QUALITY_COLOR = (
    "masterpiece, best quality, dark moody manga aesthetic, "
    "cool dark palette, intense atmospheric lighting, "
    "Sui Ishida color page style, "
)

NEG_INK = (
    "color, watercolor, photograph, sepia, pastel, cute chibi, "
    "low quality, blurry, deformed, multiple people, twin, multiple faces, "
    "soft gentle mood, washed gray, light bright, "
    "Witch Watch style, Aria style, sunshine, healing"
)
NEG_COLOR = (
    "lowres, bad anatomy, bad hands, blurry, watermark, signature, "
    "2girls, 2boys, twin, group, "
    "pastel, soft, washed out, bright sunshine"
)

SCENE_INK = {
    "yuto-bedroom": (
        "Japanese teen bedroom interior, single bed with twisted sheets, "
        "study desk with smartphone, punk posters on wall, "
        "deep sharp triangular shadows from window blinds, "
        "dense screentone background, asymmetric heavy ink shadows, "
        "Tokyo Ghoul Sui Ishida manga style"
    ),
    "classroom": (
        "Japanese high school classroom 3-B interior, rows of wooden desks, "
        "sharp angular shadow from west window, deep ink shadows under desks, "
        "dense screentone walls, asymmetric dark atmosphere, "
        "Tokyo Ghoul Sui Ishida manga style"
    ),
    "school-hierarchy": (
        "Japanese high school classroom interior with intense atmosphere, "
        "wooden desks in rows, sharp triangular window shadows, "
        "deep ink shadows, dense screentone, "
        "Tokyo Ghoul Sui Ishida manga style"
    ),
    "rens-room": (
        "dark hacker basement room with multi-monitor wall code glow, "
        "sharp triangular shadows from purple LED light, "
        "asymmetric heavy ink shadows, dense urban screentone, "
        "Tokyo Ghoul Sui Ishida manga style"
    ),
    "neis-room": (
        "teen girl bedroom interior, vanity mirror catching dim light, "
        "sharp angular window shadow, dense screentone walls, "
        "moody asymmetric dark atmosphere, "
        "Tokyo Ghoul Sui Ishida manga style"
    ),
    "city-street": (
        "Japanese residential neighborhood street at night, sidewalk, "
        "low wall, telephone poles with sharp angular shadow, "
        "moody dark atmosphere with single street lamp, "
        "asymmetric heavy ink, Tokyo Ghoul Sui Ishida manga style"
    ),
}

SCENE_COLOR = {
    "yuto-bedroom":     "dark teen bedroom, single bed, study desk, cool moody lighting",
    "classroom":        "moody japanese classroom, wooden desks, sharp shadows from west window",
    "school-hierarchy": "intense japanese classroom, desks, blackboard, deep shadows",
    "rens-room":        "dark hacker bedroom, monitors, gaming chair, cool purple ambient",
    "neis-room":        "moody teen girl bedroom, vanity, wardrobe, dim window light",
    "city-street":      "dark japanese residential street at night, single lamp",
}

CHAR_INK = {
    "Yuto":  "1boy, 17yo japanese teen, messy black hair with heavy ink strands, "
              "intense shadowed eyes with triangular shadow under, "
              "white school shirt, navy slacks, slim build, moody expression",
    "Ren":   "1boy, 17yo japanese teen, dark messy hair with heavy ink strokes, "
              "narrowed shadowed eyes, oversized grey hoodie, "
              "slumped melancholy pose, asymmetric heavy ink",
    "Nei":   "1girl, 16yo japanese teen, long platinum blonde hair with sharp ink strands, "
              "intense observant eyes with deep shadow, navy sailor uniform, "
              "stoic expression, sharp triangular shadow",
    "Akira": "1boy, 17yo japanese teen, short brown hair with heavy ink, "
              "intense narrowed eyes, fashionable streetwear, "
              "moody confident pose",
    "Saki":  "1girl, 16yo japanese teen, shoulder-length brown bob with heavy ink, "
              "intense skeptical eyes, navy sailor uniform, deep ink shadows",
}
CHAR_COLOR = CHAR_INK


def patch_module(target_mod) -> None:
    target_mod.QUALITY_INK = QUALITY_INK
    target_mod.QUALITY_COLOR = QUALITY_COLOR
    target_mod.NEG_INK = NEG_INK
    target_mod.NEG_COLOR = NEG_COLOR
    target_mod.SCENE_INK = SCENE_INK
    target_mod.SCENE_COLOR = SCENE_COLOR
    target_mod.CHAR_INK = CHAR_INK
    target_mod.CHAR_COLOR = CHAR_COLOR


def get_ink_footer() -> str:
    return ("Sui Ishida Tokyo Ghoul style, dark moody manga, "
            "sharp triangular shadow, asymmetric heavy ink")
