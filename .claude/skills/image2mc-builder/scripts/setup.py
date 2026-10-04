"""
image2mc-builder の設定（作業フォルダの config.json）を見る・保存する。スキルを使い始める時に最初に走らせる。

  python setup.py show                 … 今の設定と、足りない項目（ユーザーに聞くこと）を出す
  python setup.py detect               … このパソコンで見つかった候補を出す（保存はしない。ユーザーに確かめてから set）
  python setup.py set key=値 [key=値 …] … 保存する（server_dir / osm_json / minecraft_jar / fov / world / rcon_host）
"""

import os
import sys
from pathlib import Path

import config

KEYS = ("server_dir", "osm_json", "minecraft_jar", "fov", "world", "rcon_host")
REQUIRED = ("server_dir", "osm_json", "minecraft_jar")


def show():
    cfg = config.load()
    print(f"作業フォルダ: {config.WORK}")
    print(f"設定ファイル: {config.CONFIG}{'' if config.CONFIG.exists() else '（まだ無い）'}")
    for k in KEYS:
        if k in cfg:
            print(f"  {k} = {cfg[k]}")
    missing = [k for k in REQUIRED if not cfg.get(k)]
    if not missing:
        try:
            props = config.server_properties()
            print(f"  → ワールド: {config.world()}")
            print(f"  → RCON: {'有効' if props.get('enable-rcon') == 'true' else '無効（施工できない）'}"
                  f"（ポート {props.get('rcon.port', '25575')}）")
        except SystemExit as e:
            print(f"  → {e}")
        for k in ("osm_json", "minecraft_jar"):
            if not config.path_of(cfg[k]).exists():
                print(f"  → {k} のファイルが見つかりません: {config.path_of(cfg[k])}")
        print("足りない項目はありません")
    else:
        print("足りない項目（ユーザーに聞く）:")
        for k in missing:
            print(f"  - {k}: {config.QUESTIONS[k]}")
        print(f"  保存: python \"{config.SETUP}\" set {' '.join(f'{k}=<値>' for k in missing)}")


SKIP = {".claude", ".git", "target", "node_modules", "image2mc"}


def _find(pattern, limit=8):
    """作業を始めたフォルダの下で見つかったファイル（作業用・ビルド用のフォルダは除く）。"""
    found = []
    for p in sorted(config.PROJECT.glob(f"**/{pattern}")):
        rel = p.relative_to(config.PROJECT).parts
        if len(rel) <= 5 and not SKIP.intersection(rel):
            found.append(p)
    return found[:limit]


def detect():
    print("見つかった候補（ユーザーに確かめてから set で保存する）:")
    for p in _find("server.properties"):
        print(f"  server_dir? {p.parent}")
    versions = Path(os.path.expandvars(r"%APPDATA%\.minecraft\versions"))
    if versions.exists():
        for d in sorted(versions.iterdir()):
            jar = d / f"{d.name}.jar"
            if jar.exists():
                print(f"  minecraft_jar? {jar}")
    for p in _find("*osm*.json"):
        print(f"  osm_json? {p}")


def set_values(pairs):
    cfg = config.load()
    for pair in pairs:
        if "=" not in pair:
            sys.exit(f"key=値 の形で書いてください: {pair}")
        k, v = pair.split("=", 1)
        if k not in KEYS:
            sys.exit(f"知らない項目です: {k}（{', '.join(KEYS)}）")
        if k == "fov":
            v = float(v)
        elif k in ("server_dir", "osm_json", "minecraft_jar", "world") and not config.path_of(v).exists():
            sys.exit(f"{k} が見つかりません: {config.path_of(v)}")
        cfg[k] = v
    config.save(cfg)
    show()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "show":
        show()
    elif cmd == "detect":
        detect()
    elif cmd == "set":
        set_values(sys.argv[2:])
    else:
        sys.exit(__doc__)
