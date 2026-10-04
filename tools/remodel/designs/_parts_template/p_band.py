"""パーツ: 帯（壁から1マス張り出したハーフ）と軒下の吊りランタン。"""
import parts

ORDER = 15


def part(c):
    parts.eave_slab(c, "mangrove_slab", lantern_every=4, faces={"w", "n"})   # ★ 帯の見える面
