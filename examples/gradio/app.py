"""Run from project root: .venv/Scripts/python.exe examples/gradio/app.py"""
import os
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
import json
from pathlib import Path

import gradio as gr

from samples import SAMPLES, get_sample
from lab import (ROOT, LabError, bridge, parse_input, score_input, adjust, require_current,
                 render, transcript_html, verification, answer_comparison,
                 batch_evaluate, export_report, EMPTY)


CSS = """
.gradio-container {max-width:1440px!important;margin:auto!important;font-family:'Segoe UI','Microsoft YaHei',sans-serif!important}
.hero {background:linear-gradient(115deg,#142c2c,#245746);border-radius:18px;padding:32px;color:#f5fff9;margin:8px 0 18px}
.hero small {color:#bdecc6;letter-spacing:3px;font-size:12px}.hero h1 {font-size:32px!important;color:white!important;margin:10px 0!important;font-weight:650}
.hero p {color:#d7e9df;line-height:1.8;margin:0}.metrics {display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:8px 0}
.metrics>div {background:#edf6f0;border:1px solid #cde0d4;padding:18px;border-radius:12px;color:#153a2c}.metrics small{display:block;color:#466657;font-size:12px}.metrics strong{display:block;font-size:24px;margin-top:6px}
.transcript {height:520px;overflow:auto;background:#f7faf8;padding:12px;border:1px solid #dbe5de;border-radius:12px;color:#19382b}
.message {background:white;border:1px solid #e0e8e2;padding:14px;margin-bottom:10px;border-radius:9px}.message small{color:#59796a;font-size:11px}.prose{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0;line-height:1.8;font-size:14px}
.tool{margin-top:10px;border-left:4px solid #2c8061;padding:10px;background:#eef7f1;border-radius:5px;font-size:13px}.drop_call{border-color:#c44c4c;background:#fff0ef;color:#833131}.drop_result{border-color:#bf8a23;background:#fff8e5;color:#6c501e}
.tool pre {white-space:pre-wrap;overflow-wrap:anywhere;max-height:300px;overflow:auto;font-size:12px;color:inherit}.tool summary{cursor:pointer;font-weight:600}.empty{padding:55px 24px;text-align:center;border:1px dashed #a9bfb0;border-radius:12px;color:#5e7668;background:#f4f8f5;min-height:170px}
.score-chart{color:#244637;background:#f6faf7;padding:20px;border-radius:12px}.score-row{padding:12px 0;border-bottom:1px solid #dde8df}.bar-row{display:flex;align-items:center;gap:12px;font-size:12px;margin-top:8px}.track{flex:1;background:#deebe2;height:9px;border-radius:10px}.track i{display:block;background:#348161;height:9px;border-radius:10px}.score-row b{font-size:13px}
@media(max-width:700px){.metrics{grid-template-columns:repeat(2,1fr)}.hero{padding:22px}.hero h1{font-size:25px!important}.metrics strong{font-size:19px}}
"""

INITIAL = json.dumps(SAMPLES[0], ensure_ascii=False, indent=2)
SCORE_HEADERS = ["编号", "工具", "调用保留分数", "结果保留分数", "处理方式", "原始调用 ID"]
VERIFY_HEADERS = ["验证问题", "标准答案", "对应证据", "原始对话", "压缩后"]
QA_HEADERS = ["问题", "标准答案", "原始上下文回答", "要点匹配", "压缩上下文回答", "要点匹配"]
BATCH_HEADERS = ["样例", "策略", "证据保留", "字符减少", "压缩耗时 ms", "Jev 请求数", "问答要点匹配", "回答耗时 ms", "缺失 / 失败详情"]


def configuration():
    try:
        config = bridge("config")
        return (f"**Jev：{'已配置' if config['jev'] else '未配置'}**　｜　"
                f"**回答模型：{'已配置' if config['answer'] else '尚未配置'}**　｜　仅本机访问 · 所有评分均为真实 API")
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
        preview = transcript_html(case["messages"])
        text = f"已载入「{case['name']}」，{len(case['messages'])} 条消息、{len(case['checks'])} 个验证问题。输入或评分设置已变更，需要重新评分。"
    except LabError as error:
        preview = EMPTY
        text = f"输入无效：{error}"
    return None, text, "", preview, EMPTY, "", [], [], "验证结果已清空；请先重新评分。", [], "问答结果已清空。"


def scoring(raw, threshold, recent, head, goal):
    try:
        state = score_input(raw, threshold, recent, head, goal)
        status = "真实评分完成。绿色＝保留，黄色＝截断策略，红色＝删除。左侧始终可展开被删除的原始输出。"
        return state, status, *render(state), [], "点击「检查证据保留」进行本地验证。", [], "尚未运行回答模型。"
    except LabError as error:
        # Clear previous results so a failed new run can never masquerade as success.
        return None, f"评分失败：{error}", "", EMPTY, EMPTY, "", [], [], "评分未完成。", [], "尚未运行回答模型。"


