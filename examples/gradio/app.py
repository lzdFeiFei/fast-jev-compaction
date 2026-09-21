"""Run from project root: .venv/Scripts/python.exe examples/gradio/app.py"""
import os
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
import json
from pathlib import Path

import gradio as gr
from presentation import comparison_html, render_result

from samples import SAMPLES, get_sample
from lab import (ROOT, LabError, bridge, parse_input, score_input, adjust, require_current,
                 verification, answer_comparison,
                 batch_evaluate, export_report, EMPTY)


CSS = """
.gradio-container {max-width:1280px!important;margin:auto!important;font-family:'Segoe UI','Microsoft YaHei',sans-serif!important}
.app-heading {align-items:center!important;padding:8px 0 14px}.app-heading h1{font-size:26px!important}.app-heading p{margin:4px 0!important}.app-heading button{max-width:150px;align-self:flex-end}
.workspace-section{padding:18px!important;border:1px solid #dce6df!important;border-radius:12px!important;background:white!important;margin:12px 0!important;gap:12px!important}
.workspace-section .workspace-section{padding:0!important;border:0!important;margin:0!important}.workspace-section button.primary{align-self:flex-end!important;min-height:44px!important}.workspace-section h3{font-size:18px!important;color:#1b4938!important;margin:0!important}.quiet-note p{font-size:12px!important;color:#576c60!important;line-height:1.6!important;margin:0!important}
.result-summary{display:flex;align-items:center;gap:32px;background:#edf7f0;color:#163c2b;padding:22px;border-radius:10px}.result-summary strong{display:block;font-size:40px;line-height:1.2;margin-top:6px}.result-summary small{color:#536d5d}.result-summary p{margin:8px 0;font-size:14px}.run-details{font-size:12px;color:#526759;margin-top:12px}.run-details summary{cursor:pointer}.run-details p{margin:8px 0}
.comparison{max-height:680px;overflow:auto;border:1px solid #dce6df;border-radius:10px;background:#f7faf8;color:#223d2e}.compare-head{position:sticky;top:0;z-index:1;display:grid;grid-template-columns:1fr 1fr;background:#edf3ef;border-bottom:1px solid #ccd9d0;padding:12px 16px;font-size:14px}
.compare-row{margin:12px;border:1px solid #dce6df;border-radius:8px;overflow:hidden;background:white}.record-label{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;font-size:12px;background:#f0f5f1}.badge{font-size:11px;border-radius:4px;padding:2px 7px;background:#e2f1e6;color:#275b3d}.deleted .badge{background:#fbe4e2;color:#943b36}.trimmed .badge{background:#fff0c9;color:#76560d}.pending .badge{background:#e9edf0;color:#55616a}
.pair{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.pair article{padding:12px;min-width:0}.pair article+article{border-left:1px solid #e0e8e2}.pair pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.6;margin:8px 0;max-height:240px;overflow:auto}.pair .prose{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7;font-size:14px;margin:0}.tool-title{font-weight:600;font-size:13px}.tool-title small{font-weight:400;color:#627469;margin-left:8px}.side-name{display:none}.muted,.removed{font-size:13px;color:#65766a;padding:8px 0}.removed{color:#8c4a43}.deleted .pair article:last-child{background:#fff7f6}.trimmed .pair article:last-child{background:#fffaf0}
.inline-score,.output{font-size:12px;margin-top:10px}.inline-score summary,.output summary{cursor:pointer;color:#286649;font-weight:500;padding:4px 0}.inline-score p{font-size:12px}.bar-row{display:flex;align-items:center;gap:8px;font-size:12px;margin-top:8px}.bar-row meter{flex:1;min-width:30px;height:12px;accent-color:#277a53}.bar-row b{font-variant-numeric:tabular-nums;font-weight:400}.empty{padding:28px;color:#64776b;background:#f5f8f6;border-radius:8px;text-align:center}
@media(max-width:700px){.result-summary{gap:16px;padding:16px}.result-summary strong{font-size:30px}.workspace-section{padding:12px!important}.pair{grid-template-columns:1fr}.pair article+article{border-left:0;border-top:1px dashed #dce6df}.side-name{display:block;font-size:11px;color:#667d6c;margin-bottom:8px}.compare-head{display:none}.comparison{max-height:620px}}
"""


