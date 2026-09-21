"""Question-centered evidence and answer comparison, with explicit limits."""
from presentation import esc
from lab import evidence_present


def preparation(state, config):
    model = config['answerModel'] if config['answer'] else '未配置回答模型，可先仅检查原文'
    if not state:
        return '<div class="empty">请先在第一页完成压缩，再来验证这份结果。</div>'
    case, stats = state['case'], state['result']['stats']
    reduction = 0 if not stats['charsBefore'] else 1-stats['charsAfter']/stats['charsBefore']
    questions = ''.join(f'<li>{esc(c["question"])}</li>' for c in case['checks'])
    return (f'<div class="input-summary"><b>{esc(case["name"])}</b><p>保留阈值 {state["options"]["keepThreshold"]} · '
            f'字符减少 {reduction:.1%} · 回答模型：{esc(model)}</p></div>'
            f'<details class="question-preview" open><summary>本次验证 {len(case["checks"])} 个问题</summary>'
            f'<ol>{questions}</ol></details>' if questions else
            f'<div class="empty">{esc(case["name"])} 没有验证问题。请添加 checks 或选择内置样例，不生成空题成绩。</div>')


def build_report(state, rows=None, note=''):
    if not state:
        return None
    items = []
    for i, check in enumerate(state['case']['checks']):
        present = evidence_present(state['result']['messages'], check['evidence'])
        row = rows[i] if rows is not None else None
        if row is None:
            status = '未运行回答对比'
        elif row[3] == '匹配' and row[5] != '匹配':
            status = '疑似受压缩影响'
        elif row[3] != '匹配' and row[5] != '匹配':
            status = '两边均未匹配，暂不能归因'
        elif row[3] != '匹配':
            status = '仅压缩后匹配，需复核'
        else:
            status = '已测问题未发现回答退化'
        items.append({'index': i+1, 'check': check, 'present': present, 'row': row, 'status': status})
    return {'items': items, 'answered': rows is not None, 'note': note}


def overview(report):
    if not report or not report['items']:
        return '<div class="empty">尚无可验证的问题。完成压缩并准备验证题后，这里会显示结果。</div>'
    items, n = report['items'], len(report['items'])
    evidence = sum(i['present'] for i in items)
    if not report['answered']:
        return (f'<div class="result-summary"><div><small>关键原文保留</small><strong>{evidence}/{n}</strong></div>'
                '<div><b>本地检查已完成</b><p>回答对比尚未完成，不能据此判断模型能否答对。</p></div></div>')
    original = sum(i['row'][3] == '匹配' for i in items)
    compressed = sum(i['row'][5] == '匹配' for i in items)
    regressed = sum(i['status'] == '疑似受压缩影响' for i in items)
    cards = [('原始回答匹配', f'{original}/{n}'), ('压缩后回答匹配', f'{compressed}/{n}'), ('从匹配变为未匹配', f'{regressed} 题')]
    return ('<div class="validation-metrics">' + ''.join(f'<div><small>{label}</small><strong>{value}</strong></div>' for label,value in cards) +
            f'</div><p class="validation-note">关键原文保留 {evidence}/{n}。以上为标准答案要点匹配，不代表任务成功率；请逐题复核真实回答。</p>')


def question_details(report, mode='全部问题'):
    if not report or not report['items']:
        return '<div class="empty">准备好验证题后，每道题的回答与原文证据会集中展示在这里。</div>'
    items = report['items']
    if mode == '只看需关注':
        items = [i for i in items if not i['present'] or (i['row'] and (i['row'][3] != '匹配' or i['row'][5] != '匹配'))]
    else:
        items = sorted(items, key=lambda i: (i['status'] != '疑似受压缩影响', i['present'], i['index']))
    if not items:
        return '<div class="empty">当前没有需关注项；这只覆盖已设置的验证问题。</div>'
    cards = []
    for item in items:
        c, row = item['check'], item['row']
        attention = not item['present'] or (row and (row[3] != '匹配' or row[5] != '匹配'))
        card = (f'<section class="question-card {"attention" if attention else ""}"><div class="record-label">'
                f'<b>问题 {item["index"]} · {esc(c["question"])}</b></div>'
                f'<div class="question-standard">标准答案：{esc(c["answer"])}<br><span>{esc(item["status"])}</span></div>')
        if row:
            card += '<div class="pair">'
            for name, answer, matched in [('原始上下文的回答', row[2], row[3]), ('压缩上下文的回答', row[4], row[5])]:
                card += f'<article><small>{name} · {matched}</small><p class="prose">{esc(answer)}</p></article>'
            card += '</div>'
        ev = c['evidence']
        location = '对话正文' if ev['field'] == 'text' else '工具输出 ' + ev['tool_id']
        card += (f'<details class="evidence-detail"><summary>原文证据：压缩后{"仍保留" if item["present"] else "缺失"} · 展开查看</summary>'
                 f'<p>{esc(location)}</p><blockquote>{esc(ev["quote"])}</blockquote>'
                 '<p>仅检查指定位置是否包含这段原文，不判断其他文字是否可推断答案。</p></details></section>')
        cards.append(card)
    return ''.join(cards)
