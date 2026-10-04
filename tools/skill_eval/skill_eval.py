"""
skill_eval: Claude Code のスキルのテストを、セッションの記録（JSONL）から数字で振り返る道具。
使い方は README.md。スキルごとの設定は profiles/<名前>.json。

  python skill_eval.py <プロファイル> list    [件数]         … 最近のセッションを番号つきで並べる（1 が一番新しい）
  python skill_eval.py <プロファイル> time    [セッション]   … 何にどれくらい時間がかかったか
  python skill_eval.py <プロファイル> cite    [セッション]   … スキルのどの見出しが判断の根拠に使われたか
  python skill_eval.py <プロファイル> scan                  … スキルの文章に、特定の例だけの話がどれだけ混ざっているか
  python skill_eval.py <プロファイル> code    <ファイル>     … テストが書いたコードが、部品をどれだけ使えたか
  python skill_eval.py <プロファイル> compare [名前]         … 正解との比較（プロファイルの compare の命令を走らせる）
  python skill_eval.py <プロファイル> report  [セッション] [--code ファイル] [--compare 名前] [--images 絵1,絵2] [--with 記録1,記録2]
                                                         … 上を全部まとめて reports/ に .md と .html で保存し、history.csv に1行足す
                                                           （同じテストをもう一度 report すると、記録も history.csv の行も上書き）。
                                                           元の記録は reports/sessions/ に写して残す。--with はその回の手伝いの
                                                           Agent（並列のパーツ担当など）の記録で、usage が一緒に読む
  python skill_eval.py <プロファイル> usage   [セッション名 ...]  … 残した記録をまとめて、スキルの文書の行ごとに
                                                           「読まれたか」「効いたか」を数える（省略すると history.csv の全部の回）

[セッション] は、list の番号（例 2）・セッションID・.jsonl のパス・最初の指示に含まれる文字のどれか。
省略すると、一覧を出して止まる（今コマンドを打っているセッション自体を読まないように）。
"""

import ast
import csv
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
IDLE = 15 * 60      # 道具も動いていないのに 15 分以上なにも起きない間は、放置として作業に数えない


# ---------------- 設定と記録の読み込み ----------------

def load_profile(name):
    path = HERE / "profiles" / f"{name}.json"
    if not path.exists():
        sys.exit(f"プロファイルがありません: {path}（README の「別のスキルに使う」を参照）")
    p = json.loads(path.read_text(encoding="utf-8"))
    p["name"] = name
    p["root"] = (path.parent / p.get("root", "../../..")).resolve()     # リポジトリの一番上
    return p


def projects_dir(p):
    """Claude Code がセッションの記録を置くフォルダ。プロジェクトのパスの : と \\ と / を - にした名前。"""
    folder = re.sub(r"[:\\/]", "-", str(p["root"]))
    return Path.home() / ".claude" / "projects" / folder


def rows_of(path):
    rows = [json.loads(line) for line in open(path, encoding="utf-8")]
    if rows and all(r.get("isSidechain") for r in rows if "isSidechain" in r):
        for r in rows:                           # サブエージェントの記録（全部の行が sidechain）は、そのまま本体として読む
            r["isSidechain"] = False
    return rows


def human_text(d):
    """人が打った指示なら、その文字列（道具の結果やシステムの差し込みなら None）。"""
    if d.get("type") != "user" or d.get("isMeta"):
        return None
    c = d["message"].get("content")
    if isinstance(c, list):
        if any(x.get("type") == "tool_result" for x in c):
            return None
        c = " ".join(x.get("text", "") for x in c if x.get("type") == "text")
    c = re.sub(r"</?pasted_content[^>]*>", "", c or "").strip()   # 貼り付けた指示は囲みの中に入っている
    if (d.get("origin") or {}).get("kind") == "human":            # 人が打った印があれば、それを信じる
        return c or None
    if not c or c.startswith("<") or c.startswith("Caveat"):
        return None
    return c


