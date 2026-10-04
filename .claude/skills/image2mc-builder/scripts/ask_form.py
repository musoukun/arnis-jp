"""
質問のフォームの型。質問の一覧（JSON）を書くだけで、チャットに出すフォームの HTML ができる（フォームを一から作らない）。

  python ask_form.py <質問.json>   … out/ask_<名前>.html を書く。その中身を mcp__visualize__show_widget の widget_code に渡す
                                     （先に mcp__visualize__read_me を呼ぶ。撮って確かめる必要はない）

図は実物のブロックのテクスチャで描く（色の塗りつぶしにしない）。答えは「答えを送る」で1行になってチャットに届く。

質問.json の形（例: KFC）:
{
  "title": "KFC の質問",
  "questions": [
    {"name": "扉の位置", "type": "slider", "q": "扉は、西の面のどこにありますか？（スライダーで動かす）",
     "length": 14, "span": 2, "guess": 11, "left": "北の角", "right": "南の角",
     "rows": 5, "wall": "smooth_stone", "item": "glass", "item_rows": 3, "band": "mangrove_slab"},
    {"name": "入口の形", "type": "choice", "q": "扉は壁と同じ面にありますか、それとも奥に引っ込んでいますか？（上から見た図）",
     "legend": {"W": "deepslate_bricks", "D": "glass", "P": "brick_slab", "S": "stone_bricks"},
     "options": [{"value": "案1", "label": "壁と同じ面", "sub": "扉の前は壁の外の通り道",
                  "grid": ["WWWWDDWWWW", "PPPPPPPPPP", "SSSSSSSSSS"]},
                 {"value": "案2", "label": "奥に引っ込む", "sub": "壁を凹ませて、扉が奥",
                  "grid": ["WWWWDDWWWW", "WWWW..WWWW", "SSSSSSSSSS"]}], "guess": "案1"},
    {"name": "帯のブロック", "type": "block", "q": "赤い帯は、どのブロックが近いですか？",
     "options": ["mangrove_slab", "red_nether_brick_slab", "resin_brick_slab"], "guess": "mangrove_slab"}
  ]
}
- slider（位置・幅）: 正面の壁（rows 段 × length マス）をブロックで描き、item（扉なら glass、看板なら black_concrete）を
  span マス × item_rows 段で置く。スライダーで左右に動く。band は一番上の段（帯）。答えは「<left>から N マス」
  （N は位置の道具 parts.Facade の at(N) と同じ数え方。左の角が 0）
- choice（作りの案）: 上から見た図（grid の1文字 = 1マス、legend で文字 → ブロック、"." は空き）を並べて選ぶ。
  何を比べているのかが図で分かるように描く（言葉と AA だけにしない）
- block（ブロック）: 実物のテクスチャの見本を並べて選ぶ（ハーフは薄く描く）
- どの質問にも「そのほか・補足」の書き込み欄が付く。guess は「推測」の印と、最初から選んだ状態になる
"""

import html
import json
import sys
from pathlib import Path

import config

HERE = Path(__file__).resolve().parent

CSS = """
.af{font:14px/1.6 system-ui,sans-serif;color:var(--text-primary)}
.af .q{border:1px solid var(--border);border-radius:12px;padding:12px 14px;margin:0 0 12px;background:var(--surface-1)}
.af .qt{font-weight:500;margin:0 0 8px}
.af .wall{display:inline-grid;gap:0;border-radius:4px;overflow:hidden;box-shadow:0 0 0 1px var(--border)}
.af .wall div,.af .map div{width:var(--c);height:var(--c);background-size:100% 100%;image-rendering:pixelated}
.af .ends{display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted)}
.af input[type=range]{width:100%}
.af .read{font-weight:500;color:var(--text-accent)}
.af .opts{display:flex;flex-wrap:wrap;gap:8px}
.af .opt{border:1px solid var(--border);border-radius:10px;padding:8px 10px;cursor:pointer;background:transparent;color:inherit;text-align:left;font:inherit}
.af .opt.sel{border-color:var(--border-accent);box-shadow:inset 0 0 0 2px var(--border-accent)}
.af .map{display:inline-grid;gap:0;margin:6px 0 2px;box-shadow:0 0 0 1px var(--border)}
.af .sub{font-size:11px;color:var(--text-muted)}
.af .legend{display:flex;flex-wrap:wrap;gap:10px;font-size:11px;color:var(--text-muted);margin-top:6px}
.af .legend i{display:inline-block;width:14px;height:14px;vertical-align:-3px;margin-right:3px;background-size:100% 100%;image-rendering:pixelated}
.af .sw{width:64px;height:64px;background-repeat:repeat;image-rendering:pixelated;border-radius:4px;margin:0 auto 4px}
.af .other{width:100%;box-sizing:border-box;margin-top:8px;font:inherit;padding:4px 8px;border:1px solid var(--border);border-radius:8px;background:transparent;color:inherit}
.af .send{border:0;border-radius:10px;padding:8px 18px;font:inherit;font-weight:500;cursor:pointer;background:var(--bg-accent);color:var(--text-accent)}
"""

