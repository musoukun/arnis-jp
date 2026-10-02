"""
ガスト施工の入口。
  python run_gusto.py preview   … ワールドに置かず、写真と同じ視点の絵だけ描く（out/ に保存）
  python run_gusto.py build     … 施工（初回は敷地の控え baseline を自動で取る）
  python run_gusto.py reset     … 更地（baseline）に戻す
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "designs"))
import gusto_kitahanada as D
from builder import Construction, AIR, norm
from parcel import OsmGeometry, ROOT
from render import VoxelScene, render_view, render_top
from world_reader import load_area

SC = Path(__file__).resolve().parent / "out"  # プレビュー画像の出力先（git管理外）
SC.mkdir(exist_ok=True)
geo = OsmGeometry(ROOT / "doc" / "kitahanada" / "osm_data.json")
site = D.site_cells(geo)
con = Construction("gusto_kitahanada", site, y0=D.G, y1=-30)
# 写真（gasuto.png / sv1）のおおよその撮影位置: 西の歩道、地面から2.5m
CAMERAS = {
    "street": dict(pos=(419.0, D.G + 1 + 2.5, 474.0), yaw=-92.0, pitch=-2.0, vfov=78, width=954, height=620),
    "player": dict(pos=(420.734, -55 + 1.62, 481.112), yaw=-97.8, pitch=-15.7, vfov=90, width=854, height=480),
}


def preview(tag="preview"):
    design = {p: norm(s) for p, s in D.design(geo).items()}
    con.check_inside(design)
    snap = load_area(380, 420, 540, 560, y0=-64, y1=-10)
    over = {}
    for (x, z) in site:  # 更地にしてから設計を重ねた状態を作る
        for y in range(D.G + 1, -29):
            over[(x, y, z)] = AIR
    # 描画だけ: 西の歩道の持ち上がった帯（arnisの橋の扱いの不具合）を取り除き、実際の地上の歩道に近づける
    for x in range(395, 427):
        for z in range(440, 500):
            for y in range(D.G + 1, -40):
                over[(x, y, z)] = AIR
            over[(x, D.G, z)] = "minecraft:polished_andesite"
    over.update(design)
    sc = VoxelScene(snap, over)
    for name, cam in CAMERAS.items():
        render_view(sc, **cam).save(SC / f"{tag}_{name}.png")
    render_top(sc, px=6).crop(((420 - 380) * 6, (455 - 420) * 6, (460 - 380) * 6, (497 - 420) * 6)).save(SC / f"{tag}_top.png")
    print(len(design), "ブロック / 敷地", len(site), "セル")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    if cmd == "preview":
        preview(sys.argv[2] if len(sys.argv) > 2 else "preview")
    elif cmd == "build":
        con.build(D.design(geo), clear_from_y=D.G + 1, note=" ".join(sys.argv[2:]))
    elif cmd == "reset":
        con.reset()