def session_files(p):
    """プロジェクトのセッションの記録。新しい順（1 番が一番新しい）。"""
    d = projects_dir(p)
    files = sorted(d.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        sys.exit(f"セッションの記録がありません: {d}")
    return files


def list_sessions(p, n=15):
    """最近のセッションを番号つきで並べる（report などに番号で渡す）。"""
    L = ["番号  開始              長さ    最初の指示", "----  ----------------  ------  " + "-" * 40]
    for i, f in enumerate(session_files(p)[:n], 1):
        start, first = None, ""
        for line in open(f, encoding="utf-8"):           # 最初の指示まで読めば足りる（大きい記録を全部読まない）
            d = json.loads(line)
            start = start or d.get("timestamp")
            if (t := human_text(d)) is not None:
                start, first = d.get("timestamp", start), t
                break
        st = _t(start).astimezone() if start else None
        mins = (datetime.fromtimestamp(f.stat().st_mtime).astimezone() - st).total_seconds() / 60 if st else 0
        L.append(f"{i:>4}  {st:%Y-%m-%d %H:%M}  {mins:5.0f}分  {first[:40].replace(chr(10), ' ')}" if st
                 else f"{i:>4}  （時刻なし）")
    return "\n".join(L)


def find_session(p, arg):
    """list の番号・セッションID・.jsonl のパス・最初の指示の中の文字のどれでも。
    指定が無ければ、一覧を出して止める（今コマンドを打っているセッション自体を読んでしまわないように）。"""
    if arg and arg.endswith(".jsonl"):
        return Path(arg)
    d = projects_dir(p)
    if arg and (d / f"{arg}.jsonl").exists():
        return d / f"{arg}.jsonl"
    files = session_files(p)
    if not arg:
        sys.exit("どのセッションを読むか、番号で指定してください（例: report 2）。\n\n" + list_sessions(p))
    if arg.isdigit():
        if not 1 <= int(arg) <= len(files):
            sys.exit(f"番号 {arg} のセッションはありません。\n\n" + list_sessions(p))
        return files[int(arg) - 1]
    for f in files:
        for line in open(f, encoding="utf-8"):
            text = human_text(json.loads(line))
            if text is not None:
                if arg in text:
                    return f
                break                     # 最初の指示だけ見る（別のセッションで同じ文字を話していても拾わない）
    sys.exit(f"最初の指示に「{arg}」を含むセッションが見つかりません（{d}）")


# ---------------- 1. 時間 ----------------

def _t(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def category(p, name, inp):
    """道具の呼び出し 1 回 → 作業の分類。プロファイルの categories を上から順に当てはめる。"""
    path = str(inp.get("file_path") or inp.get("path") or "")
    cmd = str(inp.get("command") or "")
    whole = json.dumps(inp, ensure_ascii=False)
    for i, c in enumerate(p.get("categories", [])):
        if c.get("tools") and name not in c["tools"]:
            continue
        if c.get("tool_pattern") and not re.search(c["tool_pattern"], name):
            continue
        if c.get("path") and not re.search(c["path"], path, re.I):
            continue
        if c.get("command") and not re.search(c["command"], cmd):
            continue
        if c.get("input") and not re.search(c["input"], whole):
            continue
        return i, c["name"]
    return 999, "そのほか: " + (name if not name.startswith("mcp__") else "MCP の道具")


def time_report(p, path):
    rows = sorted((d for d in rows_of(path) if "timestamp" in d and not d.get("isSidechain")),
                  key=lambda d: d["timestamp"])
    calls, spent, count, first = {}, defaultdict(float), defaultdict(int), {}
    think_by, tok_by, images = defaultdict(float), defaultdict(int), []   # 考える時間・出力を「次にした作業」ごとに
    think = wait = 0.0
    pend_t, pend_k, seen, moments = 0.0, 0, set(), []
    out_tok, slow, prompts, spans, stops = 0, [], [], [], 0
    waits, stop_at = [], []                      # 返事待ちの区間と、途中で止めた時刻（流れの図に描く）
    last, turn_over = None, False                # turn_over: 発言を終えて人の番になっている
    for d in rows:
        ts = _t(d["timestamp"])
        gap = (ts - last).total_seconds() if last is not None else 0.0
        text = human_text(d)
        if text is not None and text.startswith("[Request interrupted"):
            stops += 1                           # 人が途中で止めた: そこまでは作業。止めたあとは人の番
            stop_at.append(ts)
            last, turn_over = ts, True
            continue
        if text is not None:
            if (turn_over or gap > IDLE) and last is not None:   # 発言を終えてから打つまでが返事待ち（作業中の割り込みは作業）
                wait += gap
                waits.append((last, ts))
            prompts.append((ts, text))
            last, turn_over = ts, False
            continue
        if d.get("type") not in ("assistant", "user"):
            continue
        if turn_over or gap > IDLE:              # 人の番のあいだ・放置のあいだは作業に数えない
            wait += gap
            if gap > 0:
                waits.append((last, ts))
            last = ts
            if d.get("type") == "user":
                continue
            gap = 0.0
        if d.get("type") == "assistant":
            m = d["message"]
            tok = (m.get("usage") or {}).get("output_tokens", 0)
            if m.get("id") in seen:                  # 1つの発言が「考え中・文・道具」の何行かに分かれている（数は同じ）
                tok = 0
            seen.add(m.get("id"))
            out_tok += tok
            think += max(0.0, gap)
            turn_over = m.get("stop_reason") == "end_turn"
            nxt, nxt_desc = None, ""
            for c in m.get("content", []):
                if c.get("type") == "tool_use":
                    inp = c.get("input") or {}
                    cat = category(p, c["name"], inp)
                    what = inp.get("description") or (f'{c["name"]} {Path(str(inp["file_path"])).name}' if inp.get("file_path") else c["name"])
                    calls[c["id"]] = (cat, ts, what)
                    first.setdefault(cat, ts)
                    nxt_desc = what if not nxt else nxt_desc
                    nxt = nxt or cat[1]
                    fp = str(inp.get("file_path") or "")
                    if c["name"] == "Read" and re.search(r"\.(png|jpe?g|webp|gif)$", fp, re.I):
                        images.append((ts, cat[1], fp))
            # 記録は「考え中」「文」「道具」が別々の行になるので、次に道具を呼ぶか発言を終えるまでためておく
            pend_t, pend_k = pend_t + max(0.0, gap), pend_k + tok
            if nxt or turn_over:
                nxt = nxt or "人への文章（報告・質問）"
                think_by[nxt] += pend_t
                tok_by[nxt] += pend_k
                moments.append((pend_t, ts, nxt, nxt_desc))   # 1回ごとの考える時間（長い所を見せる）
                pend_t = pend_k = 0
            last = ts
        else:
            content = d["message"].get("content")
            for c in content if isinstance(content, list) else []:
                if c.get("type") == "tool_result" and c.get("tool_use_id") in calls:
                    cat, t0, desc = calls[c["tool_use_id"]]
                    sec = (ts - t0).total_seconds()
                    spans.append((t0, ts, cat, desc))
                    count[cat] += 1
                    slow.append((sec, cat[1], desc))
            last = ts
    if not prompts:
        return "人の指示が見つかりません", {}
    # 同時に動いた道具（1つの発言で並べて呼んだ物）の時間は重ねて足さず、その間に動いていた道具の数で割る
    marks = sorted({t for a, b, *_ in spans for t in (a, b)})
    for a, b in zip(marks, marks[1:]):
        live = [cat for t0, t1, cat, _ in spans if t0 <= a and b <= t1]
        for cat in live:
            spent[cat] += (b - a).total_seconds() / len(live)
    start = prompts[0][0]
    total = (last - start).total_seconds()
    work, tool = total - wait, sum(spent.values())
    item = re.compile(r"(?:^|[\s/／　、])(\d{1,2})[.．:：=＝]")      # 「1.入口=案1 / 2.扉=…」の番号
    answers = [len(set(item.findall(t))) for _, t in prompts[1:]]
    # 指摘: 2 回目からの指示の中で、間違いを言っている文（答えとは分けて数える。言葉はプロファイルの correction_words）
    words = p.get("correction_words", ["間違", "違う", "ちがう", "おかしい", "なんで", "なぜ", "じゃない", "見れない", "できてない"])
    fixes = [(ts, x.strip()) for ts, t in prompts[1:] for x in re.split(r"[。\n/／]|(?<=[?？])", t)
             if x.strip() and any(w in x for w in words)]
    visual = [x for x in images if p.get("visual_check") and re.search(p["visual_check"], x[2])]   # 自分の描いた絵
    stats = {"work_min": round(work / 60, 1), "wait_min": round(wait / 60, 1), "tool_min": round(tool / 60, 1),
             "prompts": len(prompts), "interrupted": stops, "output_tokens": out_tok, "answer_items": sum(answers),
             "corrections": len(fixes),
             "images_viewed": len(images), "visual_checks": len(visual),
             **{f"n:{cat[1]}": count[cat] for cat in spent}}
    L = [f"# 時間の内訳: {path.name}", "",
         f"- 全体 {total / 60:.1f} 分（最初の指示 → 最後の出来事）",
         f"- 人の返事待ち {wait / 60:.1f} 分 → **作業 {work / 60:.1f} 分**"
         f"（道具の実行 {tool / 60:.1f} 分 ＋ 考える・書く {max(0, work - tool) / 60:.1f} 分）",
         f"- 人の指示 {len(prompts)} 回（2 回目からは、質問への答えか、やり直しの指示）、途中で止めた {stops} 回、出力 {out_tok:,} トークン", "",
         "| 作業 | 回数 | 時間（分） | 作業に占める割合 | 最初に出た時刻（開始から） |", "|---|---:|---:|---:|---:|"]
    for cat in sorted(spent):
        L.append(f"| {cat[1]} | {count[cat]} | {spent[cat] / 60:.1f} | {spent[cat] / max(work, 1):.0%} |"
                 f" {(first[cat] - start).total_seconds() / 60:.0f} 分 |")
    L += ["", "## 考える・書く時間の内訳（そのあとにした作業ごと）", "",
          "道具を呼ぶ前にモデルが考えて書いていた時間を、その次の作業に付けた。長いものが遅さの原因。", "",
          "| 次にした作業 | 考える・書く（分） | 出力トークン |", "|---|---:|---:|"]
    for k in sorted(think_by, key=think_by.get, reverse=True):
        L.append(f"| {k} | {think_by[k] / 60:.1f} | {tok_by[k]:,} |")
    L += ["", "上の表は「次にした作業」に付けただけなので、その作業が遅いとは限らない。何を考えていたかは、長く考えた所を見る:", "",
          "| 開始から | 考えた秒 | 直後にしたこと |", "|---:|---:|---|"]
    L += [f"| {(ts - start).total_seconds() / 60:.0f} 分 | {sec:.0f} | {k}: {str(desc)[:50]} |"
          for sec, ts, k, desc in sorted(moments, key=lambda x: x[0], reverse=True)[:8]]
    L += ["", f"## 見た画像 {len(images)} 回（うち、自分で描いた絵で出来を確かめた回数 {len(visual)} 回）", "",
          "| 開始から | 作業 | ファイル |", "|---:|---|---|"]
    L += [f"| {(ts - start).total_seconds() / 60:.0f} 分 | {cat} | {Path(fp).name} |" for ts, cat, fp in images]
    L += ["", f"## 質問への答え: {len(answers)} 回、答えた項目 {sum(answers)} 個（番号の数で数えた）"]
    L += ["", f"## 人からの指摘 {len(fixes)} 個（間違いを言っている文。やり直しの原因）", ""]
    L += [f"- {(ts - start).total_seconds() / 60:.0f} 分: {x[:100]}" for ts, x in fixes]
    L += ["", "## 時間のかかった道具 10 件", "", "| 秒 | 作業 | 内容 |", "|---:|---|---|"]
    for sec, cat, desc in sorted(slow, reverse=True)[:10]:
        L.append(f"| {sec:.0f} | {cat} | {str(desc)[:60]} |")
    L += ["", "## 人の指示（時刻は開始から）", ""]
    for ts, text in prompts:
        L.append(f"- {(ts - start).total_seconds() / 60:5.0f} 分: {text[:80].replace(chr(10), ' ')}")
    rel = lambda t: round((t - start).total_seconds(), 1)   # 開始からの秒
    stats["_data"] = {
        "total": round(total, 1), "work": round(work, 1), "wait": round(wait, 1), "tool": round(tool, 1),
        "think": round(max(0.0, work - tool), 1), "tokens": out_tok,
        "categories": [{"name": cat[1], "count": count[cat], "tool": round(spent[cat], 1),
                        "think": round(think_by.get(cat[1], 0.0), 1)} for cat in sorted(spent)]
                      + [{"name": k, "count": 0, "tool": 0.0, "think": round(v, 1)}
                         for k, v in think_by.items() if k not in {c[1] for c in spent}],
        "spans": [{"t0": rel(a), "t1": rel(b), "cat": cat[1], "what": str(w)[:80]} for a, b, cat, w in spans],
        "thinks": [{"t0": round(rel(ts) - sec, 1), "t1": rel(ts), "next": k, "what": str(w)[:80]}
                   for sec, ts, k, w in moments if sec >= 1],
        "waits": [{"t0": rel(a), "t1": rel(b)} for a, b in waits if b > a],
        "prompts": [{"t": rel(ts), "text": t[:200]} for ts, t in prompts],
        "stops": [rel(t) for t in stop_at],
        "fixes": [{"t": rel(ts), "text": x[:160]} for ts, x in fixes],
        "images": [{"t": rel(ts), "cat": c, "file": Path(fp).name,
                    "own": bool(p.get("visual_check") and re.search(p["visual_check"], fp))} for ts, c, fp in images],
        "slow": [{"sec": round(sec, 1), "cat": c, "what": str(w)[:80]} for sec, c, w in sorted(slow, reverse=True)[:10]],
        "moments": [{"t": rel(ts), "sec": round(sec, 1), "next": k, "what": str(w)[:80]}
                    for sec, ts, k, w in sorted(moments, key=lambda x: x[0], reverse=True)[:8]],
    }
    return "\n".join(L), stats


# ---------------- 2. どの見出しが根拠に使われたか ----------------

def headings(p):
    """スキルの見出し → (ファイル, 見出し, 引用を数える正規表現)。プロファイルの cite.rules を上から当てはめる。
    どのルールにも当たらない見出しは、見出しの短い名前（括弧の前）がそのまま書かれていれば数える。"""
    skill = p["root"] / p["skill_dir"]
    rules = p.get("cite", {}).get("rules", [])
    out = []
    for doc in p["docs"]:
        for line in (skill / doc["file"]).read_text(encoding="utf-8").splitlines():
            m = re.match(r"(#{2,6}) (.+)", line)
            if not m or len(m.group(1)) not in doc.get("levels", [2, 3]):
                continue
            h = m.group(2).strip()
            pat = None
            for r in rules:
                if r.get("file", doc["file"]) != doc["file"]:
                    continue
                mm = re.match(r["heading"], h)
                if not mm:
                    continue
                if r.get("skip"):
                    pat = ""
                    break
                pat = r["pattern"]
                for i, g in enumerate(mm.groups(), 1):
                    pat = pat.replace("{%d}" % i, re.escape(g.strip()) if g else "")
                break
            if pat == "":
                continue
            if pat is None:
                pat = re.escape(re.split(r"[（(:：]", h)[0].strip())
            out.append((doc["file"], h, pat))
    return out


def heading_bodies(p, limit=160):
    """(ファイル, 見出し) → 見出しの下の本文の初め（何が書いてあるかを、レポートで見せる）。"""
    skill, out = p["root"] / p["skill_dir"], {}
    for doc in p["docs"]:
        cur, buf = None, []
        for line in (skill / doc["file"]).read_text(encoding="utf-8").splitlines() + ["## (end)"]:
            m = re.match(r"(#{2,6}) (.+)", line)
            if m:
                if cur:
                    text = " ".join(l.strip(" |-*`>") for l in buf if l.strip() and not set(l.strip()) <= set("|-: "))
                    out[(doc["file"], cur)] = re.sub(r"\s+", " ", text)[:limit]
                cur, buf = m.group(2).strip(), []
            else:
                buf.append(line)
    return out


def basis_lines(p, path):
    """セッションの中の「根拠」の行（アシスタントの文と、書いたファイルの中身から）。"""
    word = p.get("cite", {}).get("basis_word", "根拠")
    texts = []
    for d in rows_of(path):
        if d.get("type") != "assistant" or d.get("isSidechain"):
            continue
        for c in d["message"].get("content", []):
            if c.get("type") == "text":
                texts.append(c["text"])
            elif c.get("type") == "tool_use" and c["name"] in ("Write", "Edit"):
                inp = c.get("input") or {}
                texts.append(inp.get("content") or inp.get("new_string") or "")
            elif c.get("type") == "tool_use" and c["name"] in ("SubagentHandback", "SendMessage"):
                texts.append((c.get("input") or {}).get("message") or "")   # サブエージェントの最後の報告はここに書かれる
    return [line for t in texts for line in t.splitlines() if word in line]


def cite_report(p, path):
    basis = basis_lines(p, path)
    none_pat = p.get("cite", {}).get("none", r"根拠[:：]\s*なし")
    no = [l.strip() for l in basis if re.search(none_pat, l)]
    used, never = [], []
    for f, h, pat in headings(p):
        n = sum(bool(re.search(pat, l)) for l in basis)
        (used if n else never).append((f, h, n))
    stats = {"basis_lines": len(basis), "basis_none": len(no), "headings_used": len(used), "headings_never": len(never)}
    L = [f"# どの見出しが判断の根拠に使われたか: {path.name}", "",
         f"- 根拠の行 {len(basis)} 行、そのうちスキルに無い判断（根拠なし） {len(no)} 行",
         f"- 見出し {len(used) + len(never)} 個のうち、使われた {len(used)} 個・一度も使われなかった {len(never)} 個", "",
         "| ファイル | 見出し | 使われた回数 |", "|---|---|---:|"]
    L += [f"| {f} | {h[:50]} | {n} |" for f, h, n in used]
    body = heading_bodies(p)
    L += ["", "## 一度も使われなかった見出し（何回かのテストで続けて 0 なら、削る候補）", "",
          "| ファイル | 見出し | 書いてあること（初めの部分） |", "|---|---|---|"]
    L += [f"| {f} | {h[:40]} | {body.get((f, h), '').replace('|', '／')} |" for f, h, _ in never]
    if no:
        L += ["", "## スキルに無い判断（足す候補）", ""] + [f"- {x[:100]}" for x in no[:30]]
    stats["_data"] = {"used": [{"file": f, "heading": h, "n": n} for f, h, n in used],
                      "never": [{"file": f, "heading": h, "body": body.get((f, h), "")} for f, h, _ in never],
                      "none": [x[:160] for x in no[:30]], "basis": len(basis)}
    return "\n".join(L), stats


# ---------------- 3. スキルの文章 ----------------

def scan_report(p):
    skill = p["root"] / p["skill_dir"]
    words = [w for w in p.get("specific_words", [])]
    L = ["# スキルの文章: 特定の例だけの話がどれだけ混ざっているか", "",
         f"数える言葉: {'、'.join(words) or '（プロファイルの specific_words が空）'}", ""]
    for doc in p["docs"]:
        lines = [l for l in (skill / doc["file"]).read_text(encoding="utf-8").splitlines() if l.strip()]
        cur, per = "（冒頭）", defaultdict(lambda: [0, 0])
        for l in lines:
            if l.startswith("#"):
                cur = l.lstrip("# ").strip()
                continue
            per[cur][0] += 1
            per[cur][1] += any(w in l for w in words)
        n_all, n_hit = sum(v[0] for v in per.values()), sum(v[1] for v in per.values())
        L += [f"## {doc['file']}: 中身の行 {n_all} 行のうち、特定の例の言葉が出る行 {n_hit} 行（{n_hit / max(n_all, 1):.0%}）", "",
              "| 見出し | 行 | 特定の例の行 | 割合 |", "|---|---:|---:|---:|"]
        L += [f"| {h[:40]} | {n} | {k} | {k / n:.0%} |" for h, (n, k) in per.items() if k]
        L.append("")
    lib = p.get("library")
    if lib:                                      # 部品のライブラリと、スキルの文章の対応
        tree = ast.parse((p["root"] / lib["path"]).read_text(encoding="utf-8"))
        defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}
        text = "".join((skill / d["file"]).read_text(encoding="utf-8") for d in p["docs"])
        mod = re.escape(lib["module"])
        named = set(re.findall(rf"{mod}\.([a-z_]\w*)\(", text)) | set(re.findall(r"`([a-z_]\w*)`", text))
        inner = set(lib.get("internal", []))
        L += ["## 部品とスキルの文章の対応", "",
              f"- スキルに書かれていない部品（使い方が伝わらない）: {', '.join(sorted(defined - named - inner)) or 'なし'}",
              f"- スキルに書かれているのに無い部品: "
              f"{', '.join(sorted(set(re.findall(rf'{mod}[.]([a-z_]\w*)[(]', text)) - defined)) or 'なし'}"]
    return "\n".join(L)


# ---------------- 3.5 スキルの行ごとの「読まれた・効いた」（何回かのテストをまとめて） ----------------

USAGE_SKIP = {"parts.py", "run.py", "c.put", "G", "F", "top"}


def usage_marks(line):
    """行の目印: `…` の中身（関数なら名前だけ・ブロックなら [ ] の前だけ）、「…」の中身、法則N・Step N。"""
    m = set()
    for t in re.findall(r"`([^`]{2,200})`", line):
        script = re.search(r"[\w./-]+\.py\b", t) if " " in t.strip() else None
        t = script.group(0).split("/")[-1] if script else re.split(r"[(\[]", t.strip())[0].strip()   # コマンドはスクリプトの名前で探す
        if len(t) >= 3 and t not in USAGE_SKIP:
            m.add(t)
    m |= set(re.findall(r"「([^」]{2,30})」", line))
    m |= {t.replace(" ", "") for t in re.findall(r"(法則\s?\d+|Step\s?\d)", line)}
    return m


def usage_scan(p, paths):
    """1回のテストの記録（手伝いの Agent も含む）から、開いたスキルの行と、Agent が書いた文字。"""
    skill = p["root"] / p["skill_dir"]
    files = p.get("usage_docs") or [d["file"] for d in p["docs"]]
    sizes = {f: len((skill / f).read_text(encoding="utf-8").splitlines()) for f in files}
    folder = p["skill_dir"].split("/")[-1]
    opened, out = defaultdict(set), []
    for path in paths:
        for d in rows_of(path):
            if d.get("type") != "assistant":
                continue
            for b in d["message"].get("content", []):
                if not isinstance(b, dict):
                    continue
                if b.get("type") in ("text", "thinking"):
                    out.append(b.get("text") or b.get("thinking") or "")
                    continue
                if b.get("type") != "tool_use":
                    continue
                name, inp = b.get("name"), b.get("input") or {}
                fp = str(inp.get("file_path") or inp.get("path") or "").replace("\\", "/")
                cmd = str(inp.get("command") or "")
                for f, n in sizes.items():
                    if name == "Read" and fp.endswith(f"{folder}/{f}"):
                        off = int(inp.get("offset") or 1)
                        opened[f] |= set(range(off, min(n, off + int(inp.get("limit") or 2000) - 1) + 1))
                    elif name in ("Bash", "PowerShell") and f in cmd and re.search(r"\b(cat|type|Get-Content|head|tail|sed)\b", cmd):
                        opened[f] |= set(range(1, n + 1))
                if name in ("Write", "Edit", "MultiEdit", "Bash", "PowerShell", "SubagentHandback", "SendMessage", "AskUserQuestion"):
                    out.append(json.dumps(inp, ensure_ascii=False))
    return opened, "\n".join(out), sizes


def usage_report(p, names=()):
    """残した記録（reports/sessions/）をまとめて、スキルの文書の行ごとに数える。
    読まれた = どれかの回で、その行を開いた（Read の範囲・cat など）。
    効いた   = その行の目印が、Agent の書いた物（考えの文・コード・報告・質問）に出た（ブロック名・部品名・「」の言葉・法則N）。"""
    sess = HERE / "reports" / "sessions"
    hist = HERE / "reports" / "history.csv"
    if not names:
        names = [r["session"] for r in csv.DictReader(open(hist, encoding="utf-8-sig")) if r.get("profile") == p["name"]]
    runs = {}
    for n in names:
        main = sess / f"{n}.jsonl"
        if not main.exists():
            print(f"注意: {main} がありません（report でまだ残していない回）")
            continue
        runs[n] = [main] + sorted((sess / f"{n}_with").glob("*.jsonl"))
    data = {n: usage_scan(p, ps) for n, ps in runs.items()}
    skill = p["root"] / p["skill_dir"]
    sizes = next(iter(data.values()))[2] if data else {}
    squash = lambda t: re.sub(r"\s", "", t)
    outs = {n: squash(o) for n, (_, o, _) in data.items()}
    L = [f"# スキルの行ごとの「読まれた・効いた」（{len(runs)} 回: {', '.join(runs)}）", "",
         "- 読まれた = どれかの回でその行を開いた。効いた = その行の目印（`…`・「…」・法則N）が Agent の書いた物に出た",
         "- 目印の無い行（文章だけの行）は効いたかを数えられないので、見出しごとの表の「目印なし」に入れる",
         "- スキルの文書は今の版で数える（前の回が読んだのは古い版なので、行の位置は目安）", "",
         "## ファイルを開いた回", ""]
    for f, n in sizes.items():
        cells = []
        for k, (op, _, _) in data.items():
            got = len(op.get(f, ()))
            cells.append(f"{k}: " + ("全部" if got >= n else f"{got}/{n}行" if got else "開いていない"))
        L.append(f"- {f}（{n}行）… " + " ／ ".join(cells))
    never_read, never_eff, per = [], [], {}
    for f in sizes:
        cur = "（先頭）"
        for i, line in enumerate((skill / f).read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("#"):
                cur = line.lstrip("# ").strip()
            if not line.strip() or line.startswith("```") or set(line.strip()) <= set("|-: "):
                continue
            s = per.setdefault((f, cur), {"lines": 0, "unread": 0, "nomark": 0, "eff": 0, "runs": set()})
            s["lines"] += 1
            read_in = [k for k, (op, _, _) in data.items() if i in op.get(f, ())]
            if not read_in:
                s["unread"] += 1
                never_read.append((f, i, cur, line))
                continue
            mk = usage_marks(line)
            if not mk:
                s["nomark"] += 1
                continue
            eff = [k for k in read_in if any(squash(m) in outs[k] for m in mk)]
            if eff:
                s["eff"] += 1
                s["runs"] |= set(eff)
            else:
                never_eff.append((f, i, cur, line, sorted(mk)))
    L += ["", f"## 一度も読まれなかった行（{len(never_read)} 行）", ""]
    L += [f"- {f}:{i}［{h[:30]}］ {l.strip()[:120]}" for f, i, h, l in never_read] or ["（なし）"]
    L += ["", f"## 読まれたのに、目印が一度も出なかった行（{len(never_eff)} 行）… 削る・書き直す候補", ""]
    L += [f"- {f}:{i}［{h[:30]}］ {l.strip()[:120]}  ← 目印: {', '.join(mk)[:80]}" for f, i, h, l, mk in never_eff] or ["（なし）"]
    L += ["", "## 見出しごと", "", "| ファイル | 見出し | 行 | 読まれなかった | 目印なし | 効いた行 | 効いた回 |",
          "|---|---|---:|---:|---:|---:|---|"]
    L += [f"| {f} | {h[:40]} | {s['lines']} | {s['unread']} | {s['nomark']} | {s['eff']} | {','.join(sorted(s['runs'])) or '—'} |"
          for (f, h), s in per.items()]
    out = HERE / "reports" / f"{datetime.now():%Y%m%d-%H%M}_{p['name']}_usage.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    return f"記録: {out}\n読まれなかった行 {len(never_read)}、読まれたのに効かなかった行 {len(never_eff)}"


# ---------------- 4. テストが書いたコード ----------------

def code_report(p, file):
    c = p.get("code", {})
    path = Path(file)
    if not path.is_absolute():
        path = p["root"] / c.get("dir", "") / file
        if not path.suffix and not path.is_dir():
            path = path.with_suffix(".py")
    if path.is_dir():   # パーツに分けた設計（フォルダ）は、中の .py を全部つないで1つとして見る
        src = "\n".join(f.read_text(encoding="utf-8") for f in sorted(path.glob("*.py")))
    else:
        src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lib = c.get("library")
    lo, hi = c.get("number_min", 100), c.get("number_max", 10 ** 6)

    def draws(f):   # 絵を描く関数（画素の数は座標ではない）
        return any(isinstance(n, ast.Name) and n.id in ("Image", "ImageDraw", "ImageFont")
                   or isinstance(n, ast.Attribute) and n.attr in ("Draw", "ImageDraw") for n in ast.walk(f))
    skip = {id(n) for f in tree.body if isinstance(f, ast.FunctionDef) and draws(f) for n in ast.walk(f)}
    skip |= {id(n) for k in ast.walk(tree) if isinstance(k, ast.keyword) and k.arg in c.get("skip_keywords", [])
             for n in ast.walk(k)}
    skip |= {id(n) for t in ast.walk(tree) if isinstance(t, ast.Tuple) and len(t.elts) in (3, 4)   # 色の組 (赤, 緑, 青[, 透明度]) は座標ではない
             and all(isinstance(e, ast.Constant) and type(e.value) is int and 0 <= e.value <= 255 for e in t.elts)
             for n in t.elts}
    lib_calls, manual, numbers = defaultdict(int), defaultdict(int), []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if lib and isinstance(node.func.value, ast.Name) and node.func.value.id == lib:
                lib_calls[node.func.attr] += 1
            if node.func.attr in c.get("manual_calls", []):
                manual[node.func.attr] += 1
        if isinstance(node, ast.Constant) and type(node.value) in (int, float) and lo <= abs(node.value) < hi:
            numbers.append(node.value)
    stats = {"code_lines": len(src.splitlines()), "library_calls": sum(lib_calls.values()),
             "manual_calls": sum(manual.values()), "hardcoded_numbers": len(numbers)}
    L = [f"# テストが書いたコード: {path.name}", "",
         f"- 全体 {len(src.splitlines())} 行",
         f"- 部品（{lib}）の呼び出し {sum(lib_calls.values())} 回: " + "、".join(f"{k}×{v}" for k, v in sorted(lib_calls.items())),
         f"- 手で書いた所（{'・'.join(c.get('manual_calls', [])) or 'なし'}） {sum(manual.values())} か所 … 多いほど部品が足りない",
         f"- 直書きの数（{lo} 以上）{len(numbers)} 個 {sorted(set(numbers))[:12]} … 座標などの直書きの候補"]
    for name, pat in c.get("count_patterns", {}).items():   # プロファイルで足す数え方（例: 地面から数えた高さ）
        n = len(re.findall(pat, src))
        stats[f"pattern:{name}"] = n
        L.append(f"- {name}: {n} か所")
    stats["_data"] = {"file": path.name, "lib": lib, "lib_calls": dict(lib_calls), "numbers": sorted(set(numbers))[:30],
                      "patterns": {k[8:]: v for k, v in stats.items() if k.startswith("pattern:")}}
    return "\n".join(L), stats


# ---------------- 5. 正解との比較 ----------------

def compare_report(p, name):
    cfg = p.get("compare")
    if not cfg:
        return "（プロファイルに compare がありません）", {}
    cmd = cfg["command"].replace("{name}", name or cfg.get("default_name", ""))
    r = subprocess.run(cmd, shell=True, cwd=p["root"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    out = (r.stdout + r.stderr).strip()
    stats = {}
    for key, pat in cfg.get("metrics", {}).items():          # 出力から数字を拾う（例: 違い: 123 マス）
        m = re.search(pat, out)
        if m:
            stats[key] = int(m.group(1))
    stats["_data"] = {"name": name, "command": cmd, "output": out[-6000:]}
    return f"# 正解との比較: {name}\n\n命令: `{cmd}`\n\n```\n{out[-6000:]}\n```", stats


# ---------------- 分析（数字から、直す候補を言葉にする） ----------------

def analyze(p, row, data, prev):
    """記録の数字から「分かったこと」と「早く・正しくするための候補」を作る。決めつけず、候補として出す。"""
    out = []
    t = data.get("time", {})
    work, think, tool, wait = t.get("work", 0), t.get("think", 0), t.get("tool", 0), t.get("wait", 0)
    if work:
        share = think / work
        top = t.get("moments", [])[:3]
        if share >= 0.6:
            out.append({"level": "warn", "title": f"作業時間の {share:.0%} は、モデルが考えて書いている時間でした",
                        "detail": "道具（コマンドやファイルの読み書き）を速くしても、全体はあまり速くなりません。"
                                  "長く考えた所: " + " ／ ".join(f"{m['t'] / 60:.0f}分 {m['sec']:.0f}秒 → {m['next']}" for m in top),
                        "action": "長く考えた所の直前にしていたことを見て、その判断に必要な材料（決まり・手順・例）をスキルに具体的に書く。迷う時間が減る"})
        cats = sorted(t.get("categories", []), key=lambda c: c["tool"], reverse=True)
        if cats and tool and cats[0]["tool"] / work >= 0.15:
            c = cats[0]
            out.append({"level": "warn", "title": f"道具では「{c['name']}」に一番時間がかかりました（{c['tool'] / 60:.1f} 分・{c['count']} 回）",
                        "detail": "", "action": "回数を減らすか（一度で決まるようにスキルを直す）、その処理自体を速くする"})
        if wait / max(work + wait, 1) >= 0.3:
            out.append({"level": "info", "title": f"人の返事待ちが {wait / 60:.1f} 分ありました",
                        "detail": "", "action": "質問を1回にまとめる・答えやすい形にすると短くなる"})
    if row.get("corrections"):
        out.append({"level": "warn", "title": f"人からの指摘が {row['corrections']} 個ありました（一発ではできていない所）",
                    "detail": " ／ ".join(f["text"] for f in t.get("fixes", [])[:5]),
                    "action": "指摘の中身を、スキルの決まりとして書き足す（次のテストで同じ指摘が出ないか確かめる）"})
    elif row.get("prompts"):
        out.append({"level": "good", "title": "人からの指摘はありませんでした", "detail": "", "action": ""})
    c = data.get("cite")
    if c:
        if c["never"]:
            out.append({"level": "info", "title": f"スキルの見出し {len(c['never'])} 個は、判断に一度も使われませんでした",
                        "detail": "、".join(n["heading"][:20] for n in c["never"][:8]),
                        "action": "1回では削らない。何回かのテストで続けて使われなければ、削る候補"})
        if c["none"]:
            out.append({"level": "info", "title": f"スキルに書いていない判断が {len(c['none'])} 個ありました",
                        "detail": " ／ ".join(c["none"][:3]), "action": "何度も出る判断なら、スキルに書き足す"})
        if not c["basis"]:
            out.append({"level": "warn", "title": "「根拠: 〜」の行が見つかりませんでした",
                        "detail": "", "action": "テストのプロンプトに、根拠を書く決まりを入れる（README の使い方 1.）"})
    for key, g in (p.get("goals") or {}).items():           # ゴールとの比較
        if key not in row or row[key] in ("", None):
            continue
        v, target, lower = float(row[key]), float(g["target"]), g.get("better", "lower") == "lower"
        ok = v <= target if lower else v >= target
        if not ok:
            out.append({"level": "warn", "title": f"{g.get('label', key)}: ゴール {g['target']} に対して {row[key]}",
                        "detail": "", "action": g.get("hint", "")})
    if prev:                                                  # 前の回との差
        for key, label in (("work_min", "作業時間（分）"), ("corrections", "指摘"), ("diff_cells", "正解との違い")):
            try:
                a, b = float(prev[key]), float(row[key])
            except (KeyError, ValueError, TypeError):
                continue
            if a != b:
                better = b < a
                out.append({"level": "good" if better else "warn",
                            "title": f"前の回より{label}が{'減りました' if better else '増えました'}（{prev[key]} → {row[key]}）",
                            "detail": f"前の回: {prev.get('started', prev.get('date', ''))}", "action": ""})
    return out


# ---------------- HTML（人が読む形。見た目は templates/report.html） ----------------

def render_html(payload, images=()):
    """templates/report.html にデータ（JSON）と比べる絵を流し込む。絵は「ラベル=パス」か「パス」。2枚ずつ組にして比べる。"""
    import base64
    pics = []
    for i, item in enumerate(images):
        label, _, path = item.rpartition("=") if "=" in item else (Path(item).stem, "", item)
        path = Path(path)
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.exists():
            mime = "image/" + {"jpg": "jpeg"}.get(path.suffix[1:].lower(), path.suffix[1:].lower())
            pics.append({"label": label, "src": f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()})
    payload = {**payload, "images": pics}
    tpl = (HERE / "templates" / "report.html").read_text(encoding="utf-8")
    js = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")   # </script> で切れないように
    return tpl.replace("/*__DATA__*/null", js)


# ---------------- まとめて残す ----------------

def keep_session(path, helpers=()):
    """元の記録を reports/sessions/ に写して残す（スクラッチパッドなどの一時的な場所は消えるため）。
    helpers はその回の手伝いの Agent の記録で、sessions/<名前>_with/ に写す。"""
    d = HERE / "reports" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    if path.resolve() != (d / f"{path.stem}.jsonl").resolve():
        shutil.copyfile(path, d / f"{path.stem}.jsonl")
    if helpers:
        w = d / f"{path.stem}_with"
        w.mkdir(exist_ok=True)
        for h in helpers:
            shutil.copyfile(h, w / Path(h).name)
    return d / f"{path.stem}.jsonl"


def report(p, session, code_file=None, compare_name=None, images=(), helpers=()):
    path = find_session(p, session)
    kept = keep_session(path, helpers)
    parts, data, row = [], {}, {"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "profile": p["name"], "session": path.stem}
    for key, (text, stats) in (("time", time_report(p, path)), ("cite", cite_report(p, path)),
                               ("code", code_report(p, code_file) if code_file else ("", {})),
                               ("compare", compare_report(p, compare_name) if compare_name is not None else ("", {}))):
        if text:
            parts.append(text)
        if "_data" in stats:
            data[key] = stats.pop("_data")           # HTML 用のくわしいデータ（history.csv には入れない）
        row.update(stats)
    t0, first = next(((d["timestamp"], t) for d in rows_of(path) if "timestamp" in d and (t := human_text(d))), ("", ""))
    row["prompt"] = first[:40].replace("\n", " ")
    stamp = _t(t0).astimezone() if t0 else datetime.now()
    row["started"] = stamp.strftime("%Y-%m-%d %H:%M")
    out = HERE / "reports"
    out.mkdir(exist_ok=True)
    # 名前はテストを始めた日時から付ける（同じテストを何回 report しても、同じファイルを上書きする）
    md = out / f"{stamp:%Y%m%d-%H%M}_{p['name']}_{path.stem[:8]}.md"
    text = (f"# スキルのテストの記録（{p['name']}）\n\n- 日時 {row['date']}\n- セッション {path.stem}\n"
            f"- 元の記録: {kept.relative_to(HERE)}" + (f"（手伝いの Agent {len(helpers)} 人の記録つき）" if helpers else "") + "\n"
            f"- 最初の指示: {row['prompt']}\n\n" + "\n\n---\n\n".join(parts) + "\n")
    md.write_text(text, encoding="utf-8")
    hist = out / "history.csv"                   # テストを重ねたときの移り変わり（1 テスト 1 行）
    old = list(csv.DictReader(open(hist, encoding="utf-8-sig"))) if hist.exists() else []
    old = [r for r in old if (r.get("profile"), r.get("session")) != (row["profile"], row["session"])]   # 同じテストは最新の1行だけ
    keys = list(dict.fromkeys([k for r in old for k in r] + list(row)))
    with open(hist, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(old + [row])
    runs = sorted((r for r in old + [row] if r.get("profile") == p["name"]), key=lambda r: r.get("started", ""))
    before = [r for r in runs if r.get("started", "") < row["started"]]
    payload = {"profile": p["name"], "row": row, "data": data, "goals": p.get("goals") or {},
               "findings": analyze(p, row, data, before[-1] if before else None),
               "history": runs, "markdown": text}
    page = md.with_suffix(".html")               # 人が読む形（見た目は templates/report.html）
    page.write_text(render_html(payload, images), encoding="utf-8")
    return f"記録: {md}\nHTML: {page}\n履歴: {hist}（テスト {len(old) + 1} 件）"


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    p, cmd, rest = load_profile(argv[0]), argv[1], argv[2:]
    opt = lambda flag: rest[rest.index(flag) + 1] if flag in rest else None
    pos = [a for i, a in enumerate(rest) if not a.startswith("--") and (i == 0 or not rest[i - 1].startswith("--"))]
    arg = pos[0] if pos else None
    if cmd == "time":
        print(time_report(p, find_session(p, arg))[0])
    elif cmd == "cite":
        print(cite_report(p, find_session(p, arg))[0])
    elif cmd == "list":
        print(list_sessions(p, int(arg) if arg and arg.isdigit() else 15))
    elif cmd == "scan":
        print(scan_report(p))
    elif cmd == "code":
        print(code_report(p, arg)[0])
    elif cmd == "compare":
        print(compare_report(p, arg)[0])
    elif cmd == "report":
        imgs = [x for x in (opt("--images") or "").split(",") if x]
        helpers = [x for x in (opt("--with") or "").split(",") if x]
        print(report(p, arg, opt("--code"), opt("--compare") if "--compare" in rest else None, imgs, helpers))
    elif cmd == "usage":
        print(usage_report(p, pos))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
