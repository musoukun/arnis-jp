"""パーツ: 看板の例（★ 看板1枚につき1ファイル。名前はほかのパーツと重ねない）。写真から中身を読んで sign_art で描く。"""
import parts
import sign_art

ORDER = 40


def signs(geo, c):
    x, z = parts.Facade(c, "w").at(2, out=1)          # ★ 面・左の角から何マス・壁に直接(out=1)か飛び出す(out=2)か
    return [("shop_name", 5, 2, (x, c.top + 2, z), "west")]


BACKING = {"shop_name": None}                         # None は壁に直接（背景の透明な文字）


def images():
    return {"shop_name": sign_art.text(["SHOP"], 5, 2)}
