# fast-jev-compaction

Claude Code plugin that replaces the compaction summary with Jev decisions:
every tool call and result is scored in one fast request, stale ones are
dropped or truncated, everything kept stays verbatim. Also usable as an npm
library.

## What and why

Most context compaction asks an LLM to summarize old turns. A summary is
lossy: a file path, exact error, constraint, or command can disappear even when
it matters later. This library never rewrites anything. It only deletes tool
calls and tool results Jev says are no longer needed, and it asks Jev while
showing it the whole conversation. User and assistant text stays verbatim and
in order.

The repository is both an npm package (`src/`) and a Claude Code plugin
(`hooks/`, `.claude-plugin/`) that uses the package to replace Claude Code's
built-in compaction summary with the original messages.

## How it works

1. Every `tool_use` is paired with its `tool_result` by `tool_use_id`. Calls in
   the first message or in the newest `preserveRecentMessages` messages are
   pinned and never touched.
2. The **state** sent to Jev is the whole conversation so far, oldest first,
   with every tool result replaced by a short note (`ok, 4213 chars (omitted)`).
   Tool inputs are included, texts are included, nothing is summarized.
3. The state is fitted into `maxStateTokens` (25k by default) in stages, each
   applied only if the previous one was not enough: tool inputs truncated to
   1000, then 200, then 60 characters; long texts abridged to head + tail,
   oldest non-pinned messages first; old non-pinned messages collapsed to a
   `[… N chars omitted …]` note; old tool calls reduced to one line each
   (`t12 Read file_path=src/a.ts → ok 480ch`); old call-less messages left
   out; runs of old call-only messages folded into one entry. If it still
   does not fit, compaction throws. Tokens are estimated without a tokenizer (a
   word per six letters, half a token per digit, ~one per other symbol),
   calibrated to land a little above the counts Jev reports.
4. For every non-pinned call Jev gets two `noul` questions: should the **call**
   stay (knowing it was made, with its input, still matters), and should the
   **result** stay verbatim (its contents are still needed and re-running the
   tool would not do).
5. Questions are split into as many requests as needed so state plus questions
   stays under `maxRequestTokens` (30k by default, under Jev's 32k request
   limit). The same full state is resent with every request; requests run
   concurrently and their answers are merged.
6. Decisions per call, against `keepThreshold`:
   - `keepResult ≥ threshold` → keep call and result;
   - else `keepCall ≥ threshold` → keep the call, truncate the result to its
     first `truncateHeadChars` characters plus a one-line note;
   - else → remove the call together with its result.
7. The message list is rebuilt: a message that loses all its content is
   removed, untouched messages are returned as the same objects, and no result
   is ever left without its call.

Jev failures, malformed answers, a missing key, or a history that cannot be
fitted throw; the caller (or the Claude Code hook) decides what to fall back to.

## Install and usage

```sh
npm install fast-jev-compaction
export TYPESAFE_API_KEY=...
```

```ts
import { compactMessages, reductionRatio, type Message } from 'fast-jev-compaction';

const transcript: Message[] = [
  { role: 'user', text: 'Fix the failing test. Never edit src/generated.', toolUses: [] },
  {
    role: 'assistant',
    text: '',
    toolUses: [{ tool_use_id: 'toolu_1', tool: 'Read', input: { file_path: 'src/a.ts' } }],
  },
  { role: 'user', text: '', toolUses: [], toolResults: [{ tool_use_id: 'toolu_1', text: '…file…' }] },
  // …
];

const result = await compactMessages(transcript, { preserveRecentMessages: 4 });
console.log(result.messages, result.decisions, result.stats);
if (reductionRatio(result) < 0.25) {
  // not worth it: keep the original transcript, or summarize instead
}
```

`Message` is a subset of Claude Code's `SessionMessage`, so a session transcript
can be passed in as is.

To bring your own transport, implement `JevAsker` (one `ask(state, questions)`
method) and call `compact(messages, asker, options)`; `buildJevRequest` and
`parseJevResponse` give you the HTTP request body and response validation.
The building blocks (`collectToolCalls`, `fitState`, `batchCalls`,
`decideCall`, `applyDecisions`) are exported too.