def local_adjust(state, raw, threshold, recent, head, goal):
    try:
        updated = adjust(state, raw, threshold, recent, head, goal)
        return updated, "已复用同一份真实评分，本次调整未调用 API。旧验证结论已清空，请重新验证。", *render(updated), [], "参数已调整，请重新检查证据。", [], "参数已调整，请重新运行问答。"
    except LabError as error:
        return None, str(error), "", EMPTY, EMPTY, "", [], [], "请先评分。", [], "请先评分。"


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
        gr.HTML('<div class="hero"><small>JEV CONTEXT LAB</small><h1>上下文变短，重要信息还在吗？</h1><p>先观察删减，再检查证据，最后比较回答。用可核对的实验，理解 Agent 的上下文压缩。</p></div>')
        config_status = gr.Markdown(configuration())
        refresh = gr.Button("刷新配置状态", size="sm")
        refresh.click(configuration, outputs=config_status)
        state = gr.State(None)
        with gr.Tabs():
            with gr.Tab("① 上下文压缩实验"):
                gr.Markdown("**操作顺序：** 选择样例或导入 → 真实 Jev 评分 → 调整阈值观察变化 → 到第二页验证信息。\n\n内置对话是手工编写的教学数据，**评分是真实 API 结果**，没有预置模拟分数。")
                sample = gr.Dropdown([s["name"] for s in SAMPLES], value=SAMPLES[0]["name"], label="选择教学场景")
                with gr.Accordion("查看 / 编辑对话 JSON，或导入自己的记录", open=False):
                    raw = gr.Code(value=INITIAL, language="json", label="对话 JSON（编辑会使评分失效）", lines=12)
                    upload = gr.File(label="导入 UTF-8 JSON（最大 2 MB）", file_types=[".json"], type="filepath")
                    gr.Markdown('可导入消息数组，或 `{ "name": "我的实验", "messages": [...], "checks": [...] }`。每条消息需要 `role`、`text`、`toolUses`；工具调用和结果通过唯一 `tool_use_id` 配对。上方内置样例就是完整格式示例。没有 `checks` 时只做压缩，不虚构验证成绩。')
                    with gr.Accordion("最小导入格式与验证题说明", open=False):
                        gr.Code(value=json.dumps({"name": "格式示例", "messages": [
                            {"role": "user", "text": "禁止修改 legacy/。", "toolUses": []},
                            {"role": "assistant", "text": "", "toolUses": [{"tool_use_id": "c1", "tool": "Read", "input": {"file_path": "log.txt"}}]},
                            {"role": "user", "text": "", "toolUses": [], "toolResults": [{"tool_use_id": "c1", "text": "错误 E42 尚未解决。"}]}
                        ], "checks": [{"question": "未解决的错误？", "answer": "E42", "evidence": {"field": "toolResults", "tool_id": "c1", "quote": "错误 E42 尚未解决。"}, "answer_groups": [["E42"]]}]}, ensure_ascii=False, indent=2), language="json", interactive=False, lines=12)
                        gr.Markdown("证据检查使用原文精确包含。正文证据使用 `field: text`，工具结果使用 `field: toolResults` 和 `tool_id`。`answer_groups` 每组为一个必需答案要点，组内任一别名匹配即可；它仅用于问答的透明关键词核对。")
                with gr.Row():
                    threshold = gr.Slider(0, 1, value=.5, step=.05, label="保留阈值 · 本地即时重算", info="越高通常删除越多；调用或结果分数达到阈值时才保留。不是正确率。")
                    recent = gr.Slider(0, 30, value=2, step=1, label="保护最近 N 条消息 · 改动需重新评分", info="首条始终保护。工具调用或结果任一处于保护范围，整对都会保留。")
                with gr.Accordion("更多控制", open=False):
                    head = gr.Slider(0, 2000, value=300, step=50, label="被截断结果保留的开头字符数 · 本地重算", info="原库对短输出可能保留原文，决策表会如实说明。")
                    goal = gr.Textbox(label="当前任务目标 · 改动需重新评分", placeholder="留空时使用最后三条用户提示", max_lines=3)
                gr.Markdown("**数据发送提示：** 点击下面按钮会把当前对话的正文和工具输入发送至 TypeSafe，输出正文按原库规则省略。请先移除私人或敏感信息。调阈值和截断长度不会发送数据。")
                run = gr.Button("真实 Jev 评分 · 调用 API", variant="primary")
                status = gr.Markdown("样例已就绪。尚未评分；点击按钮开始。")
                metrics = gr.HTML("")
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### 原始对话 · 查看删减标记")
                        before = gr.HTML(transcript_html(SAMPLES[0]["messages"]))
                    with gr.Column():
                        gr.Markdown("### 压缩后的实际上下文")
                        after = gr.HTML(EMPTY)
                gr.Markdown("绿色＝保留，黄色＝截断策略，红色＝删除。左侧可展开完整原文；右侧展示实际留下的内容。字符按原库 JavaScript UTF-16 长度统计正文、工具输入 JSON 和结果，不等同于 token 或费用。")
                chart = gr.HTML("")
                scores = gr.Dataframe(headers=SCORE_HEADERS, datatype="str", interactive=False, label="逐调用评分与决策", wrap=True)
                gr.Markdown("不生成 Jev 未提供的理由。原库评分状态中的工具输出只有状态与长度，困难样例专门检验这一信息缺口。")

            with gr.Tab("② 关键信息验证"):
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

        outputs = [state, status, metrics, before, after, chart, scores, verify_table, verify_status, qa_table, qa_status]
        inputs = [raw, threshold, recent, head, goal]
        shared = dict(concurrency_id="lab", concurrency_limit=1)
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