JS = """
const Q = __QUESTIONS__, A = __INIT__, TITLE = __TITLE__;
function cell(b){ const d=document.createElement('div'); if(b) d.style.backgroundImage=`var(--t-${b})`; return d; }
function drawWall(q, k){
  const w=document.getElementById('w_'+q.i); w.innerHTML='';
  for(let r=0;r<q.rows;r++) for(let c=0;c<q.length;c++){
    let b=q.wall;
    if(q.band && r===0) b=q.band;
    else if(c>=k && c<k+q.span && r>=q.rows-q.item_rows) b=q.item;
    w.appendChild(cell(b));
  }
  document.getElementById('r_'+q.i).textContent = `${q.left}から ${k} マス`;
  A[q.name] = `${q.left}から${k}マス`;
}
function pick(i, el, v){
  el.parentNode.querySelectorAll('.opt').forEach(o=>o.classList.remove('sel'));
  el.classList.add('sel'); A[Q[i].name]=v;
}
function send(){
  const parts = Q.map(q=>{
    const o=document.getElementById('o_'+q.i).value.trim();
    return `${q.name}=${A[q.name]||'（未回答）'}${o?'（'+o+'）':''}`;
  });
  const extra=document.getElementById('o_all').value.trim();
  sendPrompt(`${TITLE} の答え: ${parts.join(' / ')}${extra?' / そのほか: '+extra:''}`);
}
document.querySelectorAll('.map[data-grid]').forEach(m=>{ const L=Q[+m.dataset.q].legend; m.dataset.grid.split('|').forEach(r=>[...r].forEach(ch=>m.appendChild(cell(L[ch])))); });
Q.forEach(q=>{ if(q.type==='slider'){ const s=document.getElementById('s_'+q.i); s.oninput=()=>drawWall(q,+s.value); drawWall(q,+s.value);} });
"""


def esc(s):
    return html.escape(str(s), quote=True)


def blocks_used(spec):
    used = set()
    for q in spec["questions"]:
        if q["type"] == "slider":
            used |= {q["wall"], q["item"]} | ({q["band"]} if q.get("band") else set())
        elif q["type"] == "choice":
            used |= set(q["legend"].values())
        elif q["type"] == "block":
            used |= set(q["options"])
    return sorted(used)


def textures(names):
    """ブロックのテクスチャを CSS の変数（--t-<名前>）にして1回だけ埋め込む（図のマスはそれを使い回す）。"""
    import block_catalog
    return ";".join(f"--t-{b}:url({block_catalog.sample_uri(b, side=32)})" for b in names)


