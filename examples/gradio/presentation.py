"""Aligned, escaped presentation of the library's actual output."""
import html
import json


def esc(value):
    return html.escape(str(value), quote=True)


def message_body(message, scores=None):
    if message is None:
        return '<div class="removed">已删除 · 原始内容仍可在左侧查看</div>'
    parts = [f'<p class="prose">{esc(message["text"])}</p>'] if message['text'] else []
    for tool in message['toolUses']:
        parts.append(f'<div class="tool-title">{esc(tool["tool"])} <small>{esc(tool["tool_use_id"])}</small></div>')
        parts.append(f'<pre>{esc(json.dumps(tool["input"], ensure_ascii=False, indent=2))}</pre>')
        if scores and tool['tool_use_id'] in scores:
            decision, label = scores[tool['tool_use_id']]
            details = '<p>受保护的记录直接保留，未调用 Jev 评分。</p>' if decision['reason'] == 'pinned' else ''
            if decision['reason'] != 'pinned':
                for key, name in [('keepCall', '保留调用'), ('keepResult', '保留输出')]:
                    value = decision[key]
                    details += (f'<div class="bar-row"><span>{name}</span><meter min="0" max="1" value="{max(0,min(1,value))}"></meter>'
                                f'<b>{value:.3f}</b></div>')
            parts.append(f'<details class="inline-score"><summary>处理：{label} · 查看评分</summary>{details}</details>')
    for result in message.get('toolResults', []):
        parts.append(f'<details class="output"><summary>查看工具输出 · {esc(result["tool_use_id"])}</summary><pre>{esc(result["text"])}</pre></details>')
    return ''.join(parts) or '<span class="muted">空消息</span>'


def comparison_html(original, result=None):
    aligned = dict(zip(result['sourceIndices'], result['messages'])) if result else {}
    decisions = {c['tool_use_id']: d for c, d in zip(result['calls'], result['decisions'])} if result else {}
    after_results = {r['tool_use_id']: r['text'] for m in aligned.values() for r in m.get('toolResults', [])}
    before_results = {r['tool_use_id']: r['text'] for m in original for r in m.get('toolResults', [])}
    scores = {}
    for identifier, decision in decisions.items():
        if decision['action'] == 'drop_call':
            label = '删除调用及输出'
        elif before_results.get(identifier) != after_results.get(identifier):
            label = '截断输出'
        else:
            label = '受保护，保留原文' if decision['reason'] == 'pinned' else '保留原文'
        scores[identifier] = (decision, label)
    rows = []
    for i, message in enumerate(original):
        current = aligned.get(i)
        ids = [t['tool_use_id'] for t in message['toolUses']] + [r['tool_use_id'] for r in message.get('toolResults', [])]
        if not result:
            style, label = 'pending', '待压缩'
        elif current is None:
            style, label = 'deleted', '已删除'
        elif any(decisions.get(identifier, {}).get('action') == 'drop_call' for identifier in ids):
            style, label = 'trimmed', '部分删除'
        elif any(before_results.get(identifier) != after_results.get(identifier) for identifier in ids):
            style, label = 'trimmed', '已截断'
        else:
            style, label = 'retained', '保留'
        role = '工具输出' if message.get('toolResults') else '用户' if message['role'] == 'user' else '助手'
        right = message_body(current) if result else '<div class="muted">开始压缩后，在此对照同一条记录。</div>'
        rows.append(f'<section class="compare-row {style}" aria-label="原始记录 {i+1}">'
                    f'<div class="record-label"><b>#{i+1:02d} · {role}</b><span class="badge">{label}</span></div>'
                    f'<div class="pair"><article><small class="side-name">原始</small>{message_body(message, scores)}</article>'
                    f'<article><small class="side-name">压缩后</small>{right}</article></div></section>')
    return '<div class="comparison"><div class="compare-head"><b>原始对话</b><b>压缩后</b></div>' + ''.join(rows) + '</div>'


def render_result(state):
    result = state['result']
    stats = result['stats']
    before, after = stats['charsBefore'], stats['charsAfter']
    ratio = 0 if not before else (before-after)/before
    summary = (f'<div class="result-summary"><div><small>上下文字符减少</small><strong>{ratio:.1%}</strong></div>'
               f'<div><b>{before:,} → {after:,} 字符</b><p>{stats["messagesBefore"]} → {stats["messagesAfter"]} 条消息 · '
               f'评分耗时 {stats["ms"] / 1000:.2f} 秒</p><small>是否丢失关键信息，还需下一步验证。</small></div></div>'
               f'<details class="run-details"><summary>运行详情与统计口径</summary><p>真实 Jev 评分请求 {stats["requests"]} 次；'
               f'本次本地应用分数 {stats["localMs"]:.1f} ms，新增 API 请求 0 次。</p>'
               f'<p>评分时间：{esc(result["scoredAt"])} · 模型：{esc(result["model"])} · 保留阈值：{state["options"]["keepThreshold"]}</p>'
               '<p>字符按 JavaScript UTF-16 长度统计正文、工具输入 JSON 和输出，不等同于 token 或费用节省。</p></details>')
    return summary, comparison_html(state['case']['messages'], result)
