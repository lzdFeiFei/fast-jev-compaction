import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { loadEnvFile } from 'node:process';
import { compactMessages, reductionRatio } from '../../src/index.js';
import { messages } from '../transcript.js';

const envFile = new URL('../../.env', import.meta.url);
if (existsSync(envFile)) loadEnvFile(envFile);
const port = Number(process.env.PORT ?? 3000);
const origin = `http://127.0.0.1:${port}`;
let busy = false;
const server = createServer(async (req, res) => {
  const json = (status: number, value: unknown) => {
    res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
    res.end(JSON.stringify(value));
  };
  try {
    if (req.method === 'GET' && req.url === '/') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(await readFile(new URL('./index.html', import.meta.url)));
    } else if (req.method === 'GET' && req.url === '/api/demo') {
      json(200, { messages, configured: Boolean(process.env.TYPESAFE_API_KEY) });
    } else if (req.method === 'POST' && req.url === '/api/compact') {
      if (req.headers.origin !== origin || req.headers['content-type'] !== 'application/json') {
        json(403, { error: '请从本地演示页面发起请求。' }); return;
      }
      if (busy) { json(409, { error: '正在压缩，请稍后再试。' }); return; }
      if (!process.env.TYPESAFE_API_KEY) { json(503, { error: '请在项目根目录 .env 中配置 TYPESAFE_API_KEY，然后重启服务。' }); return; }
      let body = '';
      for await (const chunk of req) {
        body += chunk;
        if (body.length > 2048) { json(413, { error: '请求过大。' }); return; }
      }
      let input: { keepThreshold?: unknown; preserveRecentMessages?: unknown };
      try { input = JSON.parse(body); } catch { json(400, { error: '参数格式无效。' }); return; }
      const threshold = input?.keepThreshold;
      const recent = input?.preserveRecentMessages;
      if (typeof threshold !== 'number' || !Number.isFinite(threshold) || threshold < 0 || threshold > 1 ||
          typeof recent !== 'number' || !Number.isInteger(recent) || recent < 0 || recent > messages.length) {
        json(400, { error: '阈值必须为 0–1，保留消息数必须为有效整数。' }); return;
      }
      busy = true;
      try {
        const result = await compactMessages(messages, {
          keepThreshold: threshold, preserveRecentMessages: recent,
          fetch: (url, options) => fetch(url, { ...options, signal: AbortSignal.timeout(45_000) }),
        });
        json(200, { ...result, reduction: reductionRatio(result) });
      } catch {
        json(502, { error: 'Jev 请求失败或超时。请检查网络、TypeSafe 密钥和额度后重试。' });
      } finally { busy = false; }
    } else { json(404, { error: 'Not found' }); }
  } catch { if (!res.headersSent) json(500, { error: '本地服务发生错误。' }); else res.end(); }
});
server.listen(port, '127.0.0.1', () => console.log(`Jev demo: ${origin}`));
server.on('error', (error) => { console.error(error.message); process.exitCode = 1; });