`apiKey` defaults to `process.env.TYPESAFE_API_KEY`. Never commit the key or
put it in a source file.

## Options

| Option | Default | Description |
| --- | --- | --- |
| `apiKey` | `TYPESAFE_API_KEY` | TypeSafe API key (`compactMessages`/`JevClient`) |
| `model` | `jev-latest` | Jev model name |
| `baseUrl` | `https://api.typesafe.ai/v1/systemone` | System One endpoint |
| `fetch` | native `fetch` | Injectable fetch implementation for tests |
| `goal` | last 3 user prompts | Ongoing task description included in the state |
| `keepThreshold` | `0.5` | Minimum keep probability for a call or result to stay |
| `preserveRecentMessages` | `6` | Newest messages never touched (the first is always kept) |
| `maxStateTokens` | `25000` | Estimated token ceiling for the state |
| `maxRequestTokens` | `30000` | Estimated ceiling for state plus one batch of questions |
| `truncateHeadChars` | `300` | Characters of a dropped tool result retained before its note |

`result.stats` reports message and character counts before and after, the
per-reason decision counts, the state size in estimated tokens, which fitting
stage was needed, and the number of requests.

## Limitations

- Only tool calls and results are candidates; text messages are never removed
  or shortened in the output (they are only abridged in the state Jev sees).
- Token sizes are estimates from character counts, not a tokenizer.
- Calibration is at the request level; a probability is not a proof that a
  result is safe to delete. The assistant can always re-run the tool.
- The full state is repeated with every request, so a history near the state
  ceiling costs one request per handful of questions.

## Claude Code plugin

The repository root is a Claude Code function-hook plugin: `hooks/fast-jev.ts`
is a thin adapter that feeds `session.compact` transcripts through `src/` and
falls back to Claude Code's built-in summary on errors or insufficient
reduction. See [`hooks/README.md`](hooks/README.md) for configuration and the
Claude Code 2.1.274 type reference.

### Install in Claude Code

Function hooks are an early-access Claude Code feature (2.1.274+), so the
opt-in flag must be set wherever Claude Code runs, e.g. in `~/.claude/settings.json`:

```json
{ "env": { "CLAUDE_CODE_ENABLE_FUNCTION_HOOKS": "1", "TYPESAFE_API_KEY": "<your key>" } }
```

Then add this repository as a plugin marketplace and install the plugin,
either from the shell or as slash commands inside a session:

```sh
claude plugin marketplace add tamaratran/fast-jev-compaction
claude plugin install fast-jev-compaction@fast-jev-compaction
```

The install prompts for the plugin options (API key, thresholds, `truncateHeadChars`,
…); leave them at their defaults to use `TYPESAFE_API_KEY` from the environment.
Restart Claude Code or run `/reload-plugins`. From then on `/compact` (and
auto-compaction) goes through Jev: the toast reads
`fast-jev-compaction: kept N/M messages, no summary (…)` when the pruned history
replaced the built-in summary, or `fallback to built-in summary (…)` when Jev
could not remove enough (short sessions, or when it fails).

To run from a checkout without installing: `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude --plugin-dir .`
from the repository root. No publishing step is required; the marketplace is
just the repo's `.claude-plugin/marketplace.json`.

## Development

```sh
npm install
npm run typecheck        # library + hook
npm test
npm run build
npm run validate:plugin  # claude plugin validate
TYPESAFE_API_KEY="$(cat ~/.typesafe_key)" npm run demo
```

The unit tests use a fake Jev and never contact TypeSafe. The demo is the live
network check.

## 中文 Gradio 实验台（Windows / macOS / Linux）

新增入口复用 `src/` 的评分、决策和压缩算法，不改动 Claude Code 插件或原网页。
架构为 **Gradio / Python → 本地 Node 子进程（JSON 标准输入输出）→ 原 TypeScript 库**。
不额外监听 Node API 端口；每次子进程从项目根目录 `.env` 读取密钥。

### 安装、启动和停止

需要 Node.js 22+、Python 3.11+。本地已验证 Node 24、Python 3.14、Gradio 6.28。
在项目根目录执行（Windows PowerShell）：

