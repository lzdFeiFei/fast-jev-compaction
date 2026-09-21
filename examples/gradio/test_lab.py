import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import lab
from presentation import comparison_html
from samples import SAMPLES


def test_aligned_comparison_preserves_indices_and_escapes_deleted_output():
    original = [
        {'role': 'user', 'text': 'same', 'toolUses': []},
        {'role': 'assistant', 'text': '', 'toolUses': [{'tool_use_id': 'x', 'tool': 'Read', 'input': {}}]},
        {'role': 'user', 'text': '', 'toolUses': [], 'toolResults': [{'tool_use_id': 'x', 'text': '<script>lost</script>'}]},
        {'role': 'user', 'text': 'same', 'toolUses': []},
    ]
    result = {'sourceIndices': [0, 3], 'messages': [original[0], original[3]],
              'calls': [{'tool_use_id': 'x'}], 'decisions': [{'action': 'drop_call', 'reason': 'call_dropped', 'keepCall': .1, 'keepResult': .2}]}
    markup = comparison_html(original, result)
    assert markup.count('class="compare-row') == 4
    assert '#04' in markup
    assert markup.count('已删除 ·') == 2
    assert markup.count('查看评分') == 1
    assert '<script>' not in markup
    assert '&lt;script&gt;lost' in markup


def test_comparison_marks_actual_short_output_as_kept():
    original = [{'role': 'user', 'text': '', 'toolUses': [], 'toolResults': [{'tool_use_id': 'x', 'text': 'short'}]}]
    result = {'sourceIndices': [0], 'messages': original, 'calls': [{'tool_use_id': 'x'}],
              'decisions': [{'action': 'drop_result', 'reason': 'result_dropped', 'keepCall': .7, 'keepResult': .1}]}
    markup = comparison_html(original, result)
    assert 'compare-row retained' in markup
    result['messages'] = [{**original[0], 'toolResults': [{'tool_use_id': 'x', 'text': 's [truncated]'}]}]
    assert 'compare-row trimmed' in comparison_html(original, result)


@pytest.mark.parametrize('case', SAMPLES, ids=[s['name'] for s in SAMPLES])
def test_builtin_evidence_really_exists(case):
    parsed = lab.parse_input(json.dumps(case, ensure_ascii=False))
    assert all(lab.evidence_present(parsed['messages'], c['evidence']) for c in parsed['checks'])


def test_hard_case_evidence_only_in_old_output():
    case = SAMPLES[-1]
    for check in case['checks'][:3]:
        assert not any(check['answer'] in m['text'] for m in case['messages'])
    trimmed = copy.deepcopy(case['messages'])
    trimmed[2]['toolResults'][0]['text'] = trimmed[2]['toolResults'][0]['text'][:300]
    rows = lab.verification(case, [case['messages'], trimmed])
    assert [r[-1] for r in rows[:3]] == ['缺失'] * 3
    assert all(r[-2] == '保留' for r in rows)


def test_import_error_and_no_checks():
    with pytest.raises(lab.LabError, match='第 1 行'):
        lab.parse_input('{bad')
    parsed = lab.parse_input(json.dumps(SAMPLES[0]['messages']))
    assert parsed['checks'] == []
    bad = copy.deepcopy(SAMPLES[0])
    bad['checks'][0]['evidence']['quote'] = 'not in the original'
    with pytest.raises(lab.LabError, match='找不到'):
        lab.parse_input(json.dumps(bad))


def test_html_escapes_imported_content():
    markup = lab.transcript_html([{'role': 'user', 'text': '<script>alert(1)</script>', 'toolUses': []}])
    assert '<script>' not in markup
    assert '&lt;script&gt;' in markup


def test_stale_input_guard():
    state = {'input_key': lab.input_key('old', 2, '')}
    lab.require_current(state, 'old', 2, '')
    for args in [('new', 2, ''), ('old', 3, ''), ('old', 2, 'new goal')]:
        with pytest.raises(lab.LabError, match='改变'):
            lab.require_current(state, *args)


def test_answer_matching_requires_all_groups():
    check = {'answer_groups': [['72 小时', '72 hours'], ['手册']]}
    assert lab.answer_matches('手册：72小时', check)
    assert not lab.answer_matches('72 hours', check)


def test_missing_answer_config_never_fabricates(monkeypatch):
    monkeypatch.setattr(lab, 'bridge', lambda *a, **k: {'answer': False})
    with pytest.raises(lab.LabError, match='未生成任何'):
        lab.answer_comparison({})


def test_same_questions_no_reference_answers_sent(monkeypatch):
    sent = []
    def fake(command, **kwargs):
        if command == 'config':
            return {'answer': True}
        sent.append(kwargs)
        return {'answers': ['legacy/'] * 4, 'model': 'offline-test-only', 'ms': 10, 'requests': 1}
    monkeypatch.setattr(lab, 'bridge', fake)
    case = SAMPLES[0]
    rows, _ = lab.answer_comparison({'case': case, 'result': {'messages': case['messages'][-1:]}})
    assert len(sent) == 2
    assert sent[0]['questions'] == sent[1]['questions']
    assert set(sent[0]) == {'messages', 'questions'}
    assert sent[0]['messages'] != sent[1]['messages']
    assert len(rows) == 4


def test_batch_records_api_failures_and_exports(monkeypatch, tmp_path):
    real_bridge = lab.bridge
    def fake(command, **kwargs):
        if command == 'config':
            return {'answer': False, 'jevModel': 'test', 'answerModel': ''}
        if command == 'score':
            raise lab.LabError('API 限流')
        return real_bridge(command, **kwargs)
    monkeypatch.setattr(lab, 'bridge', fake)
    monkeypatch.setattr(lab, 'EXPORTS', tmp_path)
    table, report = lab.batch_evaluate(.5, 2, 300)
    assert len(table) == 12
    assert sum(r['status'] == '失败' for r in report['records']) == 4
    assert report['sample_count'] == 4
    assert report['question_count'] == 17
    json_file, csv_file = lab.export_report(report, table)
    assert json.loads(Path(json_file).read_text(encoding='utf-8'))['sample_count'] == 4
    assert 'API 限流' in Path(csv_file).read_text(encoding='utf-8-sig')
