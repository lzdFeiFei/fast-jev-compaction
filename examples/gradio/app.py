"""Run from project root: .venv/Scripts/python.exe examples/gradio/app.py"""
import os
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
import json
import re
from pathlib import Path

import gradio as gr
import validation_view as vv
from presentation import comparison_html, render_result, message_body, esc

from samples import SAMPLES, get_sample
from lab import (ROOT, LabError, bridge, parse_input, score_input, adjust, require_current,
                 verification, answer_comparison,
                 EMPTY)


CSS = """
.gradio-container {max-width:1280px!important;margin:auto!important;font-family:'Segoe UI','Microsoft YaHei',sans-serif!important}
.app-heading {align-items:center!important;padding:8px 0 14px}.app-heading h1{font-size:26px!important}.app-heading p{margin:4px 0!important}.app-heading button{max-width:150px;align-self:flex-end}
.workspace-section{padding:18px!important;border:1px solid #dce6df!important;border-radius:12px!important;background:white!important;margin:12px 0!important;gap:12px!important}
.workspace-section .workspace-section{padding:0!important;border:0!important;margin:0!important}.workspace-section button.primary{align-self:flex-end!important;min-height:44px!important}.workspace-section h3{font-size:18px!important;color:#1b4938!important;margin:0!important}.quiet-note p{font-size:12px!important;color:#576c60!important;line-height:1.6!important;margin:0!important}
.input-summary{color:#254332;padding:4px 0 10px}.input-summary p{font-size:13px;margin:6px 0;line-height:1.6}.input-summary small{color:#617368;font-size:12px}.input-preview{max-height:300px;overflow:auto;background:#f7faf8;border:1px solid #dce6df;border-radius:8px;padding:12px;color:#243e30}.input-preview article{background:white;border:1px solid #e3eae5;border-radius:6px;padding:12px;margin-bottom:8px}.input-preview article>small{display:block;font-size:11px;color:#65786b;margin-bottom:6px}.input-preview .prose{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7;font-size:13px;margin:0}.input-preview pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;max-height:200px;overflow:auto}.input-preview:focus-visible{outline:2px solid #277a53;outline-offset:2px}.result-summary{display:flex;align-items:center;gap:32px;background:#edf7f0;color:#163c2b;padding:22px;border-radius:10px}.result-summary strong{display:block;font-size:40px;line-height:1.2;margin-top:6px}.result-summary small{color:#536d5d}.result-summary p{margin:8px 0;font-size:14px}.run-details{font-size:12px;color:#526759;margin-top:12px}.run-details summary{cursor:pointer}.run-details p{margin:8px 0}
.comparison{max-height:680px;overflow:auto;border:1px solid #dce6df;border-radius:10px;background:#f7faf8;color:#223d2e}.compare-head{position:sticky;top:0;z-index:1;display:grid;grid-template-columns:1fr 1fr;background:#edf3ef;border-bottom:1px solid #ccd9d0;padding:12px 16px;font-size:14px}
.compare-row{margin:12px;border:1px solid #dce6df;border-radius:8px;overflow:hidden;background:white}.record-label{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;font-size:12px;background:#f0f5f1}.badge{font-size:11px;border-radius:4px;padding:2px 7px;background:#e2f1e6;color:#275b3d}.deleted .badge{background:#fbe4e2;color:#943b36}.trimmed .badge{background:#fff0c9;color:#76560d}.pending .badge{background:#e9edf0;color:#55616a}
.pair{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.pair article{padding:12px;min-width:0}.pair article+article{border-left:1px solid #e0e8e2}.pair pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.6;margin:8px 0;max-height:240px;overflow:auto}.pair .prose{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7;font-size:14px;margin:0}.tool-title{font-weight:600;font-size:13px}.tool-title small{font-weight:400;color:#627469;margin-left:8px}.side-name{display:none}.muted,.removed{font-size:13px;color:#65766a;padding:8px 0}.removed{color:#8c4a43}.deleted .pair article:last-child{background:#fff7f6}.trimmed .pair article:last-child{background:#fffaf0}
.inline-score,.output{font-size:12px;margin-top:10px}.inline-score summary,.output summary{cursor:pointer;color:#286649;font-weight:500;padding:4px 0}.inline-score p{font-size:12px}.bar-row{display:flex;align-items:center;gap:8px;font-size:12px;margin-top:8px}.bar-row meter{flex:1;min-width:30px;height:12px;accent-color:#277a53}.bar-row b{font-variant-numeric:tabular-nums;font-weight:400}.empty{padding:28px;color:#64776b;background:#f5f8f6;border-radius:8px;text-align:center}
.question-preview{font-size:14px;color:#294737}.question-preview summary{cursor:pointer}.question-preview li{margin:6px 0}.validation-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.validation-metrics>div{background:#edf7f0;border-radius:8px;padding:18px;color:#245137}.validation-metrics strong{display:block;font-size:30px;margin-top:6px}.validation-note{font-size:13px;color:#5a6c60}.question-card{border:1px solid #dce6df;border-radius:10px;overflow:hidden;margin-bottom:14px;color:#284433}.question-card.attention{border-color:#d5a35a}.question-standard{padding:12px;font-size:14px;line-height:1.8;overflow-wrap:anywhere}.question-standard span{font-size:12px;color:#647466}.evidence-detail{padding:12px;font-size:13px;background:#f7faf8}.evidence-detail summary{cursor:pointer}.evidence-detail blockquote{white-space:pre-wrap;overflow-wrap:anywhere;border-left:3px solid #a3bba9;padding-left:12px}.question-card .pair article small{display:block;margin-bottom:8px}.question-card .record-label b{overflow-wrap:anywhere}@media(max-width:700px){.validation-metrics{grid-template-columns:1fr}.result-summary{gap:16px;padding:16px}.result-summary strong{font-size:30px}.workspace-section{padding:12px!important}.pair{grid-template-columns:1fr}.pair article+article{border-left:0;border-top:1px dashed #dce6df}.side-name{display:block;font-size:11px;color:#667d6c;margin-bottom:8px}.compare-head{display:none}.comparison{max-height:620px}}
"""