```powershell
npm ci
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r examples/gradio/requirements.txt
# 也可以用 uv venv .venv，再用 uv pip install --python .venv/Scripts/python.exe -r examples/gradio/requirements.txt
npm run demo:gradio
```

macOS / Linux 安装依赖使用 `.venv/bin/python -m pip install -r examples/gradio/requirements.txt`，
启动同样使用 `npm run demo:gradio`。打开 **http://127.0.0.1:7860**。
终端按 **Ctrl+C** 停止。端口被占用时先停止旧进程，或设置 `GRADIO_SERVER_PORT` 后启动。
默认 `share=False`，只绑定本机，不公开分享或部署。原网页仍可使用 `npm run demo:web`（3000 端口）。

`.env`（被 Git 忽略）至少需要：

```dotenv
TYPESAFE_API_KEY=你的TypeSafe密钥
# 可选；不填写使用 jev-latest
JEV_MODEL=jev-latest
```

### 两个页面

1. **上下文压缩实验**：4 个手工教学样例（Bug 修复、资料检索、多轮需求修改、旧输出唯一线索）；
   按“准备对话 → 压缩结果 → 内容对比”组织；支持编辑/导入 JSON、保留/截断/删除标记。
   原文与结果按原始编号逐条对齐，共用一个滚动区域；删除位置保留提示，原始输出仍可展开查看。
   评分条和处理动作合并到对应工具记录的详情中，不重复展示独立图表和表格。
   运行耗时、API 次数及统计口径收在运行详情，支持直接进入关键信息验证。
   首条和最近范围内的调用/结果成对保护，受保护项显示“未评分”。
   同次评分可立即调整阈值及截断开头长度，完全复用分数，不产生新 API 调用。
   修改对话、任务目标、保护范围或 Jev 模型会使缓存失效；旧验证结论会清空。
2. **关键信息验证**：17 道题均有标准答案和可定位的证据。
   页面按“验证准备 → 验证概览 → 逐题对比”组织，显示当前案例、参数和回答模型。
   压缩完成或阈值改变后自动更新本地证据检查，并清空旧问答结论；可选择仅检查原文。
   每题集中展示标准答案、两份真实回答及可展开的证据，支持筛选需关注项。
   原始匹配但压缩未匹配标为疑似受压缩影响，两边均未匹配不直接归因；只对已测问题作结论。
   A 检查指定正文或工具输出是否还包含证据原文，不调用 API；它不是语义完整性或任务成功率。
   B 用同一个回答模型、相同提示词/温度 0/问题顺序，分别读取原始和压缩上下文，标准答案不发送给模型。
   展示真实回答，并按题目声明的答案要点/别名做透明匹配；该初筛不能处理所有否定、矛盾或同义改写，须人工复核。
### 导入格式

支持项目 `Message[]`，或 `{ "name": "案例名称", "messages": [...], "checks": [...] }`。
完整格式可查看页面中的内置样例。没有 `checks` 时可压缩，但不生成验证成绩。
仅接受完整配对的调用/结果：结果位于调用之后，ID 唯一。最多 500 条消息、500,000 个
JavaScript 字符的消息 JSON，上传文件最多 2 MB。无效字段、孤立结果、重复 ID 和找不到的证据会给出中文提示。

```json
{
  "name": "最小示例",
  "messages": [
    {"role":"user","text":"禁止修改 legacy/。","toolUses":[]},
    {"role":"assistant","text":"","toolUses":[{"tool_use_id":"c1","tool":"Read","input":{"file_path":"log.txt"}}]},
    {"role":"user","text":"","toolUses":[],"toolResults":[{"tool_use_id":"c1","text":"错误 E42 尚未解决。"}]}
  ],
  "checks": [
    {
      "question":"未解决的错误是什么？",
      "answer":"E42",
      "evidence":{"field":"toolResults","tool_id":"c1","quote":"错误 E42 尚未解决。"},
      "answer_groups":[["E42"]]
    }
  ]
}
```