INITIAL = json.dumps(SAMPLES[0], ensure_ascii=False, indent=2)
VERIFY_HEADERS = ["验证问题", "标准答案", "对应证据", "原始对话", "压缩后"]
QA_HEADERS = ["问题", "标准答案", "原始上下文回答", "要点匹配", "压缩上下文回答", "要点匹配"]
BATCH_HEADERS = ["样例", "策略", "证据保留", "字符减少", "压缩耗时 ms", "Jev 请求数", "问答要点匹配", "回答耗时 ms", "缺失 / 失败详情"]


def configuration():
    try:
        config = bridge("config")
        return (f"**Jev：{'已配置' if config['jev'] else '未配置'}**　｜　"
                f"**回答模型：{'已配置' if config['answer'] else '尚未配置'}**")
    except LabError as error:
        return str(error)


def load_sample(name):
    return json.dumps(get_sample(name), ensure_ascii=False, indent=2)


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


def invalidate(raw, recent, goal):
    try:
        case = parse_input(raw)
        preview = comparison_html(case["messages"])
        text = f"已载入「{case['name']}」，{len(case['messages'])} 条消息、{len(case['checks'])} 个验证问题。输入或评分设置已变更，需要重新评分。"
    except LabError as error:
        preview = EMPTY
        text = f"输入无效：{error}"
    return None, text, "", preview, [], "验证结果已清空；请先重新评分。", [], "问答结果已清空。"


def scoring(raw, threshold, recent, head, goal):
    try:
        state = score_input(raw, threshold, recent, head, goal)
        status = "压缩完成。可调整下方阈值，立即查看删减变化，无需再次调用 API。"
        return state, status, *render_result(state), [], "点击「检查证据保留」进行本地验证。", [], "尚未运行回答模型。"
    except LabError as error:
        # Clear previous results so a failed new run can never masquerade as success.
        return None, f"评分失败：{error}", "", EMPTY, [], "评分未完成。", [], "尚未运行回答模型。"


def local_adjust(state, raw, threshold, recent, head, goal):
    try:
        updated = adjust(state, raw, threshold, recent, head, goal)
        return updated, "已复用同一份评分，未调用 API；验证结论已清空。", *render_result(updated), [], "参数已调整，请重新检查证据。", [], "参数已调整，请重新运行问答。"
    except LabError as error:
        return invalidate(raw, recent, goal)


def verify(state, raw, threshold, recent, head, goal):
    try:
        state = adjust(state, raw, threshold, recent, head, goal)
        case = state["case"]
        if not case["checks"]:
            return [], "此导入对话没有验证题。不会把没有题目的结果记为 100%。请使用内置样例或添加 checks。"
        rows = verification(case, [case["messages"], state["result"]["messages"]])
        retained = sum(row[-1] == "保留" for row in rows)
        return rows, f"证据原文保留 {retained}/{len(rows)}。只核对指定位置的原文片段，不代表模型答对或 Agent 任务成功。缺失证据可能仍可被其他文字推断；本检查不判断推断。"
    except LabError as error:
        return [], str(error)


def qa(state, raw, threshold, recent, head, goal):
    try:
        state = adjust(state, raw, threshold, recent, head, goal)
        return answer_comparison(state)
    except LabError as error:
        return [], str(error)


