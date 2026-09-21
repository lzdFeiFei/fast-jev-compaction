import { describe, it, expect, vi } from 'vitest';
import { validateMessages, optionsFrom, score, reapply, recentOnly } from '../examples/gradio/adapter.js';
import { fitState, collectToolCalls, resolveOptions, type Message, type JevAsker } from '../src/index.js';

const messages: Message[] = [
  { role: 'user', text: 'Do not modify legacy/', toolUses: [] },
  { role: 'assistant', text: '', toolUses: [{ tool_use_id: 'one', tool: 'Read', input: { file_path: 'log.txt' } }] },
  { role: 'user', text: '', toolUses: [], toolResults: [{ tool_use_id: 'one', text: 'x'.repeat(600) + 'ONLY_CLUE_731' }] },
  { role: 'user', text: 'Use the old recovery information.', toolUses: [] },
];
const opts = optionsFrom({ preserveRecentMessages: 1, keepThreshold: .5, truncateHeadChars: 20 });
const asker = () => ({ ask: vi.fn(async () => ({ answers: { call_t1: { noul: .7 }, result_t1: { noul: .3 } } })) });

describe('Gradio adapter (offline fixtures; no real API calls)', () => {
  it('reuses scores at different thresholds with no further API calls', async () => {
    const client = asker();
    const cached = await score(messages, opts, 'test', client);
    const keep = reapply(messages, { ...opts, keepThreshold: .2 }, 'test', cached);
    const truncate = reapply(messages, opts, 'test', cached);
    const drop = reapply(messages, { ...opts, keepThreshold: .9 }, 'test', cached);
    expect(keep.decisions[0].action).toBe('keep');
    expect(truncate.decisions[0].action).toBe('drop_result');
    expect(truncate.messages[2].toolResults![0].text).not.toContain('ONLY_CLUE_731');
    expect(drop.decisions[0].action).toBe('drop_call');
    expect(drop.messages.map(m => m.text)).toEqual(['Do not modify legacy/', 'Use the old recovery information.']);
    expect(client.ask).toHaveBeenCalledTimes(1);
    expect(drop.stats.newRequests).toBe(0);
    expect(drop.stats.requests).toBe(1);
  });
  it('invalidates cache on transcript, goal, protection or model changes', async () => {
    const cached = await score(messages, opts, 'test', asker());
    expect(() => reapply([...messages, { role: 'user', text: 'new', toolUses: [] }], opts, 'test', cached)).toThrow('重新评分');
    expect(() => reapply(messages, { ...opts, goal: 'new' }, 'test', cached)).toThrow('重新评分');
    expect(() => reapply(messages, { ...opts, preserveRecentMessages: 2 }, 'test', cached)).toThrow('重新评分');
    expect(() => reapply(messages, opts, 'other', cached)).toThrow('重新评分');
  });
  it('never presents protected calls as API-scored calls', async () => {
    const client = asker();
    const protectedOptions = { ...opts, preserveRecentMessages: 4 };
    const cached = await score(messages, protectedOptions, 'test', client);
    expect(cached.result.decisions[0].reason).toBe('pinned');
    expect(cached.result.stats.requests).toBe(0);
    expect(client.ask).not.toHaveBeenCalled();
  });
  it('confirms the hard-case clue is absent from the state actually scored', () => {
    const fitted = fitState(messages, collectToolCalls(messages, 1), resolveOptions(opts));
    expect(JSON.stringify(fitted.state)).not.toContain('ONLY_CLUE_731');
    expect(JSON.stringify(fitted.state)).toContain('omitted');
  });
  it('recent baseline handles zero and removes orphan results', () => {
    expect(recentOnly(messages, 0)).toEqual([]);
    expect(recentOnly(messages, 2).map(m => m.text)).toEqual(['Use the old recovery information.']);
    expect(recentOnly(messages, 3)).toHaveLength(3);
  });
  it('rejects malformed schemas, duplicate IDs and orphan tool results', () => {
    expect(() => validateMessages([])).toThrow('1–500');
    expect(() => validateMessages([{ role: 'user', text: 'x' }])).toThrow('toolUses');
    expect(() => validateMessages([messages[2]])).toThrow('前面的工具调用');
    expect(() => validateMessages([messages[0], messages[1], messages[1], messages[2]])).toThrow('重复');
    expect(() => validateMessages(messages.slice(0, 2))).toThrow('缺少配对结果');
    expect(() => optionsFrom({ keepThreshold: 2 })).toThrow('无效');
    expect(() => optionsFrom({ preserveRecentMessages: 1.5 })).toThrow('无效');
    expect(validateMessages(messages)).toEqual(messages);
  });
  it('propagates scoring failures without generating fallback scores', async () => {
    const failing: JevAsker = { ask: async () => { throw new Error('offline failure'); } };
    await expect(score(messages, opts, 'test', failing)).rejects.toThrow('offline failure');
  });
});
