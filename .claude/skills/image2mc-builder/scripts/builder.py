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

import config
from world_reader import load_area

BUILDS = config.work("builds")   # 作業フォルダの builds/（スキルのフォルダには書かない）
AIR = "minecraft:air"


def rcon():
    """サーバーの RCON。場所とパスワードは設定のサーバーの server.properties から毎回読む。"""
    host, pw, port = config.rcon()
    return MCRcon(host, pw, port=port)


def norm(state: str) -> str:
    return state if state.startswith("minecraft:") else f"minecraft:{state}"


class Construction:
    def __init__(self, name: str, cells: set, y0: int, y1: int):
        self.name = name
        self.cells = set(cells)
        self.site = set(cells)      # 丸ごと空にしてよいセル（敷地）
        self.demolish = set()       # 敷地の外にはみ出した、元の建物の残り（ここだけ空にする）
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

    def find_connected(self, footprint: set, ground_y: int, protect: set, radius: int = 6) -> set:
        """元の建物の土台（footprint）の上のブロックから、つながっているブロックを全部たどる（26近傍）。
        土台から radius マスまで、protect（ほかの建物のセル）には入らない。敷地の外の分だけ返す。"""
        with rcon() as m:
            m.command("save-all flush")
        xs, zs = [c[0] for c in footprint], [c[1] for c in footprint]
        snap = load_area(min(xs) - radius, min(zs) - radius, max(xs) + radius, max(zs) + radius,
                         y0=ground_y + 1, y1=self.y1)
        near = {(x + dx, z + dz) for (x, z) in footprint
                for dx in range(-radius, radius + 1) for dz in range(-radius, radius + 1)}
        allowed = (near - protect) | footprint
        solid = {p for p in snap.blocks if (p[0], p[2]) in allowed}
        seen = {p for p in solid if (p[0], p[2]) in footprint}
        todo = list(seen)
        while todo:
            x, y, z = todo.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        q = (x + dx, y + dy, z + dz)
                        if q in solid and q not in seen:
                            seen.add(q)
                            todo.append(q)
        return {p for p in seen if (p[0], p[2]) not in self.site}

    def add_demolition(self, blocks: set, source_world: Path):
        """敷地の外の残りを解体の対象に加える（そのセルの元の状態も控えに足すので reset で戻せる）。"""
        if not blocks:
            return
        self.demolish |= set(blocks)
        self.cells |= {(x, z) for x, _, z in blocks}
        xs = [c[0] for c in self.cells]
        zs = [c[1] for c in self.cells]
        self.box = (min(xs), min(zs), max(xs), max(zs))
        self.extend_baseline(source_world)
        print(f"解体: 敷地の外の残り {len(blocks)} ブロック（{len({(x, z) for x, _, z in blocks})} 列）")

    def extend_baseline(self, source_world: Path):
        """敷地を広げたとき、控えに無いセルの元の状態を source_world（生成直後のワールドのコピー）から足す。"""
        path = self.dir / "baseline.json"
        d = json.loads(path.read_text(encoding="utf-8"))
        have = {(x, z) for x, _, z, _ in d["blocks"]}
        missing = self.cells - have
        if not missing:
            return 0
        xs, zs = [c[0] for c in missing], [c[1] for c in missing]
        with rcon() as m:
            m.command("save-all flush")
        snap = load_area(min(xs), min(zs), max(xs), max(zs), y0=self.y0, y1=self.y1, world=source_world)
        palette = d["palette"]
        idx = {s: i for i, s in enumerate(palette)}
        for (x, z) in missing:
            for y in range(self.y0, self.y1 + 1):
                s = snap.get(x, y, z)
                if s not in idx:
                    idx[s] = len(palette)
                    palette.append(s)
                d["blocks"].append([x, y, z, idx[s]])
        d["box"] = self.box
        d.setdefault("extended", []).append({"cells": len(missing), "from": str(source_world)})
        path.write_text(json.dumps(d), encoding="utf-8")
        print(f"baseline に {len(missing)} セル分を追加（{source_world}）")
        return len(missing)

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
        x0, z0, x1, z1 = self.box
        errors = 0
        with rcon() as m:
            # プレイヤーがいないとチャンクが読み込まれず、setblock/fill が失敗するので強制読み込みする
            m.command(f"forceload add {x0} {z0} {x1} {z1}")
            time.sleep(2)
            try:
                for c in cmds:
                    r = m.command(c)
                    # "Could not set the block" は「すでに同じブロック」（つながり方の状態だけ違う柵など）なので失敗にしない
                    if any(w in r for w in ("Unknown", "Incorrect", "Expected", "not loaded", "Invalid")):
                        errors += 1
                        if errors <= 10:
                            print("RCONエラー:", c, "->", r)
            finally:
                m.command(f"forceload remove {x0} {z0} {x1} {z1}")
        if errors:
            raise RuntimeError(f"{errors} 件のコマンドが失敗しました（上のエラーを確認）")
        return len(diff)

    def reset(self):
        """更地（baseline）に戻す。額縁（看板の地図アート）も消す。"""
        self.place_frames([])
        n = self.send(self.baseline(), self.read_world())
        print(f"baseline に戻しました（{n} ブロック変更）")

    def place_ordered(self, blocks, label="仕掛け", verify=False):
        """ピストンや飾りなど、置く順番で状態が決まるものを、書いた順に setblock する（施工の後に呼ぶ）。
        verify=True なら置いた後に1つずつワールドを確かめ、無い物を報告する（飾りが辞書どおり付いたかの確認）。"""
        if not blocks:
            return
        x0, z0, x1, z1 = self.box
        with rcon() as m:
            m.command(f"forceload add {x0} {z0} {x1} {z1}")
            time.sleep(2)
            try:
                for (x, y, z, s) in blocks:
                    r = m.command(f"setblock {x} {y} {z} {s}")
                    if any(w in r for w in ("Unknown", "Incorrect", "Expected", "not loaded", "Invalid")):
                        raise RuntimeError(f"setblock {x} {y} {z} {s} -> {r}")
                missing = []
                if verify:
                    time.sleep(1)
                    for (x, y, z, s) in blocks:
                        name = s.split("[")[0].split("{")[0]
                        if "passed" not in m.command(f"execute if block {x} {y} {z} {name}"):
                            missing.append((x, y, z, name))
            finally:
                m.command(f"forceload remove {x0} {z0} {x1} {z1}")
        print(f"{label}: {len(blocks)} 個を順番に設置")
        if verify:
            if missing:
                print(f"  {label}が {len(missing)} 個付いていません（支えが無いと外れる）:", missing[:10])
            else:
                print(f"  {label}は全部付いていることを確かめました")

    def place_frames(self, frames):
        """敷地内の額縁を全部消してから、frames = [(x, y, z, facing, map_id)] を固定・透明で置く。
        facing は west/east/north/south。支えのブロックは先に置いておくこと。"""
        facing_id = {"north": 2, "south": 3, "west": 4, "east": 5}
        x0, z0, x1, z1 = self.box
        sel = f"x={x0},y={self.y0},z={z0},dx={x1 - x0},dy={self.y1 - self.y0},dz={z1 - z0}"
        with rcon() as m:
            m.command(f"forceload add {x0} {z0} {x1} {z1}")
            time.sleep(2)
            try:
                m.command(f"kill @e[type=minecraft:item_frame,{sel}]")
                for (x, y, z, facing, map_id) in frames:
                    nbt = (f'{{Facing:{facing_id[facing]}b,Fixed:1b,Invisible:1b,'
                           f'Item:{{id:"minecraft:filled_map",count:1,components:{{"minecraft:map_id":{map_id}}}}}}}')
                    r = m.command(f"summon minecraft:item_frame {x + 0.5} {y + 0.5} {z + 0.5} {nbt}")
                    if "Summoned" not in r:
                        print("額縁の設置に失敗:", (x, y, z), "->", r)
            finally:
                m.command(f"forceload remove {x0} {z0} {x1} {z1}")

    def build(self, design: dict, clear_from_y: int, note: str = ""):
        """baseline を基準に、clear_from_y 以上を空にしてから design を重ねて施工する。"""
        design = {p: norm(s) for p, s in design.items()}
        self.check_inside(design)
        base = self.baseline()
        # 敷地は clear_from_y より上を丸ごと空に、敷地の外は元の建物の残り（demolish）だけ空にする
        target = {p: (AIR if ((p[0], p[2]) in self.site and p[1] >= clear_from_y) or p in self.demolish else s)
                  for p, s in base.items()}
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
