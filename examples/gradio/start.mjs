import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../../', import.meta.url));
const local = fileURLToPath(new URL(process.platform === 'win32' ? '../../.venv/Scripts/python.exe' : '../../.venv/bin/python', import.meta.url));
if (!existsSync(local)) {
  console.error('缺少 .venv。请先按 README 创建 Python 虚拟环境并安装 examples/gradio/requirements.txt。');
  process.exit(1);
}
const child = spawn(local, ['-X', 'utf8', 'examples/gradio/app.py'], { cwd: root, stdio: 'inherit', windowsHide: true });
child.on('error', () => { console.error('Gradio 启动失败，请检查 Python 依赖。'); process.exitCode = 1; });
child.on('exit', code => { process.exitCode = code ?? 0; });
process.on('SIGINT', () => child.kill('SIGINT'));
process.on('SIGTERM', () => child.kill('SIGTERM'));
