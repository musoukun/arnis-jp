"""
パーツの書き方の例（名前が _ で始まるので、組み立てには入らない。コピーして p_<名前>.py にし、受け持ちの物だけを残す）。
どの作りを選ぶかは recipes.md の「手札」で写真から決める。値は全部、受け持ちの表（plan.md）の数で書き換える。
位置は parts.Facade(c, 面).at(k) / .line(k, 外へ何マス)、高さは c.G（地面）・c.F（床）・c.top（帯の段）から書く。
"""
import parts
import sign_art

ORDER = 20          # 組み立ての順: 屋上 10 → 帯 15 → 面ごと 20 → 外まわり 30 → 看板 40


def part(c):
    # 屋上（手札「屋根の縁・屋上の物」）: 塔・箱は box_on_roof、縁が透ける柵なら lattice（塔の所は skip）
    #   tower = {parts.Facade(c, "n").line(k, -d) for k in range(13, 18) for d in (0, 1)}
    #   parts.box_on_roof(c, tower, 4, "deepslate_bricks")
    #   parts.lattice(c, 3, "nether_brick_fence", skip=tower)
    # 帯・軒（手札「帯・軒」）: 壁から1マス張り出したハーフと軒下の明かり
    #   parts.eave_slab(c, "<帯のハーフ>", lantern_every=4, faces={"<明かりを吊る面>"})
    # 面の一部だけの窓（手札「窓」）
    #   parts.window_strip(c, "n", 0, 4, rows=3)
    # 壁沿いの植え込み・車止め（手札「外まわり」）
    #   gravel, _ = parts.planter_ring(c, lambda p: ..., edge="brick_wall", fill="diorite")
    #   parts.bollard(c, [...], c.G + 2)
    pass


def signs(geo, c):
    # 看板（recipes.md の「看板の取り付け方」で、何に付いているかから位置・高さ・向き・裏を決める）
    #   壁に直接 → at(k, out=1)・BACKING None ／ 箱で張り出す・塔の面 → at(k, out=2)・BACKING に箱の色
    x, z = parts.Facade(c, "w").at(2, out=1)
    return [("example", 5, 2, (x, c.top + 2, z), parts.FACING["w"])]   # (名前, 列, 行, 左上の額縁, 向き)


BACKING = {"example": None}


def images():
    # 写真から中身（文字・色・形・配置）を読んで、sign_art の型で描く（parts.md の「看板の絵」）
    return {"example": sign_art.text(["SHOP"], 5, 2)}