INITIAL = json.dumps(SAMPLES[0], ensure_ascii=False, indent=2)


def configuration():
    try:
        config = bridge("config")
        return (f"**Jev：{'已配置' if config['jev'] else '未配置'}**　｜　"
                f"**回答模型：{'已配置' if config['answer'] else '尚未配置'}**")
    except LabError as error:
        return str(error)


def load_sample(name):
    return json.dumps(get_sample(name), ensure_ascii=False, indent=2)


def input_preview(raw):
    try:
        case = parse_input(raw)
        matched = next((s for s in SAMPLES if s['messages'] == case['messages']), None)
        description = matched['description'] if matched else '当前导入或编辑的对话；以下内容将用于本次压缩。'
        count = sum(len(m['toolUses']) for m in case['messages'])
        heading = (f'<div class="input-summary"><p>{esc(description)}</p>'
                   f'<small>{len(case["messages"])} 条消息 · {count} 次工具调用 · {len(case["checks"])} 个验证问题</small></div>')
        rows = []
        for i, m in enumerate(case['messages']):
            role = '工具输出' if m.get('toolResults') else '用户' if m['role'] == 'user' else '助手'
            rows.append(f'<article><small>#{i+1:02d} · {role}</small>{message_body(m)}</article>')
        return heading + '<div class="input-preview" role="region" aria-label="待压缩对话预览" tabindex="0">' + ''.join(rows) + '</div>'
    except LabError as error:
        return f'<div class="empty">无法预览：{esc(error)}</div>'


def import_file(path):
    if not path:
        raise gr.Error("请先选择 JSON 文件。")
    try:
        if Path(path).stat().st_size > 2_000_000:
            raise LabError("文件超过 2 MB，请缩小后导入。")
        raw = Path(path).read_text(encoding="utf-8-sig")
        parse_input(raw)
        return raw
    except (UnicodeError, OSError):
        raise gr.Error("无法读取文件，请使用 UTF-8 编码的 JSON 文件。") from None
    except LabError as error:
        raise gr.Error(str(error)) from None


def validation_preparation(state):
    try:
        return vv.preparation(state, bridge("config"))
    except LabError as error:
        return f'<div class="empty">{esc(error)}</div>'


def reset_validation(state, message):
    report = vv.build_report(state)
    return report, vv.overview(report), vv.question_details(report), message, validation_preparation(state), "全部问题"


def invalidate(raw, recent, goal):
    try:
        case = parse_input(raw)
        preview = comparison_html(case["messages"])
        text = f"已载入「{case['name']}」，{len(case['messages'])} 条消息、{len(case['checks'])} 个验证问题。输入或评分设置已变更，需要重新评分。"
    except LabError as error:
        preview = EMPTY
        text = f"输入无效：{error}"
    return None, text, "", preview, *reset_validation(None, "输入已变更，请先重新压缩。")


def scoring(raw, threshold, recent, head, goal):
    try:
        state = score_input(raw, threshold, recent, head, goal)
        status = "压缩完成。可调整下方阈值，立即查看删减变化，无需再次调用 API。"
        return state, status, *render_result(state), *reset_validation(state, "原文已自动检查；可开始回答对比。")
    except LabError as error:
        # Clear previous results so a failed new run can never masquerade as success.
        return None, f"评分失败：{error}", "", EMPTY, *reset_validation(None, "压缩未完成。")


