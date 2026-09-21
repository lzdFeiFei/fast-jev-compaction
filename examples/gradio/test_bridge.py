"""Real Node bridge against a local HTTP fixture, never a paid provider."""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import subprocess
import threading

import pytest
from lab import ROOT
from samples import SAMPLES


def invoke(payload, **environment):
    env = {**os.environ, 'TYPESAFE_API_KEY': '', 'ANSWER_API_KEY': '', 'ANSWER_MODEL': '', 'ANSWER_BASE_URL': '', **environment}
    process = subprocess.run(['node', '--import', 'tsx', 'examples/gradio/bridge.ts'], cwd=ROOT,
                             input=json.dumps(payload), encoding='utf-8', capture_output=True, env=env, timeout=10)
    assert process.returncode == 0
    assert 'fixture-private-key' not in process.stdout
    assert 'fixture-private-key' not in process.stderr
    return json.loads(process.stdout)


def test_missing_configuration():
    result = invoke({'command': 'answer', 'messages': SAMPLES[0]['messages'], 'questions': ['问题']})
    assert not result['ok']
    assert '尚未配置' in result['error']


@pytest.mark.parametrize('status,body,expected', [
    (200, {'choices': [{'message': {'content': '{"answers":["legacy/"]}'}}]}, None),
    (200, {'choices': [{'message': {'content': 'not valid JSON'}}]}, '未返回约定'),
    (429, {'error': 'fixture-private-key'}, '限流'),
    (401, {'error': 'fixture-private-key'}, '认证失败'),
    (500, {'error': 'fixture-private-key'}, '服务异常'),
])
def test_answer_transport_and_sanitized_errors(status, body, expected):
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())
        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = invoke({'command': 'answer', 'messages': SAMPLES[0]['messages'], 'questions': ['禁止修改哪个目录？']},
                        ANSWER_API_KEY='fixture-private-key', ANSWER_MODEL='fixture-model',
                        ANSWER_BASE_URL=f'http://127.0.0.1:{server.server_port}/v1')
        if expected:
            assert not result['ok']
            assert expected in result['error']
        else:
            assert result['data']['answers'] == ['legacy/']
            assert result['data']['model'] == 'fixture-model'
        assert seen[0][0] == '/v1/chat/completions'
        request = seen[0][1]
        assert request['temperature'] == 0
        prompt = json.loads(request['messages'][1]['content'])
        assert set(prompt) == {'context', 'questions'}
    finally:
        server.shutdown()
        server.server_close()