def batch(threshold, recent, head, with_answers, progress=gr.Progress()):
    try:
        table, report = batch_evaluate(threshold, recent, head, with_answers, progress)
        files = export_report(report, table)
        failures = sum(r["status"] == "失败" for r in report["records"])
        status = (f"完成 {report['sample_count']} 个手工教学样例、{report['question_count']} 道验证题 × 3 种策略；"
                  f"Jev 失败 {failures} 项。失败项保留在表中，不计为零压缩或答错。小样本仅供观察，不代表通用能力。")
        return table, status, *files
    except LabError as error:
        return [], f"评测未完成：{error}", None, None


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
                    with gr.Row(equal_height=False):
                        sample = gr.Dropdown([s["name"] for s in SAMPLES], value=SAMPLES[0]["name"], label="内置样例", scale=3)
                        run = gr.Button("开始压缩", variant="primary", scale=1, min_width=160)
                    gr.Markdown("使用手工教学样例，或导入自己的对话。开始压缩会调用真实 Jev API。", elem_classes="quiet-note")
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
                with gr.Column(variant="panel", elem_classes="workspace-section"):
                    gr.Markdown("### 02　压缩结果")
                    status = gr.Markdown("样例已就绪，点击「开始压缩」。")
                    metrics = gr.HTML("")
                    threshold = gr.Slider(0, 1, value=.5, step=.05, label="保留阈值", info="越高通常删得越多。首次压缩后，调整立即生效，不会再次调用 API。")
                with gr.Column(variant="panel", elem_classes="workspace-section"):
                    with gr.Row():
                        gr.Markdown("### 03　内容对比", scale=3)
                        next_step = gr.Button("下一步：验证关键信息 →", scale=1, min_width=230)
                    gr.Markdown("同一编号对应同一条原始记录。绿色保留、黄色部分删减、红色删除；展开工具记录可查看评分与输出。", elem_classes="quiet-note")
                    comparison = gr.HTML(comparison_html(SAMPLES[0]["messages"]))
                    with gr.Accordion("如何理解评分？", open=False):
                        gr.Markdown("Jev 为每次工具调用给出两项保留分数：调用本身、输出内容。分数达到阈值时保留；受保护的记录直接保留，不进行评分。分数不是正确率，界面不会生成 Jev 未提供的理由。原库评分时只能看到工具输出的状态和长度，这一限制可在困难样例中验证。")

            with gr.Tab("② 关键信息验证", id="verification"):
                gr.Markdown("## 从‘文字还在’到‘真的答对’\n本页使用第一页**当前有效的实验结果**。修改输入或参数会清除旧结论。")
                gr.Markdown("### A. 检查证据保留 · 本地运行\n检查每题对应的原文片段是否仍在指定正文或工具输出中。**不是完整任务成功率，也不等于模型理解。**")
                check_button = gr.Button("检查证据保留 · 不调用 API", variant="primary")
                verify_status = gr.Markdown("请先在第一页运行评分。")
                verify_table = gr.Dataframe(headers=VERIFY_HEADERS, datatype="str", interactive=False, wrap=True, label="问题、答案与原始证据")
                gr.Markdown("### B. 相同回答模型对照 · 真实 API\n将原始和压缩后的**完整上下文（含工具输出）**分别发送给你配置的回答模型，回答同一组问题。标准答案与证据不会随题目发送给回答模型。")
                qa_button = gr.Button("运行原始 / 压缩问答 · 调用回答模型 API")
                qa_status = gr.Markdown("尚未运行。未配置回答模型时不会生成模拟答案或成绩。")
                qa_table = gr.Dataframe(headers=QA_HEADERS, datatype="str", interactive=False, wrap=True, label="真实回答与标准答案要点匹配")
                gr.Markdown("**判分范围：** 采用可查看的 `answer_groups` 要点匹配，同义词需在题目中列出。关键词可能出现于否定或错误叙述中，请人工复核实际回答。这里的匹配率只是问答正确性的初筛，不是通用能力评估。")
                with gr.Accordion("回答模型配置说明", open=True):
                    gr.Markdown("在项目根目录 `.env` 添加以下配置。需要支持 `/chat/completions` 的兼容接口。配置保留在服务器，不在界面填写密钥。基础地址以 `/v1` 等 API 根路径结尾，不要附加 `/chat/completions`。保存后点击顶部刷新。两种上下文使用相同模型、提示词、温度 0 和问题顺序。")
                    gr.Code('ANSWER_BASE_URL=https://your-provider.example/v1\nANSWER_API_KEY=填写你的回答模型密钥\nANSWER_MODEL=填写模型名称', language="shell", interactive=False)

            with gr.Tab("③ 批量评测"):
                gr.Markdown("## 同一批样例，三种保留策略\n**完整上下文：** 不删减，作为基线。\n\n**保留最近记录：** 只取最后 N 条，移除窗口内没有对应调用的孤立工具结果；不额外保护首条。N=0 时为空。\n\n**Jev 压缩：** 复用现有算法，首条和最近范围内的调用成对保护，其余使用真实评分。")
                with gr.Row():
                    batch_threshold = gr.Slider(0, 1, value=.5, step=.05, label="批量保留阈值")
                    batch_recent = gr.Slider(0, 30, value=2, step=1, label="最近 N 条（两种压缩策略共用）")
                    batch_head = gr.Slider(0, 2000, value=300, step=50, label="截断保留字符数")
                include_qa = gr.Checkbox(value=False, label="加入真实问答对照（需要回答模型；每样例每策略各 1 次请求）")
                gr.Markdown("按钮会为 **4 个内置教学样例、17 道验证题**运行三策略评测。Jev 为真实 API；勾选问答后，还会发送每种策略的完整上下文至回答模型（通常共 12 次回答请求）。费用不作估算。")
                batch_button = gr.Button("一键评测内置样例 · 调用真实 API", variant="primary")
                batch_status = gr.Markdown("尚未运行。小样本仅用于发现具体信息丢失案例，不作超出数据的能力结论。")
                batch_table = gr.Dataframe(headers=BATCH_HEADERS, datatype="str", interactive=False, wrap=True, label="批量结果 · 失败不会隐藏")
                with gr.Row():
                    json_download = gr.File(label="下载完整 JSON 结果", interactive=False)
                    csv_download = gr.File(label="下载 CSV 对比表", interactive=False)
                gr.Markdown("导出包含参数、样本数、证据、分数、失败详情与真实回答（如启用），不包含服务端密钥。压缩耗时与回答耗时分开；本地基线不产生 API 请求。")

        outputs = [state, status, metrics, comparison, verify_table, verify_status, qa_table, qa_status]
        inputs = [raw, threshold, recent, head, goal]
        shared = dict(concurrency_id="lab", concurrency_limit=1)
        next_step.click(lambda: gr.Tabs(selected="verification"), outputs=tabs)
        sample.change(load_sample, sample, raw, **shared)
        upload.upload(import_file, upload, raw, **shared)
        raw.change(invalidate, [raw, recent, goal], outputs, **shared)
        recent.change(invalidate, [raw, recent, goal], outputs, **shared)
        goal.change(invalidate, [raw, recent, goal], outputs, **shared)
        run.click(scoring, inputs, outputs, **shared)
        threshold.change(local_adjust, [state, *inputs], outputs, **shared)
        head.change(local_adjust, [state, *inputs], outputs, **shared)
        check_button.click(verify, [state, *inputs], [verify_table, verify_status], **shared)
        qa_button.click(qa, [state, *inputs], [qa_table, qa_status], **shared)
        batch_button.click(batch, [batch_threshold, batch_recent, batch_head, include_qa],
                           [batch_table, batch_status, json_download, csv_download], **shared)
        for component in [batch_threshold, batch_recent, batch_head, include_qa]:
            component.change(lambda: ([], "批量参数已改变，请重新评测。旧导出入口已清空。", None, None),
                             outputs=[batch_table, batch_status, json_download, csv_download], **shared)
    return app


if __name__ == "__main__":
    build_app().queue(default_concurrency_limit=1, max_size=16).launch(
        server_name="127.0.0.1", server_port=int(os.environ.get("GRADIO_SERVER_PORT", "7860")),
        share=False, inbrowser=False, show_error=False, max_file_size="2mb", run_history=False,
        blocked_paths=[str(ROOT / ".env"), str(ROOT / ".git"), str(ROOT / ".venv")],
        theme=gr.themes.Soft(primary_hue="emerald", neutral_hue="slate", font=["Segoe UI", "Microsoft YaHei", "sans-serif"]),
        css=CSS,
    )
