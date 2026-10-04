"""
image2mc-builder の設定と作業フォルダ。スキルのフォルダには何も書かない。

- 作業フォルダ: Claude Code を開いているフォルダ（CLAUDE_PROJECT_DIR、無ければ今のフォルダ）の image2mc/。
  建物ごとの設計（designs/）・質問（specs/）・絵とフォーム（out/）・施工の控え（builds/）はここに出る。
  IMAGE2MC_WORK で別の場所にできる。
- 設定: 作業フォルダの config.json。使う人の環境の情報（サーバーのフォルダ、OSM データ、Minecraft の jar、視野角）。
  足りない項目は、道具が「ユーザーに何を聞くか」を書いて止まる。聞いたら setup.py set で保存する。
- RCON の場所とパスワードは保存しない。サーバーのフォルダの server.properties から毎回読む。
"""

import json
import os
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS = SKILL_DIR / "assets"
PROJECT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()
WORK = Path(os.environ.get("IMAGE2MC_WORK") or PROJECT / "image2mc").resolve()
CONFIG = WORK / "config.json"
SETUP = SKILL_DIR / "scripts" / "setup.py"

DEFAULTS = {"fov": 102, "rcon_host": "127.0.0.1"}

# 足りない時にユーザーに聞くこと（setup.py show と、止まった時の案内に出す）
QUESTIONS = {
    "server_dir": "建物を置く Minecraft サーバーのフォルダ（server.properties がある所）はどこですか？"
                  "（ワールドは server.properties の level-name、RCON の場所とパスワードもここから読みます）",
    "osm_json": "ワールドを作った時の OSM データの JSON はどこですか？"
                "（arnis の --save-json-file で保存したもの。建物の形と場所をここから読みます）",
    "minecraft_jar": "テクスチャに使う Minecraft 本体の jar はどこですか？"
                     "（例: %APPDATA%\\.minecraft\\versions\\<版>\\<版>.jar。サーバーと同じ版）",
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG.exists():
        cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    return cfg


def save(cfg: dict):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    keep = {k: v for k, v in cfg.items() if DEFAULTS.get(k) != v or k not in DEFAULTS}
    CONFIG.write_text(json.dumps(keep, ensure_ascii=False, indent=2), encoding="utf-8")


def stop_missing(keys):
    lines = [f"設定が足りません（{CONFIG}）。ユーザーに聞いてから、次で保存してください:"]
    for k in keys:
        lines.append(f"  - {k}: {QUESTIONS.get(k, k)}")
    lines.append(f"  保存: python \"{SETUP}\" set {' '.join(f'{k}=<値>' for k in keys)}")
    sys.exit("\n".join(lines))


def need(key: str) -> str:
    v = load().get(key)
    if not v:
        stop_missing([key])
    return v


def path_of(value: str) -> Path:
    """設定やユーザーが書いたパス。相対パスは作業を始めたフォルダ（PROJECT）から。"""
    p = Path(os.path.expandvars(str(value))).expanduser()
    return p if p.is_absolute() else (PROJECT / p)


def work(*parts) -> Path:
    """作業フォルダの中のパス（designs/, specs/, out/, builds/ …）。"""
    return WORK.joinpath(*parts)


def server_dir() -> Path:
    return path_of(need("server_dir"))


def server_properties() -> dict:
    f = server_dir() / "server.properties"
    if not f.exists():
        sys.exit(f"server.properties が見つかりません: {f}（server_dir の設定を確かめてください）")
    props = {}
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            props[k.strip()] = v.strip()
    return props


def world() -> Path:
    """建物を置くワールドのフォルダ。REMODEL_WORLD（プレビュー専用で別のワールドを読む）が優先。"""
    if os.environ.get("REMODEL_WORLD"):
        return Path(os.environ["REMODEL_WORLD"])
    cfg = load()
    if cfg.get("world"):
        return path_of(cfg["world"])
    return server_dir() / server_properties().get("level-name", "world")


def rcon() -> tuple:
    """(host, password, port)。server.properties から毎回読む（パスワードは保存しない）。"""
    props = server_properties()
    if props.get("enable-rcon", "false").lower() != "true":
        sys.exit("サーバーの RCON が無効です。server.properties の enable-rcon=true と rcon.password を設定して、"
                 "サーバーを再起動するようユーザーに頼んでください")
    return load()["rcon_host"], props.get("rcon.password", ""), int(props.get("rcon.port", "25575"))


def osm_json() -> Path:
    return path_of(need("osm_json"))


def minecraft_jar() -> Path:
    return path_of(need("minecraft_jar"))


def fov() -> float:
    return float(load()["fov"])
