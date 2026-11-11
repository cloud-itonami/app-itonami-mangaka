"""v11 — Shokugeki no Soma (食戟のソーマ) style profile.

Replaces Witch Watch's soft tones with the dramatic battle-intensity of
佐伯俊 art (Shokugeki no Soma): heavy ink + dense screentone + radial speed
lines + dramatic chiaroscuro + extreme expressions.

Triggered by V11_STYLE=shokugeki.
"""

QUALITY_INK = (
    "professional Japanese manga panel, monochrome B&W only, "
    "dramatic ink weight, heavy black ink lines, dense screentone hatching, "
    "strong chiaroscuro contrast, intense expression, radial speed lines, "
    "action-burst composition, dynamic perspective, "
)
QUALITY_COLOR = (
    "masterpiece, best quality, dramatic battle scene, intense lighting, "
    "high contrast, motion blur, "
)

NEG_INK = (
    "color, red, crimson, blood, watercolor, photograph, sepia, "
    "low quality, blurry, deformed, multiple people, twin, multiple faces, "
    "soft pastel, cute chibi, light atmosphere, washed gray, "
    "Witch Watch style, gentle mood, no contrast, anime color"
)
NEG_COLOR = (
    "lowres, bad anatomy, bad hands, blurry, watermark, signature, "
    "2girls, 2boys, twin, group, pastel, washed out"
)

# Scene prompts re-tuned: heavier ink + dramatic mood
SCENE_INK = {
    "yuto-bedroom": (
        "teen bedroom interior, single bed, study desk with smartphone, "
        "intense punk band posters and concert tickets on wall, "
        "dramatic chiaroscuro window light casting deep shadows, "
        "heavy ink shadows on wood floor, dense screentone background, "
        "Shokugeki no Soma battle manga style by Saeki Shun"
    ),
    "classroom": (
        "Japanese high school classroom 3-B interior, rows of wooden desks, "
        "intense west window backlighting, deep shadows under desks, "
        "dense screentone walls, dramatic perspective, "
        "Shokugeki no Soma battle manga style"
    ),
    "school-hierarchy": (
        "Japanese high school classroom interior with intense atmosphere, "
        "wooden desks in rows, blackboard, dramatic west window light, "
        "heavy screentone, looming shadows, "
        "Shokugeki no Soma battle manga style"
    ),
    "rens-room": (
        "dark hacker basement room, multi-monitor wall blazing with code, "
        "research corkboard with intense lighting, gaming chair, "
        "dramatic purple light casting deep shadows, "
        "heavy ink shadows, dense screentone, "
        "Shokugeki no Soma battle manga style"
    ),
    "neis-room": (
        "teen girl bedroom interior, vanity mirror, wardrobe, single bed, "
        "intense morning window backlight casting dramatic shadows, "
        "K-pop posters, dense screentone, deep blacks, "
        "Shokugeki no Soma battle manga style"
    ),
    "city-street": (
        "Japanese residential neighborhood street, sidewalk, low wall, "
        "two-storey wooden houses, telephone poles, dramatic golden hour "
        "backlight with deep silhouette shadows, heavy ink, intense atmosphere, "
        "Shokugeki no Soma battle manga style"
    ),
}

SCENE_COLOR = {
    "yuto-bedroom":     "intense teen bedroom, single bed, study desk, posters, dramatic warm light + deep shadows",
    "classroom":        "intense japanese high school classroom, wooden desks, blackboard, dramatic west window backlight",
    "school-hierarchy": "intense japanese classroom, desks, blackboard, large window, dramatic afternoon light",
    "rens-room":        "intense teen bedroom, multi-monitor wall, gaming chair, dramatic purple ambient",
    "neis-room":        "intense teen girl bedroom, vanity, wardrobe, dramatic morning backlight",
    "city-street":      "intense japanese residential street, sidewalk, houses, dramatic golden hour silhouette",
}

# Character descriptions — emphasize sharper features, intense expressions
CHAR_INK = {
    "Yuto":  "1boy, 17yo japanese teen, sharp messy black hair, intense dark eyes, "
              "white school shirt, navy slacks, slim build, sharp jawline, "
              "intense expression, battle manga style",
    "Ren":   "1boy, 17yo japanese teen, dark hair under hoodie, sharp narrowed eyes, "
              "oversized grey hoodie, intense brooding pose, sharp features, "
              "battle manga style",
    "Nei":   "1girl, 16yo japanese teen, long platinum blonde hair, sharp blue eyes, "
              "navy sailor uniform with red ribbon, intense determined expression, "
              "battle manga style",
    "Akira": "1boy, 17yo japanese teen, short brown hair, intense mischievous eyes, "
              "fashionable streetwear, sharp grin, battle manga style",
    "Saki":  "1girl, 16yo japanese teen, shoulder-length brown bob, sharp skeptical eyes, "
              "navy sailor uniform, intense deadpan expression, battle manga style",
}
CHAR_COLOR = CHAR_INK


def patch_module(target_mod) -> None:
    """Monkey-patch v10_panel_render module with Shokugeki constants."""
    target_mod.QUALITY_INK = QUALITY_INK
    target_mod.QUALITY_COLOR = QUALITY_COLOR
    target_mod.NEG_INK = NEG_INK
    target_mod.NEG_COLOR = NEG_COLOR
    target_mod.SCENE_INK = SCENE_INK
    target_mod.SCENE_COLOR = SCENE_COLOR
    target_mod.CHAR_INK = CHAR_INK
    target_mod.CHAR_COLOR = CHAR_COLOR


def get_ink_footer() -> str:
    return "Shokugeki no Soma style by Saeki Shun, intense battle manga, professional Jump"
