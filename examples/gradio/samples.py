"""Hand-authored teaching fixtures, not recorded real agent runs."""
import copy


def text(role, content):
    return {"role": role, "text": content, "toolUses": []}


def tool(identifier, name, args, output, error=False):
    return [
        {"role": "assistant", "text": "", "toolUses": [
            {"tool_use_id": identifier, "tool": name, "input": args}]},
        {"role": "user", "text": "", "toolUses": [], "toolResults": [
            {"tool_use_id": identifier, "text": output, "isError": error}]},
    ]


def check(question, answer, quote, *, tool_id=None, aliases=None):
    return {"question": question, "answer": answer,
            "evidence": {"field": "toolResults" if tool_id else "text", "tool_id": tool_id, "quote": quote},
            "answer_groups": aliases or [[answer]]}


SAMPLES = [
    {
        "name": "Bug 修复 · 约束与未解决错误",
        "description": "修复支付解析器，区分已经通过的测试与尚未解决的集成错误。",
        "messages": [
            text("user", "修复支付解析器。禁止修改 legacy/ 目录，保持公开 API 不变。"),
            *tool("bug-1", "Read", {"file_path": "src/parser.ts"}, "旧解析器实现\n" + "if (token) advance();\n" * 45),
            text("assistant", "我会调整尾逗号分支，并保持接口兼容。"),
            *tool("bug-2", "Bash", {"command": "npm run test:unit"}, "PASS parser.trailing-comma\n单元测试 18/18 通过。"),
            text("assistant", "parser.trailing-comma 已通过；单元测试 18/18 通过。"),
            *tool("bug-3", "Bash", {"command": "npm run test:integration"}, "FAIL payment.retry：E_RETRY_409，重复支付请求未正确去重。", True),
            text("assistant", "集成测试仍有 E_RETRY_409 错误，尚未解决。"),
            text("user", "下一步补写 CHANGELOG.md，并继续处理集成测试失败。"),
        ],
        "checks": [
            check("禁止修改哪个目录？", "legacy/", "禁止修改 legacy/ 目录"),
            check("尚未解决的错误代码是什么？", "E_RETRY_409", "集成测试仍有 E_RETRY_409 错误，尚未解决。"),
            check("已经通过的是哪个测试？", "parser.trailing-comma", "parser.trailing-comma 已通过"),
            check("下一步要更新哪个文件？", "CHANGELOG.md", "下一步补写 CHANGELOG.md"),
        ],
    },
    {
        "name": "资料检索 · 来源与限制",
        "description": "虚构的研究资料，检查重要条款、数字与引用来源是否留下。",
        "messages": [
            text("user", "比较两个虚构供应商的离线能力。只引用给定资料，不要把宣传语当测试结果。"),
            *tool("research-1", "Search", {"query": "澄海与青岚 离线功能"}, "检索结果：澄海产品介绍、青岚产品介绍。\n" + "与本任务无关的推荐链接。\n" * 35),
            text("assistant", "已找到两份产品手册，准备核对条款。"),
            *tool("research-2", "Read", {"file_path": "docs/chenghai-manual.txt"}, "澄海：离线缓存上限为 72 小时。证据出处：澄海手册第 8 页。"),
            text("assistant", "澄海离线缓存上限为 72 小时，来自澄海手册第 8 页。"),
            *tool("research-3", "Read", {"file_path": "docs/qinglan-manual.txt"}, "青岚：离线模式不支持多人协作。此条款见手册第 12 页。"),
            text("assistant", "青岚离线模式不支持多人协作。两者均尚未做真实环境测试。"),
            text("user", "请写比较表，附上出处，并说明未进行真实环境测试。"),
        ],
        "checks": [
            check("澄海的离线缓存上限是多少？", "72 小时", "离线缓存上限为 72 小时", aliases=[["72小时", "72 hours"]]),
            check("这个上限来自哪里？", "澄海手册第 8 页", "来自澄海手册第 8 页", aliases=[["澄海"], ["8"]]),
            check("青岚离线模式不支持什么？", "多人协作", "青岚离线模式不支持多人协作"),
            check("是否已经做过真实环境测试？", "未进行真实环境测试", "未进行真实环境测试", aliases=[["未", "没有", "尚未"], ["测试"]]),
        ],
    },
    {
        "name": "多轮需求修改 · 以最新要求为准",
        "description": "保留需求演变，避免把旧版限制当成最终决定。",
        "messages": [
            text("user", "做一个报表导出功能。第一版只支持 CSV，最多 1000 行。不要修改 billing/。"),
            *tool("req-1", "Read", {"file_path": "src/export.ts"}, "exportCSV(rows)\n" + "// 旧版导出逻辑\n" * 50),
            text("assistant", "已记录第一版的格式与数量限制。"),
            text("user", "需求更新：最终只支持 XLSX，最多 5000 行，取消 CSV。"),
            *tool("req-2", "Edit", {"file_path": "src/export.ts", "format": "XLSX"}, "已完成导出格式修改。"),
            text("assistant", "最终规格：XLSX，上限 5000 行，CSV 已取消。"),
            *tool("req-3", "Bash", {"command": "npm run test:export"}, "PASS export.xlsx；PASS export.limit5000"),
            text("assistant", "export.xlsx 测试已通过，下一步补上无数据时的空状态。"),
            text("user", "按最终规格补写使用说明，再检查空状态。"),
        ],
        "checks": [
            check("最终支持的格式是什么？", "XLSX", "最终规格：XLSX"),
            check("最终最多支持多少行？", "5000", "上限 5000 行"),
            check("不能修改哪个目录？", "billing/", "不要修改 billing/"),
            check("还需要补什么界面状态？", "空状态", "下一步补上无数据时的空状态"),
        ],
    },
    {
        "name": "困难样例 · 唯一线索藏在旧输出",
        "description": "关键线索只在旧工具输出末尾。Jev 只能看到输出长度和状态，无法直接读到该线索；用于观察这一盲点。",
        "messages": [
            text("user", "检查一次性迁移演练。禁止修改 archive/。保留后续恢复需要的信息，演练记录无法重新获取。"),
            *tool("hard-1", "Read", {"file_path": "logs/one-off-migration.log"},
                  "一次性演练日志（虚构教学数据）\n" + "扫描完成：普通对象检查通过。\n" * 65 +
                  "\n唯一恢复批次标识：BATCH-ORCHID-731。恢复必须先暂停队列 queue_amber。仍未解决的错误：E_LEDGER_731。"),
            text("assistant", "日志已读取，我会继续清理临时测试文件。"),
            *tool("hard-2", "Bash", {"command": "npm run test:cleanup"}, "PASS cleanup.sandbox\n" + "临时文件检查通过。\n" * 25),
            text("assistant", "cleanup.sandbox 测试已通过。"),
            *tool("hard-3", "Read", {"file_path": "docs/style.md"}, "使用两格缩进。\n" * 60),
            text("assistant", "格式要求已确认。"),
            text("user", "现在开始恢复，请依据之前演练的唯一记录，给出恢复批次、前置操作和待处理错误。"),
        ],
        "checks": [
            check("唯一恢复批次标识是什么？", "BATCH-ORCHID-731", "BATCH-ORCHID-731", tool_id="hard-1"),
            check("恢复前必须暂停哪个队列？", "queue_amber", "恢复必须先暂停队列 queue_amber", tool_id="hard-1"),
            check("仍未解决的错误代码是什么？", "E_LEDGER_731", "仍未解决的错误：E_LEDGER_731", tool_id="hard-1"),
            check("禁止修改哪个目录？", "archive/", "禁止修改 archive/"),
            check("哪个清理测试已通过？", "cleanup.sandbox", "cleanup.sandbox 测试已通过"),
        ],
    },
]


def get_sample(name):
    return copy.deepcopy(next(s for s in SAMPLES if s["name"] == name))
