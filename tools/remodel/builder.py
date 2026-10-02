"""
施工: 敷地の控え（baseline）を取り、設計ブロックとの差分だけを RCON で置く。

  builds/<name>/baseline.json … 初回施工前の敷地（範囲内の全ブロック、air 含む）
  builds/<name>/NNN.json      … 施工記録（置いた設計ブロック）

「更地に戻す」= baseline を差分で書き戻す。何回建て直しても baseline 基準なので取り残しが出ない。
"""

import json
import time
from datetime import datetime
from pathlib import Path

from mcrcon import MCRcon

from world_reader import load_area

ROOT = Path(__file__).resolve().parents[2]
BUILDS = Path(__file__).resolve().parent / "builds"
RCON = ("127.0.0.1", "arnis2026", 25575)
AIR = "minecraft:air"


def rcon():
    host, pw, port = RCON
    return MCRcon(host, pw, port=port)


def norm(state: str) -> str:
    return state if state.startswith("minecraft:") else f"minecraft:{state}"


class Construction:
    def __init__(self, name: str, cells: set, y0: int, y1: int):
        self.name = name
        self.cells = set(cells)
        self.y0, self.y1 = y0, y1
        self.dir = BUILDS / name
        self.dir.mkdir(parents=True, exist_ok=True)
        xs = [c[0] for c in cells]
        zs = [c[1] for c in cells]
        self.box = (min(xs), min(zs), max(xs), max(zs))

    # ---- 読み取り ----
    def read_world(self) -> dict:
        with rcon() as m:
            m.command("save-all flush")
        snap = load_area(*self.box, y0=self.y0, y1=self.y1)
        return {(x, y, z): snap.get(x, y, z) for (x, z) in self.cells
                for y in range(self.y0, self.y1 + 1)}

    def baseline(self) -> dict:
        path = self.dir / "baseline.json"
        if not path.exists():
            world = self.read_world()
            palette = sorted(set(world.values()))
            idx = {s: i for i, s in enumerate(palette)}
            path.write_text(json.dumps({
                "box": self.box, "y": [self.y0, self.y1], "palette": palette,
                "blocks": [[x, y, z, idx[s]] for (x, y, z), s in world.items()],
                "taken_at": datetime.now().isoformat(timespec="seconds"),
            }), encoding="utf-8")
            print(f"baseline を保存: {path} ({len(world)} ブロック)")
        d = json.loads(path.read_text(encoding="utf-8"))
        return {(x, y, z): d["palette"][i] for x, y, z, i in d["blocks"]}

    # ---- 書き込み ----
    def check_inside(self, blocks: dict):
        bad = [p for p in blocks if (p[0], p[2]) not in self.cells or not (self.y0 <= p[1] <= self.y1)]
        if bad:
            raise ValueError(f"敷地の外に {len(bad)} ブロックあります（例: {bad[:5]}）。施工を中止します")

    def send(self, target: dict, current: dict) -> int:
        """target と current の差分を送る。x方向に同じブロックが続く所は /fill にまとめる。"""
        diff = {p: s for p, s in target.items() if current.get(p, AIR) != s}
        rows = {}
        for (x, y, z), s in diff.items():
            rows.setdefault((y, z), []).append((x, s))
        cmds = []
        for (y, z), items in rows.items():
            items.sort()
            i = 0
            while i < len(items):
                x0, s = items[i]
                j = i
                while j + 1 < len(items) and items[j + 1][0] == items[j][0] + 1 and items[j + 1][1] == s:
                    j += 1
                x1 = items[j][0]
                cmds.append(f"fill {x0} {y} {z} {x1} {y} {z} {s}" if x1 > x0 else f"setblock {x0} {y} {z} {s}")
                i = j + 1
        # 下から順に置く（支えが要るブロック対策）
        cmds.sort(key=lambda c: int(c.split()[2]))
        with rcon() as m:
            for c in cmds:
                r = m.command(c)
                if "Unknown" in r or "Incorrect" in r or "Expected" in r:
                    print("RCONエラー:", c, "->", r)
        return len(diff)

    def reset(self):
        """更地（baseline）に戻す。"""
        n = self.send(self.baseline(), self.read_world())
        print(f"baseline に戻しました（{n} ブロック変更）")

    def build(self, design: dict, clear_from_y: int, note: str = ""):
        """baseline を基準に、clear_from_y 以上を空にしてから design を重ねて施工する。"""
        design = {p: norm(s) for p, s in design.items()}
        self.check_inside(design)
        base = self.baseline()
        target = {p: (AIR if p[1] >= clear_from_y else s) for p, s in base.items()}
        target.update(design)
        t = time.time()
        n = self.send(target, self.read_world())
        no = len(list(self.dir.glob("[0-9][0-9][0-9].json"))) + 1
        (self.dir / f"{no:03d}.json").write_text(json.dumps({
            "build": no, "note": note, "applied_at": datetime.now().isoformat(timespec="seconds"),
            "clear_from_y": clear_from_y,
            "blocks": [[x, y, z, s] for (x, y, z), s in design.items()],
        }, ensure_ascii=False), encoding="utf-8")
        print(f"施工 {no:03d}: {n} ブロック変更（{time.time() - t:.1f}秒）")
        return target
