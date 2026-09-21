import copy
from samples import SAMPLES
from validation_view import build_report, overview, question_details, preparation


def state_fixture():
    return {'case': copy.deepcopy(SAMPLES[0]), 'options': {'keepThreshold': .5},
            'result': {'messages': SAMPLES[0]['messages'], 'stats': {'charsBefore': 100, 'charsAfter': 50}}}


def test_categories_and_focus_filter():
    state = state_fixture()
    rows = [[c['question'], c['answer'], 'original', a, 'compressed', b] for c, (a,b) in zip(state['case']['checks'],
            [('匹配','未匹配'),('未匹配','未匹配'),('未匹配','匹配'),('匹配','匹配')])]
    report = build_report(state, rows)
    assert [i['status'] for i in report['items']] == ['疑似受压缩影响', '两边均未匹配，暂不能归因', '仅压缩后匹配，需复核', '已测问题未发现回答退化']
    assert '1 题' in overview(report)
    assert question_details(report, '只看需关注').count('<section') == 3
    assert question_details(report).count('标准答案：') == 4


def test_local_only_and_escaping():
    state = state_fixture()
    state['case']['checks'][0]['question'] = '<script>bad</script>'
    report = build_report(state)
    assert '回答对比尚未完成' in overview(report)
    assert '<script>' not in question_details(report)
    assert '&lt;script&gt;' in question_details(report)
    assert '当前没有需关注项' in question_details(report, '只看需关注')
    assert '未配置回答模型' in preparation(state, {'answer': False})


def test_empty_not_perfect_score():
    state = state_fixture()
    state['case']['checks'] = []
    assert '尚无可验证' in overview(build_report(state))
    assert '没有验证问题' in preparation(state, {'answer': True, 'answerModel': 'test'})
