"""v11 — Kozue Amano (天野こずえ) / Aria / Yokohama Kaidashi Kikou style profile.

Characteristics:
  - Soft delicate linework (very thin pen lines)
  - Light atmospheric backgrounds (ample white space)
  - Round expressive eyes (large gentle highlights)
  - Calm contemplative serene mood
  - Soft pastel color palette (or very light grayscale in mono)
  - Healing iyashi-kei aesthetic
  - Beautiful sky / water / nature in every panel possible
  - Minimal heavy ink, maximum white space
"""

QUALITY_INK = (
    "professional Japanese manga panel, monochrome with very soft tones, "
    "Kozue Amano Aria aesthetic, delicate thin pen line, "
    "ample white space, gentle round expressive eyes with large highlights, "
    "serene atmospheric background, light delicate hatching, "
    "iyashi healing tone, calm contemplative mood, "
)
QUALITY_COLOR = (
    "masterpiece, best quality, very aesthetic, soft pastel watercolor, "
    "Kozue Amano Aria color page style, "
    "gentle atmospheric lighting, serene healing mood, "
)

NEG_INK = (
    "color, watercolor, photograph, sepia, "
    "low quality, blurry, deformed, multiple people, twin, multiple faces, "
    "heavy ink, dark shadows, intense expression, gritty, dramatic, "
    "Tokyo Ghoul style, Shokugeki style, Death Note style, "
    "harsh contrast, dense screentone"
)
NEG_COLOR = (
    "lowres, bad anatomy, bad hands, blurry, watermark, signature, "
    "2girls, 2boys, twin, group, "
    "heavy shadows, dark mood, gritty, oversaturated, dramatic"
)

SCENE_INK = {
    "yuto-bedroom": (
        "Japanese teen bedroom interior, single bed with soft sheets, "
        "study desk with smartphone, gentle window light streaming in, "
        "delicate atmospheric background, ample white space, "
        "soft light screentone, peaceful contemplative mood, "
        "Kozue Amano Aria manga style"
    ),
    "classroom": (
        "Japanese high school classroom 3-B interior, wooden desks in soft sunlight, "
        "blackboard with gentle screentone, west window with delicate light, "
        "peaceful serene atmosphere, ample white space, "
        "Kozue Amano Aria manga style"
    ),
    "school-hierarchy": (
        "Japanese high school classroom interior with serene atmosphere, "
        "wooden desks, gentle window light, soft delicate screentone, "
        "peaceful contemplative mood, "
        "Kozue Amano Aria manga style"
    ),
    "rens-room": (
        "teen bedroom with multi-monitor wall, gaming chair, "
        "soft window light, delicate atmospheric mood, "
        "ample white space, gentle screentone, "
        "Kozue Amano Aria manga style"
    ),
    "neis-room": (
        "teen girl bedroom interior with vanity mirror, wardrobe, "
        "soft morning window light, delicate atmospheric background, "
        "ample white space, serene healing mood, "
        "Kozue Amano Aria manga style"
    ),
    "city-street": (
        "Japanese residential neighborhood street, sidewalk with delicate detail, "
        "low wall, telephone poles softly drawn, "
        "soft golden hour light, calm peaceful atmosphere, "
        "ample white space, Kozue Amano Aria manga style"
    ),
}

SCENE_COLOR = {
    "yuto-bedroom":     "soft teen bedroom, single bed, study desk, gentle warm window light, pastel tones",
    "classroom":        "serene japanese classroom, wooden desks, gentle west window light, pastel atmosphere",
    "school-hierarchy": "peaceful japanese classroom, desks, soft afternoon light, watercolor pastel",
    "rens-room":        "soft teen bedroom, monitors, gentle ambient light, pastel tones",
    "neis-room":        "serene teen girl bedroom, vanity, gentle morning light, pastel tones",
    "city-street":      "peaceful japanese residential street, soft golden hour, watercolor pastel",
}

CHAR_INK = {
    "Yuto":  "1boy, 17yo japanese teen, soft messy black hair with delicate strands, "
              "large round expressive eyes with gentle highlights, "
              "white school shirt, navy slacks, slim build, "
              "calm gentle expression, delicate clean line",
    "Ren":   "1boy, 17yo japanese teen, soft dark hair under hoodie, "
              "round droopy gentle eyes, oversized grey hoodie, "
              "relaxed peaceful pose, delicate clean line",
    "Nei":   "1girl, 16yo japanese teen, long platinum blonde hair softly drawn, "
              "large round gentle blue eyes, navy sailor uniform with red ribbon, "
              "serene observant expression, delicate clean line",
    "Akira": "1boy, 17yo japanese teen, short brown hair softly drawn, "
              "large round mischievous eyes, fashionable streetwear, "
              "gentle playful expression, delicate clean line",
    "Saki":  "1girl, 16yo japanese teen, shoulder-length brown bob softly drawn, "
              "large round gentle eyes, navy sailor uniform, "
              "calm thoughtful expression, delicate clean line",
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
    return ("Kozue Amano Aria style, gentle iyashi manga, "
            "delicate thin pen line, serene atmospheric mood")
