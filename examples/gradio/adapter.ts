import { createHash } from 'node:crypto';
import {
  applyDecisions, collectToolCalls, compact, decideCall, messageChars, resolveOptions,
  type Message, type JevAsker, type CompactOptions, type CompactResult,
} from '../../src/index.js';

export function validateMessages(value: unknown): Message[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 500)
    throw new Error('对话必须是包含 1–500 条消息的数组。');
  if (JSON.stringify(value).length > 500_000) throw new Error('对话超过 500,000 字符，请缩小后重试。');
  const calls = new Map<string, number>();
  const results = new Set<string>();
  value.forEach((m, i) => {
    const fail = (s: string): never => { throw new Error(`第 ${i + 1} 条消息：${s}`); };
    if (!m || !['user', 'assistant'].includes(m.role) || typeof m.text !== 'string' || !Array.isArray(m.toolUses))
      fail('需要 role（user/assistant）、text（字符串）、toolUses（数组）。');
    if (m.toolResults !== undefined && !Array.isArray(m.toolResults)) fail('toolResults 必须是数组。');
    for (const t of m.toolUses) {
      if (!t || typeof t.tool_use_id !== 'string' || !t.tool_use_id || typeof t.tool !== 'string' || !t.tool ||
          !t.input || typeof t.input !== 'object' || Array.isArray(t.input)) fail('工具调用需要唯一 tool_use_id、tool 和 input 对象。');
      if (t.text !== undefined && typeof t.text !== 'string') fail('工具调用 text 必须是字符串。');
      if (t.isError !== undefined && typeof t.isError !== 'boolean') fail('isError 必须是布尔值。');
      if (calls.has(t.tool_use_id)) fail(`重复的工具调用 ID：${t.tool_use_id}`);
      calls.set(t.tool_use_id, i);
    }
    for (const r of m.toolResults ?? []) {
      if (!r || typeof r.tool_use_id !== 'string' || typeof r.text !== 'string') fail('工具结果需要 tool_use_id 和 text。');
      if (r.isError !== undefined && typeof r.isError !== 'boolean') fail('isError 必须是布尔值。');
      if (!calls.has(r.tool_use_id) || calls.get(r.tool_use_id)! >= i) fail('工具结果必须对应前面的工具调用。');
      if (results.has(r.tool_use_id)) fail('工具结果 ID 重复。');
      results.add(r.tool_use_id);
    }
  });
  for (const id of calls.keys()) if (!results.has(id)) throw new Error(`工具调用 ${id} 缺少配对结果；请导入完整的调用与结果。`);
  // Copy only the public transcript fields; discard arbitrary imported metadata.
  return value.map(m => ({
    role: m.role, text: m.text,
    toolUses: m.toolUses.map((t: any) => ({ tool_use_id: t.tool_use_id, tool: t.tool, input: t.input,
      ...(t.text === undefined ? {} : { text: t.text }), ...(t.isError === undefined ? {} : { isError: t.isError }) })),
    ...(m.toolResults === undefined ? {} : { toolResults: m.toolResults.map((r: any) => ({
      tool_use_id: r.tool_use_id, text: r.text, ...(r.isError === undefined ? {} : { isError: r.isError }),
    })) }),
  }));
}

export function optionsFrom(value: any = {}): CompactOptions {
  const ranges = { keepThreshold: [0, 1], preserveRecentMessages: [0, 500], truncateHeadChars: [0, 5000] };
  for (const [key, range] of Object.entries(ranges)) {
    const v = value[key];
    if (v !== undefined && (typeof v !== 'number' || !Number.isFinite(v) || v < range[0] || v > range[1] ||
        (key !== 'keepThreshold' && !Number.isInteger(v)))) throw new Error(`参数 ${key} 无效。`);
  }
  if (value.goal !== undefined && (typeof value.goal !== 'string' || value.goal.length > 2000)) throw new Error('任务目标最多 2000 字符。');
  return { keepThreshold: value.keepThreshold ?? .5, preserveRecentMessages: value.preserveRecentMessages ?? 2,
    truncateHeadChars: value.truncateHeadChars ?? 300, goal: value.goal ?? '' };
}

export function fingerprint(messages: Message[], options: CompactOptions, model: string): string {
  return createHash('sha256').update(JSON.stringify({ messages, recent: options.preserveRecentMessages, goal: options.goal, model })).digest('hex');
}
export interface Scored {
  fingerprint: string;
  result: CompactResult;
  scoredAt: string;
  model: string;
}
export async function score(messages: Message[], options: CompactOptions, model: string, asker: JevAsker): Promise<Scored> {
  return { fingerprint: fingerprint(messages, options, model), result: await compact(messages, asker, options),
    scoredAt: new Date().toISOString(), model };
}
export function reapply(messages: Message[], options: CompactOptions, model: string, cache: Scored) {
  if (!cache || cache.fingerprint !== fingerprint(messages, options, model)) throw new Error('输入或评分设置已改变，请重新评分。');
  const started = performance.now();
  const resolved = resolveOptions(options);
  const calls = collectToolCalls(messages, resolved.preserveRecentMessages);
  const scores = new Map(cache.result.decisions.map(d => [d.id, d]));
  const decisions = calls.map(c => {
    const answer = scores.get(c.id);
    if (!answer) throw new Error('评分缓存不完整，请重新评分。');
    return decideCall(c, answer, resolved);
  });
  const kept = applyDecisions(messages, decisions, calls, resolved.truncateHeadChars);
  const sourceIndices = messages.flatMap((message, index) =>
    applyDecisions([message], decisions, calls, resolved.truncateHeadChars).length ? [index] : []);
  return { messages: kept, sourceIndices, decisions, calls,
    stats: { ...cache.result.stats, messagesAfter: kept.length,
      charsAfter: kept.reduce((n, m) => n + messageChars(m), 0),
      kept: decisions.filter(d => d.reason === 'kept').length,
      resultsDropped: decisions.filter(d => d.reason === 'result_dropped').length,
      callsDropped: decisions.filter(d => d.reason === 'call_dropped').length,
      localMs: performance.now() - started, newRequests: 0 },
    scoredAt: cache.scoredAt, model };
}