正文证据使用 `field: "text"`（无需 tool_id）。工具证据限定在对应 tool_id 的输出中。
`answer_groups` 是必需答案要点的数组：每组任一别名匹配、全部组满足才记为要点匹配。
不提供时使用标准答案整段文本；比较忽略大小写和空白。

### 可选：回答模型

在 `.env` 添加支持 Chat Completions 格式的接口，再点击页面“刷新配置状态”：

```dotenv
ANSWER_BASE_URL=https://your-provider.example/v1
ANSWER_API_KEY=你的回答模型密钥
ANSWER_MODEL=模型名称
```

基础地址不包含 `/chat/completions`，需支持 `temperature: 0` 和 JSON 文本回答。
不自动重试或切换其他模型。无配置时证据核对仍可运行，模型问答显示未配置，绝不模拟答案。
请求超时（45 秒）、认证、限流、接口错误、答案 JSON 无效都有明确失败状态；
整个子进程操作超过 75 秒会终止。更改服务器配置后，已有评分可能需要重新获取。

### 数据、指标与边界

- “开始压缩”会将正文及工具输入发往 TypeSafe；原库在评分状态中省略工具输出正文。
  “真实问答”会把所选原始/压缩上下文连同工具输出发往配置的回答服务。导入前请自行移除敏感信息。
- 只读 `.env` 中的密钥，密钥不进入 Gradio 状态或日志。原始上游错误正文不会转发给页面。
  Gradio 禁止下载 `.env`、`.git` 和 `.venv`。不用内置模拟评分；自动测试的替身仅用于离线测试。
- 字符统计复用 `messageChars`：正文、工具输入 JSON、结果的 JavaScript UTF-16 长度。
  字符减少比例不是 token 或费用节省；不显示未经验证的费用。评分耗时为原库整轮真实调用耗时，
  不含 Gradio 排队/进程启动；本地重算和问答耗时分开显示。
- “困难样例”将批次、队列、错误线索只放在旧工具输出末尾。测试确认这些内容不在发送给 Jev 的状态中。
  一次随机评分可能保留或删除它，不能预先假定成功。证据是否缺失依实际结果报告。
- 手工教学样例只有 4 个、17 道题，不代表真实任务分布；不声称通用任务成功率或普遍优于其他策略。
- 当前会话评分存在服务器内存；页面刷新后需重新评分。

### 测试

```powershell
npm test
npm run typecheck:gradio
.venv\Scripts\python.exe -m pip install -r examples/gradio/requirements-dev.txt
.venv\Scripts\python.exe -X utf8 -m pytest examples/gradio -q
```

测试覆盖分数复用、缓存失效、保护范围、截断导致证据丢失、
JSON 导入、HTML 转义、缺配置、问题对照、请求失败和逐题结果展示。自动测试不调用真实收费 API。

## Browser demo (Windows, macOS, Linux)

Requires Node.js 22+ for the demo server (the library still supports Node.js 18+).
Create a `.env` file in the repository root with `TYPESAFE_API_KEY=your-key`, then:

```sh
npm ci
npm run demo:web
```

Open http://127.0.0.1:3000. The Chinese-language page compares the original
sample transcript with Jev's compacted output, shows each tool's keep scores,
and lets you adjust the threshold and number of protected recent messages.
Each click makes a real TypeSafe request and may consume API credits. The API
key stays on the server; only the bundled sample transcript is submitted.
The server binds to loopback only and reads `.env` automatically. Restart it
after changing the key. Set `PORT` before launching to use a different port.
Stop the server with Ctrl+C.

The terminal and browser demos share `examples/transcript.ts`. Run
`npm run typecheck:web` to check the demo server. Missing credentials, invalid
options, request failures and timeouts are reported without exposing the key.

## Animated demo (macOS)

`demo/JevDemo` is a small native SwiftUI app that plays a scripted, dramatized
version of the compaction flow inside a Claude Code-style terminal: the tool
calls of a canned transcript are scored, results and calls Jev lets go turn red
and collapse away, and the rest stays verbatim. It never calls the API; it
exists to be screen recorded.

```sh
demo/JevDemo/build.sh   # builds demo/JevDemo/build/JevDemo.app and launches it
```

Press space in the app to replay from the start.
