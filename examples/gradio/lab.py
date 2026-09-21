"""UI-independent experiment logic. Node owns all compression and credentials."""
from __future__ import annotations

import copy
import csv
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone

from samples import SAMPLES

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / "artifacts" / "gradio"


class LabError(Exception):
    pass


def bridge(command, **kwargs):
    node = shutil.which("node")
    if not node:
        raise LabError("找不到 Node.js。请安装 Node.js 22+ 并执行 npm ci。")
    try:
        process = subprocess.run(
            [node, "--import", "tsx", "examples/gradio/bridge.ts"], cwd=ROOT,
            input=json.dumps({"command": command, **kwargs}, ensure_ascii=False),
            encoding="utf-8", capture_output=True, timeout=75,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if process.returncode:
            raise LabError("Node 适配进程启动失败，请确认 Node.js 22+、npm ci 和项目文件完整。")
        result = json.loads(process.stdout)
        if not result.get("ok"):
            raise LabError(result.get("error", "适配层请求失败。"))
        return result["data"]
    except subprocess.TimeoutExpired:
        raise LabError("本地操作超过 75 秒，已停止适配进程。请稍后重试。") from None
    except (OSError, json.JSONDecodeError):
        raise LabError("本地适配层不可用或响应格式异常。") from None


def evidence_present(messages, evidence):
    quote = evidence["quote"]
    if evidence["field"] == "text":
        return any(quote in m["text"] for m in messages)
    return any(r["tool_use_id"] == evidence["tool_id"] and quote in r["text"]
               for m in messages for r in m.get("toolResults", []))


def parse_input(raw):
    if len(raw) > 600_000:
        raise LabError("输入超过 600,000 字符。请缩小对话。")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise LabError(f"JSON 格式错误：第 {error.lineno} 行、第 {error.colno} 列。请检查逗号、引号和括号。") from None
    messages = value if isinstance(value, list) else value.get("messages") if isinstance(value, dict) else None
    messages = bridge("validate", messages=messages)["messages"]
    checks = value.get("checks", []) if isinstance(value, dict) else []
    if not isinstance(checks, list) or len(checks) > 30:
        raise LabError("checks 必须是最多 30 项的数组；没有验证题时可省略。")
    for i, check in enumerate(checks):
        if not isinstance(check, dict) or any(not isinstance(check.get(k), str) or not check[k] or len(check[k]) > 1000 for k in ("question", "answer")):
            raise LabError(f"第 {i+1} 个验证题需要 question 和 answer 字符串（每项最多 1000 字符）。")
        ev = check.get("evidence")
        if not isinstance(ev, dict) or ev.get("field") not in ("text", "toolResults") or not isinstance(ev.get("quote"), str) or not ev["quote"]:
            raise LabError(f"第 {i+1} 个验证题需要 evidence：field、quote，工具结果还需要 tool_id。")
        if ev["field"] == "toolResults" and not isinstance(ev.get("tool_id"), str):
            raise LabError(f"第 {i+1} 个验证题的工具证据需要 tool_id。")
        if not evidence_present(messages, ev):
            raise LabError(f"第 {i+1} 个验证题的证据在原文指定位置找不到，请核对 quote 与 tool_id。")
        groups = check.get("answer_groups", [[check["answer"]]])
        if not isinstance(groups, list) or not groups or any(not isinstance(g, list) or not g or any(not isinstance(a, str) or not a.strip() for a in g) for g in groups):
            raise LabError(f"第 {i+1} 题 answer_groups 必须是非空字符串的二维数组。")
        check["answer_groups"] = groups
    name = value.get("name", "导入对话") if isinstance(value, dict) else "导入对话"
    return {"name": str(name)[:120], "messages": messages, "checks": checks}


def options(threshold=.5, recent=2, head=300, goal=""):
    return {"keepThreshold": threshold, "preserveRecentMessages": int(recent), "truncateHeadChars": int(head), "goal": goal or ""}


def input_key(raw, recent, goal):
    # Threshold/head never affect scoring. Checks are included intentionally to invalidate old QA.
    return hashlib.sha256(json.dumps([raw, recent, goal], ensure_ascii=False).encode()).hexdigest()


def score_input(raw, threshold, recent, head, goal):
    case = parse_input(raw)
    opts = options(threshold, recent, head, goal)
    cache = bridge("score", messages=case["messages"], options=opts)
    result = bridge("reapply", messages=case["messages"], options=opts, cache=cache)
    return {"case": case, "cache": cache, "result": result, "options": opts,
            "input_key": input_key(raw, recent, goal)}


def require_current(state, raw, recent, goal):
    if not state or state.get("input_key") != input_key(raw, recent, goal):
        raise LabError("当前输入或评分设置已改变（或尚未评分）。请回到第一页点击「真实 Jev 评分」。")


def adjust(state, raw, threshold, recent, head, goal):
    require_current(state, raw, recent, goal)
    state = copy.deepcopy(state)
    state["options"] = options(threshold, recent, head, goal)
    state["result"] = bridge("reapply", messages=state["case"]["messages"], options=state["options"], cache=state["cache"])
    return state


def verification(case, variants):
    rows = []
    for check in case["checks"]:
        ev = check["evidence"]
        source = "对话正文" if ev["field"] == "text" else f"工具输出 {ev['tool_id']}"
        rows.append([check["question"], check["answer"], f"{source}：{ev['quote']}"] +
                    ["保留" if evidence_present(messages, ev) else "缺失" for messages in variants])
    return rows


def normalize(value):
    return re.sub(r"\s+", "", value).casefold()


def answer_matches(answer, check):
    # A transparent reference-keyword metric, not an LLM judge or semantic proof.
    return all(any(normalize(alias) in normalize(answer) for alias in group) for group in check["answer_groups"])


def ask_variant(case, messages):
    if not case["checks"]:
        raise LabError("此对话没有验证问题。请导入包含 checks 的格式，或选择内置样例。")
    response = bridge("answer", messages=messages, questions=[c["question"] for c in case["checks"]])
    response["matched"] = [answer_matches(a, c) for a, c in zip(response["answers"], case["checks"])]
    return response


def answer_comparison(state):
    config = bridge("config")
    if not config["answer"]:
        raise LabError("回答模型尚未配置。请按本页说明设置 .env 中的三个 ANSWER_* 配置。未生成任何模型回答或成绩。")
    case = state["case"]
    original = ask_variant(case, case["messages"])
    compressed = ask_variant(case, state["result"]["messages"])
    if original["model"] != compressed["model"]:
        raise LabError("两次请求的回答模型配置发生变化，本轮对比无效，请重新运行。")
    rows = [[c["question"], c["answer"], original["answers"][i], "匹配" if original["matched"][i] else "未匹配",
             compressed["answers"][i], "匹配" if compressed["matched"][i] else "未匹配"] for i, c in enumerate(case["checks"])]
    n = len(case["checks"])
    summary = (f"真实回答模型：{original['model']}；{n} 题，2 次请求。"
               f"标准答案要点匹配：原始 {sum(original['matched'])}/{n}；压缩后 {sum(compressed['matched'])}/{n}。"
               f"耗时 {original['ms'] + compressed['ms']:.0f} 毫秒。请逐题复核，关键词匹配不能识别所有否定、矛盾或同义改写。")
    return rows, summary


def esc(value):
    return html.escape(str(value), quote=True)


LABELS = {"keep": "保留", "drop_call": "删除", "drop_result": "截断策略"}


def transcript_html(messages, decisions=None, calls=None):
    lookup = {}
    if decisions is not None:
        lookup = {c["tool_use_id"]: d for c, d in zip(calls, decisions)}
    blocks = []
    for i, message in enumerate(messages):
        content = f'<p class="prose">{esc(message["text"])}</p>' if message["text"] else ""
        for t in message["toolUses"]:
            d = lookup.get(t["tool_use_id"], {})
            action = d.get("action", "keep")
            label = LABELS[action] + (" · 受保护" if d.get("reason") == "pinned" else "")
            content += f'<div class="tool {action}"><b>{esc(t["tool"])} · {label}</b><pre>{esc(json.dumps(t["input"], ensure_ascii=False, indent=2))}</pre></div>'
        for r in message.get("toolResults", []):
            d = lookup.get(r["tool_use_id"], {})
            action = d.get("action", "keep")
            content += f'<details class="tool {action}"><summary>{LABELS[action]} · 工具输出 {esc(r["tool_use_id"])} · 展开原文</summary><pre>{esc(r["text"])}</pre></details>'
        blocks.append(f'<article class="message"><small>{i+1:02d} · {"用户 / 工具" if message["role"] == "user" else "助手"}</small>{content}</article>')
    return '<div class="transcript">' + ("".join(blocks) or '<p class="empty">此策略没有保留任何消息。</p>') + '</div>'


EMPTY = '<div class="empty">尚未压缩。选择样例，然后点击「开始压缩」。</div>'


def batch_evaluate(threshold, recent, head, with_answers=False, progress=None):
    config = bridge("config")
    if with_answers and not config["answer"]:
        raise LabError("回答模型尚未配置，请先取消「加入真实问答」或完成 ANSWER_* 配置。")
    records, table = [], []
    opts = options(threshold, recent, head)
    for index, case in enumerate(SAMPLES):
        if progress:
            progress(index / len(SAMPLES), desc=f"样例 {index+1}/{len(SAMPLES)}：{case['name']}")
        base = bridge("recent", messages=case["messages"], options=opts)
        variants = [("完整上下文", case["messages"], base["charsBefore"], 0, 0, None),
                    ("保留最近记录", base["messages"], base["charsAfter"], base["ms"], 0, None)]
        try:
            cached = bridge("score", messages=case["messages"], options=opts)
            result = bridge("reapply", messages=case["messages"], options=opts, cache=cached)
            stats = result["stats"]
            variants.append(("Jev 压缩", result["messages"], stats["charsAfter"], stats["ms"], stats["requests"], cached))
        except LabError as error:
            records.append({"sample": case["name"], "strategy": "Jev 压缩", "status": "失败", "error": str(error)})
            table.append([case["name"], "Jev 压缩", "失败", "—", "—", "—", "未完成", "—", str(error)])
        for strategy, kept, chars, elapsed, requests, cached in variants:
            present = [evidence_present(kept, c["evidence"]) for c in case["checks"]]
            failures = [c["question"] for c, yes in zip(case["checks"], present) if not yes]
            ratio = 0 if base["charsBefore"] == 0 else 1-chars/base["charsBefore"]
            record = {"sample": case["name"], "strategy": strategy, "status": "完成", "checks": case["checks"],
                      "evidence_present": present, "missing_questions": failures, "chars_before": base["charsBefore"],
                      "chars_after": chars, "character_reduction": ratio, "compression_ms": elapsed,
                      "jev_requests": requests, "answer": None,
                      "scored_at": cached["scoredAt"] if cached else None,
                      "scores": cached["result"]["decisions"] if cached else None}
            qa_text = "未运行"
            if with_answers:
                try:
                    qa = ask_variant(case, kept)
                    if qa["model"] != config["answerModel"]:
                        raise LabError("回答模型配置在评测期间改变，本行无效。")
                    record["answer"] = qa
                    qa_text = f"{sum(qa['matched'])}/{len(present)}"
                except LabError as error:
                    record["answer_error"] = str(error)
                    qa_text = "请求失败"
            records.append(record)
            table.append([case["name"], strategy, f"{sum(present)}/{len(present)}", f"{ratio:.1%}",
                          f"{elapsed:.1f}", str(requests), qa_text,
                          f"{record['answer']['ms']:.0f}" if record["answer"] else "—",
                          "；".join(failures) or record.get("answer_error", "无证据缺失")])
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "sample_count": len(SAMPLES),
              "question_count": sum(len(c["checks"]) for c in SAMPLES), "options": opts,
              "jev_model": config["jevModel"], "answer_model": config["answerModel"] if with_answers else None,
              "method": "证据原文在指定正文/工具输出中精确包含；问答为标准答案要点匹配，须人工复核。非任务成功率。",
              "recent_rule": "仅保留最后 N 条消息，移除对应调用不在窗口内的孤立工具结果，不额外保护首条。N=0 为空。",
              "records": records}
    return table, report


def export_report(report, table):
    EXPORTS.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="evaluation-", dir=EXPORTS))
    json_path, csv_path = folder / "results.json", folder / "results.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["样例", "策略", "证据保留", "字符减少", "压缩耗时ms", "Jev请求", "问答要点匹配", "回答耗时ms", "缺失/失败"])
        # Prevent spreadsheet formula execution if any model/provider text starts with a formula.
        writer.writerows([["'"+str(v) if str(v).startswith(("=", "+", "-", "@")) else v for v in row] for row in table])
    return str(json_path), str(csv_path)