def local_adjust(state, raw, threshold, recent, head, goal):
    try:
        updated = adjust(state, raw, threshold, recent, head, goal)
        return updated, "已复用同一份评分，未调用 API；验证结论已清空。", *render_result(updated), *reset_validation(updated, "参数已调整，原文检查已更新；请重新运行回答对比。")
    except LabError as error:
        return invalidate(raw, recent, goal)


def validate_answers(state, raw, threshold, recent, head, goal, local_only, mode):
    report = None
    try:
        state = adjust(state, raw, threshold, recent, head, goal)
        report = vv.build_report(state)
        if not state["case"]["checks"]:
            raise LabError("当前对话没有验证题，请添加 checks 或选择内置样例。")
        if local_only:
            note = "本地原文检查已完成，未调用回答模型。"
        else:
            rows, note = answer_comparison(state)
            report = vv.build_report(state, rows, note)
            timing = re.search(r'耗时 [\d.]+ 毫秒', note)
            note = note.split('标准答案要点匹配')[0] + (timing.group(0) if timing else '')
        return report, vv.overview(report), vv.question_details(report, mode), note
    except LabError as error:
        return report, vv.overview(report), vv.question_details(report, mode), f"回答对比未完成：{error}"


def build_app():
    with gr.Blocks(title="Jev 中文实验台", analytics_enabled=False, delete_cache=(3600, 86400)) as app:
        with gr.Row(elem_classes="app-heading"):
            gr.Markdown("# Jev 上下文实验台\n压缩对话，再验证重要信息是否还在。", scale=3)
            with gr.Column(scale=2, min_width=260):
                config_status = gr.Markdown(configuration())
                refresh = gr.Button("刷新连接状态", size="sm")
        refresh.click(configuration, outputs=config_status)
        state = gr.State(None)
        with gr.Tabs() as tabs:
            with gr.Tab("① 上下文压缩实验", id="compression"):
                with gr.Column(variant="panel", elem_classes="workspace-section"):
                    gr.Markdown("### 01　准备对话")
                    sample = gr.Dropdown([s["name"] for s in SAMPLES], value=SAMPLES[0]["name"], label="内置样例")
                    preview = gr.HTML(input_preview(INITIAL))
                    with gr.Accordion("导入或编辑对话", open=False):
                        upload = gr.File(label="导入 UTF-8 JSON（最大 2 MB）", file_types=[".json"], type="filepath")
                        raw = gr.Code(value=INITIAL, language="json", label="对话 JSON", lines=12)
                        gr.Markdown('支持消息数组，或 `{ "name": "我的实验", "messages": [...], "checks": [...] }`。当前样例就是完整格式示例。编辑后需要重新压缩。')
                        with gr.Accordion("格式说明", open=False):
                            gr.Markdown("每条消息需要 `role`（user/assistant）、`text` 和 `toolUses`。工具调用包含 `tool_use_id`、`tool`、`input`；后续 `toolResults` 通过同一 ID 配对并提供 `text`。没有 `checks` 时只压缩，不生成验证成绩。验证题需要 `question`、`answer`、`evidence`；正文证据使用 `field: text` 和 `quote`，工具结果使用 `field: toolResults`、`tool_id` 和 `quote`。可选 `answer_groups` 用于答案要点匹配。")
                    with gr.Accordion("高级设置", open=False):
                        recent = gr.Slider(0, 30, value=2, step=1, label="保护最近消息数", info="首条始终保护；工具调用与结果成对保留。修改后需重新压缩。")
                        head = gr.Slider(0, 2000, value=300, step=50, label="截断时保留开头字符数", info="修改后复用评分。短输出可能保持原文。")
                        goal = gr.Textbox(label="当前任务目标", placeholder="留空时使用最后三条用户提示", info="修改后需重新压缩。", max_lines=3)
                    gr.Markdown("发送至 TypeSafe：对话正文和工具输入，输出正文按原库规则省略。导入前请移除敏感信息。", elem_classes="quiet-note")
                    run = gr.Button("开始压缩", variant="primary")
                with gr.Column(variant="panel", elem_classes="workspace-section"):
                    gr.Markdown("### 02　压缩结果")
                    status = gr.Markdown("样例已就绪，点击「开始压缩」。")
                    metrics = gr.HTML("")
                    threshold = gr.Slider(0, 1, value=.5, step=.05, label="保留阈值", info="越高通常删得越多。首次压缩后，调整立即生效，不会再次调用 API。")
                with gr.Column(variant="panel", elem_classes="workspace-section"):
                    gr.Markdown("### 03　内容对比")
                    gr.Markdown("同一编号对应同一条原始记录。绿色保留、黄色部分删减、红色删除；展开工具记录可查看评分与输出。", elem_classes="quiet-note")
                    comparison = gr.HTML(comparison_html(SAMPLES[0]["messages"]))
                    with gr.Accordion("如何理解评分？", open=False):
                        gr.Markdown("Jev 为每次工具调用给出两项保留分数：调用本身、输出内容。分数达到阈值时保留；受保护的记录直接保留，不进行评分。分数不是正确率，界面不会生成 Jev 未提供的理由。原库评分时只能看到工具输出的状态和长度，这一限制可在困难样例中验证。")
                    next_step = gr.Button("下一步：验证关键信息 →")

            with gr.Tab("② 关键信息验证", id="verification") as verification_tab:
                validation_report = gr.State(None)
                with gr.Column(variant="panel", elem_classes="workspace-section"):
                    gr.Markdown("### 01　验证准备")
                    preparation = gr.HTML(validation_preparation(None))
                    local_only = gr.Checkbox(value=False, label="仅检查关键原文，不调用回答模型")
                    with gr.Accordion("回答模型配置", open=False):
                        gr.Markdown("未配置时可先仅检查原文。真实回答对比需要在项目根目录 `.env` 设置以下项目；保存后点击顶部刷新连接状态，再进入本页。")
                        gr.Code('ANSWER_BASE_URL=https://your-provider.example/v1\nANSWER_API_KEY=填写你的回答模型密钥\nANSWER_MODEL=填写模型名称', language="shell", interactive=False)
                    gr.Markdown("开始回答对比会将原始和压缩后的完整对话（含工具输出）分别发送至配置的回答模型。使用相同模型和问题，标准答案不发送；通常产生 2 次真实 API 请求。", elem_classes="quiet-note")
                    validate_button = gr.Button("开始回答对比", variant="primary")
                with gr.Column(variant="panel", elem_classes="workspace-section"):
                    gr.Markdown("### 02　验证概览")
                    validation_status = gr.Markdown("请先完成压缩，关键原文会自动检查。")
                    validation_summary = gr.HTML(vv.overview(None))
                with gr.Column(variant="panel", elem_classes="workspace-section"):
                    gr.Markdown("### 03　逐题对比")
                    question_filter = gr.Radio(["全部问题", "只看需关注"], value="全部问题", label="显示范围", info="优先显示原始匹配而压缩后未匹配的题目；未匹配或证据缺失的题目均可筛选。")
                    validation_details = gr.HTML(vv.question_details(None))
                    with gr.Accordion("验证方法与结果边界", open=False):
                        gr.Markdown("**原文检查**：在指定正文或工具输出中精确查找证据，自动本地运行。\n\n**回答对比**：同一模型分别读取两份上下文回答同一组问题，按标准答案要点匹配（忽略空白及大小写，使用题目声明的别名）。匹配无法排除否定、矛盾或同义改写造成的误判，请人工复核。\n\n原始匹配而压缩未匹配：疑似受压缩影响；两边均未匹配：暂不能归因；两边均匹配：仅表示已测问题未发现回答退化，不等于完全没有信息损失或任务成功。")

        outputs = [state, status, metrics, comparison, validation_report, validation_summary, validation_details, validation_status, preparation, question_filter]
        inputs = [raw, threshold, recent, head, goal]
        shared = dict(concurrency_id="lab", concurrency_limit=1)
        next_step.click(lambda: gr.Tabs(selected="verification"), outputs=tabs)
        sample.change(load_sample, sample, raw, **shared)
        upload.upload(import_file, upload, raw, **shared)
        raw.change(invalidate, [raw, recent, goal], outputs, **shared)
        raw.change(input_preview, raw, preview, **shared)
        recent.change(invalidate, [raw, recent, goal], outputs, **shared)
        goal.change(invalidate, [raw, recent, goal], outputs, **shared)
        run.click(scoring, inputs, outputs, **shared)
        threshold.change(local_adjust, [state, *inputs], outputs, **shared)
        head.change(local_adjust, [state, *inputs], outputs, **shared)
        verification_tab.select(validation_preparation, state, preparation, **shared)
        local_only.change(lambda value: gr.Button(value="检查关键原文" if value else "开始回答对比"), local_only, validate_button)
        validate_button.click(validate_answers, [state, *inputs, local_only, question_filter],
                              [validation_report, validation_summary, validation_details, validation_status], **shared)
        question_filter.change(vv.question_details, [validation_report, question_filter], validation_details, **shared)
    return app


if __name__ == "__main__":
    build_app().queue(default_concurrency_limit=1, max_size=16).launch(
        server_name="127.0.0.1", server_port=int(os.environ.get("GRADIO_SERVER_PORT", "7860")),
        share=False, inbrowser=False, show_error=False, max_file_size="2mb", run_history=False,
        blocked_paths=[str(ROOT / ".env"), str(ROOT / ".git"), str(ROOT / ".venv")],
        theme=gr.themes.Soft(primary_hue="emerald", neutral_hue="slate", font=["Segoe UI", "Microsoft YaHei", "sans-serif"]),
        css=CSS,
    )