def question(i, q):
    head = f'<div class="qt">{i + 1}. {esc(q["q"])}</div>'
    if q["type"] == "slider":
        c = max(10, min(22, 420 // q["length"]))
        w = c * q["length"]
        body = (f'<div class="wall" id="w_{i}" style="--c:{c}px; grid-template-columns:repeat({q["length"]},{c}px)"></div>'
                f'<div class="ends" style="width:{w}px"><span>◀ {esc(q["left"])}</span><span>{esc(q["right"])} ▶</span></div>'
                f'<input type="range" id="s_{i}" min="0" max="{q["length"] - q["span"]}" value="{q["guess"]}" '
                f'style="max-width:{w}px">'
                f'<div>いま: <span class="read" id="r_{i}"></span> <span class="sub">（推測は {q["guess"]} マス）</span></div>')
    elif q["type"] == "choice":
        opts = []
        for o in q["options"]:
            grid = o.get("grid", [])
            cols = max((len(r) for r in grid), default=0)
            # マスは JS で描く（1マスずつ <div> を書き出すと HTML が数百 KB になり、チャットに出せない）
            pic = (f'<div class="map" data-q="{i}" data-grid="{esc("|".join(r.ljust(cols, ".") for r in grid))}" '
                   f'style="--c:{max(6, min(16, 400 // cols))}px; grid-template-columns:repeat({cols},{max(6, min(16, 400 // cols))}px)"></div>') if grid else ""
            sel = " sel" if str(o["value"]) == str(q.get("guess")) else ""
            opts.append(f'<button type="button" class="opt{sel}" onclick=\'pick({i},this,{json.dumps(o["value"])})\'>'
                        f'<b>{esc(o.get("label", o["value"]))}</b><div class="sub">{esc(o.get("sub", ""))}</div>{pic}'
                        f'{"<div class=sub>推測</div>" if sel else ""}</button>')
        legend = "".join(f'<span><i style="background-image:var(--t-{b})"></i>{esc(b)}</span>'
                         for b in dict.fromkeys(q["legend"].values()))
        body = f'<div class="opts">{"".join(opts)}</div><div class="legend">{legend}</div>'
    elif q["type"] == "block":
        opts = []
        for b in q["options"]:
            slab = b.endswith("_slab")         # ハーフは薄く見せる（見本の絵は下半分だけ）
            sel = " sel" if b == q.get("guess") else ""
            sw = (f'<div class="sw" style="background-image:var(--t-{b}); background-size:32px {16 if slab else 32}px;'
                  f'{" height:32px; margin-top:32px;" if slab else ""}"></div>')
            opts.append(f'<button type="button" class="opt{sel}" style="width:120px; text-align:center" '
                        f'onclick=\'pick({i},this,{json.dumps(b)})\'>{sw}<div style="font-size:12px; word-break:break-all">'
                        f'{esc(b)}</div>{"<div class=sub>推測</div>" if sel else ""}</button>')
        body = f'<div class="opts">{"".join(opts)}</div>'
    else:
        raise ValueError(f"type は slider / choice / block のどれか: {q['type']}")
    return f'<div class="q">{head}{body}<input class="other" id="o_{i}" placeholder="そのほか・補足（あれば）"></div>'


def build(spec):
    qs = [dict(q, i=i, item_rows=q.get("item_rows", 3)) for i, q in enumerate(spec["questions"])]
    init = {q["name"]: q["guess"] for q in qs if q["type"] != "slider" and q.get("guess") is not None}
    js = (JS.replace("__QUESTIONS__", json.dumps(qs, ensure_ascii=False))
          .replace("__INIT__", json.dumps(init, ensure_ascii=False))
          .replace("__TITLE__", json.dumps(spec["title"], ensure_ascii=False)))
    body = "".join(question(i, q) for i, q in enumerate(qs))
    return (f'<h2 class="sr-only">{esc(spec["title"])}: {len(qs)} 個の質問</h2>'
            f'<style>{CSS}</style><div class="af" style="{textures(blocks_used(spec))}">{body}'
            f'<div class="q"><div class="qt">ほかに伝えたいことはありますか？</div>'
            f'<input class="other" id="o_all" placeholder="気づいた所があれば"></div>'
            f'<button type="button" class="send" onclick="send()">答えを送る</button></div><script>{js}</script>')


MAX_KB = 50       # ウィジェットに出すフォームの大きさの目安
MAX_DIVS = 300    # マス・繰り返しは JS で描く。<div> がこれを超えたら書き出し方を見直す


def main(path):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    out = config.work("out", f"ask_{Path(path).stem}.html")   # 作業フォルダの out/
    out.parent.mkdir(parents=True, exist_ok=True)
    html_text = build(spec)
    out.write_text(html_text, encoding="utf-8")
    # 大きいフォームはウィジェットに出せない・書き出しが遅い（マスを <div> で書いて 126KB になり失敗した 2026-10-05）
    kb, divs = len(html_text.encode("utf-8")) / 1024, html_text.count("<div")
    print(f"質問 {len(spec['questions'])} 個 → {out}（{kb:.0f}KB、<div> {divs} 個。中身を本体が show_widget の widget_code に渡す）")
    if kb > MAX_KB or divs > MAX_DIVS:
        sys.exit(f"大きすぎます（目安 {MAX_KB}KB・<div> {MAX_DIVS} 個）。質問を分けるか、図を小さくしてください")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1])
