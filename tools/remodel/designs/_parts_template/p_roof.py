"""パーツ: 屋上（塔・屋上の柵）。★ 受け持ちの表のとおりに書く。高さは c.top から。位置は parts.Facade で。"""
import parts

ORDER = 10


def part(c):
    towers = set()                                    # ★ 例: 北西の角の塔 {(x, z) ...} を Facade から求めて box_on_roof
    parts.lattice(c, 3, "nether_brick_fence", skip=towers)
