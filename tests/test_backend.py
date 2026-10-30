import asyncio
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from backend import app as module, store
from backend.imports import match_rows, parse_log
from backend.zentao import RemoteError, duplicate_key, signature


class FakeRemote:
    def __init__(self, profile):
        self.profile, self.account = profile, profile['account']
        self.logs, self.writes = [], 0
        self.mode = 'ok'

    async def login(self, password):
        if password != 'test-password':
            raise RemoteError('密码错误', status=401)

    async def close(self):
        pass

    async def projects(self, status='undone'):
        return [{'id': 1, 'name': '测试项目'}]

    async def executions(self):
        return [{'id': 2, 'project_id': 1, 'name': '开发'}]

    async def tasks(self):
        return [{'id': 3, 'project_id': 1, 'execution_id': 2, 'name': '测试任务', 'left': 10, 'consumed': 0, 'status': 'doing'}]

    async def efforts(self, tid):
        return deepcopy([r for r in self.logs if r['task_id'] == tid])

    async def create(self, entry):
        self.writes += 1
        if self.mode == 'fail':
            raise RemoteError('无写入权限')
        if self.mode == 'unknown':
            raise RemoteError('超时', uncertain=True)
        row = {**entry.model_dump(mode='json'), 'id': len(self.logs) + 1, 'project_id': 1, 'execution_id': 2, 'account': self.account, 'consumed': float(entry.consumed), 'left': float(entry.left)}
        row['signature'] = signature(row)
        self.logs.append(row)
        if self.mode == 'timeout_after_write':
            raise RemoteError('响应丢失', uncertain=True)

    async def edit(self, eid, entry):
        self.writes += 1
        row = next(r for r in self.logs if r['id'] == eid)
        row.update({k: v for k, v in entry.model_dump(mode='json').items() if k != 'expected'})
        row.update(consumed=float(entry.consumed), left=float(entry.left))
        row['signature'] = signature(row)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    monkeypatch.setattr(module, 'ZenTao', FakeRemote)
    module.sessions.clear()
    with TestClient(module.app, base_url='http://127.0.0.1', headers={'X-Worklog-Client': '1'}) as c:
        p = c.post('/api/profiles', json={'name': '公司', 'base_url': 'https://example.test', 'account': 'tester'}).json()
        assert c.post('/api/session', json={'profile_id': p['id'], 'password': 'test-password'}).status_code == 200
        assert c.get('/api/catalog').status_code == 200
        yield c
    module.sessions.clear()


def remote():
    return next(iter(module.sessions.values())).remote


ENTRY = {'task_id': 3, 'date': '2026-09-01', 'work': '分切页面开发', 'consumed': 2, 'left': 8}


def draft(**kwargs):
    return {'id': 'line-1', **ENTRY, 'project_id': 1, 'selected': True, **kwargs}


def test_parser_keeps_edited_sources_and_missing_fields():
    text = '# 9月日志\n## 示例（本月 6 小时）\n- 2026-09-01：开发（2）✅\n- 2026-09-02：自测 +1.5\n- 2026-09-03：缺工时\n无日期内容'
    rows = parse_log(text)
    assert len(rows) == 4
    assert rows[0]['project_hint'] == '示例'
    assert rows[0]['consumed'] == 2
    assert rows[1]['work'] == '自测'
    assert rows[1]['consumed'] == 1.5
    assert rows[2]['consumed'] is None
    assert rows[3]['date'] == ''


def test_profile_does_not_persist_credentials(client):
    body = client.get('/api/profiles').json()
    assert set(body[0]) == {'id', 'name', 'base_url', 'account'}
    assert b'test-password' not in (store.DATA / 'profiles.db').read_bytes()
    assert client.get('/api/session').json()['profile']['account'] == 'tester'


def test_import_template_auto_matches_project_then_task_ignoring_whitespace(client):
    text = '## 2026-09-01\n- 测 试　项目 / 测\t试 任 务 |  完成页面  联调  | + 1.5  \n\n## 2026-09-02\n- 测试项目 / 不存在的任务 | 功能测试 | +2'
    data = client.post('/api/import/parse', json={'text': text}).json()
    first, missing = data['rows']
    assert (first['project_id'], first['task_id'], first['left']) == (1, 3, 10)
    assert (first['date'], first['work'], first['consumed']) == ('2026-09-01', '完成页面  联调', 1.5)
    assert first['format_error'] == ''
    assert missing['project_id'] == 1 and missing['task_id'] == 0
    checked = client.post('/api/import/review', json={'rows': data['rows']}).json()
    assert checked['count'] == 1 and checked['total'] == 1.5
    assert remote().writes == 0


def test_matching_never_guesses_ambiguous_or_partial_names():
    rows = parse_log('## 2026-09-01\n- 项目 / 开发 | 联调 | +2')
    cat = {'projects': [{'id': 1, 'name': '项目'}], 'tasks': [
        {'id': 2, 'project_id': 1, 'name': '开发', 'left': 1},
        {'id': 3, 'project_id': 1, 'name': '开 发', 'left': 2},
        {'id': 4, 'project_id': 9, 'name': '开发', 'left': 3},
    ]}
    assert match_rows(rows, cat)[0]['task_id'] == 0
    assert '同名任务' in rows[0]['message']
    cat['projects'].append({'id': 5, 'name': '项 目'})
    assert match_rows(rows, cat)[0]['project_id'] == 0
    cat['projects'] = [{'id': 1, 'name': '项目完整版'}]
    assert match_rows(rows, cat)[0]['project_id'] == 0


@pytest.mark.parametrize('line', ['项目 /  | 联调 | +2', '项目 / 开发 | 联调 | 缺工时', '项目 / 开发 | +2'])
def test_malformed_template_cannot_be_imported(client, line):
    rows = client.post('/api/import/parse', json={'text': '## 2026-09-01\n- ' + line}).json()['rows']
    assert rows[0]['format_error']
    assert rows[0]['task_id'] == 0
    assert client.post('/api/import/review', json={'rows': rows}).json()['count'] == 0


def test_add_readback_idempotency_and_duplicate(client):
    headers = {'Idempotency-Key': 'operation-1'}
    first = client.post('/api/worklogs', json=ENTRY, headers=headers).json()
    assert first['status'] == 'success'
    assert client.post('/api/worklogs', json=ENTRY, headers=headers).json() == first
    assert remote().writes == 1
    assert client.post('/api/worklogs', json=ENTRY, headers={'Idempotency-Key': 'operation-2'}).status_code == 409
    assert client.post('/api/worklogs', json={**ENTRY, 'consumed': 3}, headers=headers).status_code == 409


def test_edit_optimistic_concurrency_and_readback(client):
    row = client.post('/api/worklogs', json=ENTRY, headers={'Idempotency-Key': 'operation-1'}).json()['row']
    new = {**ENTRY, 'consumed': 1.5, 'expected': row['signature']}
    result = client.put(f"/api/worklogs/{row['id']}", json=new, headers={'Idempotency-Key': 'edit-0001'}).json()
    assert result['row']['consumed'] == 1.5
    assert client.put(f"/api/worklogs/{row['id']}", json=new, headers={'Idempotency-Key': 'edit-0002'}).status_code == 409


def test_unknown_write_is_never_blindly_retried(client):
    remote().mode = 'unknown'
    headers = {'Idempotency-Key': 'unknown-01'}
    assert client.post('/api/worklogs', json=ENTRY, headers=headers).json()['status'] == 'unknown'
    assert client.post('/api/worklogs', json=ENTRY, headers=headers).json()['status'] == 'unknown'
    assert remote().writes == 1


def test_lost_response_reconciles_success(client):
    remote().mode = 'timeout_after_write'
    assert client.post('/api/worklogs', json=ENTRY, headers={'Idempotency-Key': 'lost-response'}).json()['status'] == 'success'
    assert remote().writes == 1


def test_import_uses_reviewed_edited_snapshot_and_dedup(client):
    rows = [draft(consumed=1.5), draft(id='line-2', consumed=1.5), draft(id='line-3', task_id=0), draft(id='line-4', work='未选记录', selected=False)]
    checked = client.post('/api/import/review', json={'rows': rows}).json()
    assert checked['count'] == 1 and checked['total'] == 1.5
    assert [r['status'] for r in checked['rows']] == ['ready', 'duplicate', 'invalid', 'ready']
    assert checked['existing_complete'] is False
    result = client.post('/api/import/commit', json={'review_id': checked['id']}).json()
    assert result['rows'][0]['status'] == 'success'
    assert remote().logs[0]['consumed'] == 1.5
    assert client.post('/api/import/commit', json={'review_id': checked['id']}).json() == result
    assert remote().writes == 1


def test_new_remote_duplicate_blocks_entire_commit(client):
    checked = client.post('/api/import/review', json={'rows': [draft()]}).json()
    client.post('/api/worklogs', json=ENTRY, headers={'Idempotency-Key': 'other-tab'})
    assert client.post('/api/import/commit', json={'review_id': checked['id']}).status_code == 409
    assert remote().writes == 1


@pytest.mark.parametrize('change', [{'consumed': 0}, {'consumed': -1}, {'consumed': 25}, {'date': '2099-01-01'}, {'consumed': 1.234}, {'work': '  '}, {'left': -1}])
def test_invalid_worklog_never_written(client, change):
    assert client.post('/api/worklogs', json={**ENTRY, **change}, headers={'Idempotency-Key': 'invalid-row'}).status_code == 422
    assert remote().writes == 0


def test_origin_and_session_boundaries(client):
    assert client.post('/api/profiles', json={}, headers={'Origin': 'https://evil.test'}).status_code == 403
    assert client.post('/api/profiles', json={}, headers={'X-Worklog-Client': ''}).status_code == 403
    client.delete('/api/session')
    assert client.get('/api/worklogs?start=2026-09-01&end=2026-09-30').status_code == 401


def test_sync_reports_failures_instead_of_complete_zero(client):
    s = next(iter(module.sessions.values()))
    async def broken(tid):
        raise RemoteError('读取失败')
    s.remote.efforts = broken
    asyncio.run(module.sync_efforts(s, 0))
    data = client.get('/api/worklogs?start=2026-09-01&end=2026-09-30').json()
    assert data['complete'] is False
    assert len(data['sync']['errors']) == 1


def test_duplicate_identity_includes_task_date_content_and_hours():
    assert duplicate_key(ENTRY) == duplicate_key({**ENTRY, 'work': '  分切页面开发  '})
    assert duplicate_key(ENTRY) != duplicate_key({**ENTRY, 'task_id': 4})


def test_catalog_and_sync_exclude_unrelated_projects(client):
    s = next(iter(module.sessions.values()))
    async def tasks():
        return [
            {'id': 3, 'project_id': 1, 'execution_id': 2, 'name': '我的项目任务'},
            {'id': 9, 'project_id': 8, 'execution_id': 7, 'name': '无关任务'},
        ]
    async def executions():
        return [{'id': 2, 'project_id': 1}, {'id': 7, 'project_id': 8}]
    s.remote.tasks, s.remote.executions = tasks, executions
    s.efforts[9] = [{**ENTRY, 'task_id': 9, 'project_id': 8}]
    data = client.get('/api/catalog?refresh=true').json()
    assert [p['id'] for p in data['projects']] == [1]
    assert [e['id'] for e in data['executions']] == [2]
    assert [t['id'] for t in data['tasks']] == [3]
    assert 9 not in s.efforts
    asyncio.run(module.sync_efforts(s, 0))
    assert s.sync['total'] == 1
    assert s.sync['complete'] is True


def test_history_includes_suspended_and_closed_projects_without_expanding_entry_choices(client):
    s = next(iter(module.sessions.values()))
    async def projects(status='undone'):
        active = [{'id': 1, 'name': '在做的项目', 'status': 'doing'}]
        return active if status == 'undone' else active + [
            {'id': 8, 'name': '挂起项目', 'status': 'suspended'},
            {'id': 10, 'name': '已关闭项目', 'status': 'closed'},
        ]
    async def tasks():
        return [{'id': 3, 'project_id': 1, 'execution_id': 2, 'name': '当前任务'},
                {'id': 4, 'project_id': 8, 'execution_id': 7, 'name': '历史任务'},
                {'id': 5, 'project_id': 10, 'execution_id': 11, 'name': '已完成任务'},
                {'id': 9, 'project_id': 99, 'execution_id': 90, 'name': '无关任务'}]
    async def executions():
        return [{'id': 2, 'project_id': 1, 'name': '开发'}, {'id': 7, 'project_id': 8, 'name': '历史执行'}, {'id': 11, 'project_id': 10, 'name': '归档执行'}]
    s.remote.projects, s.remote.tasks, s.remote.executions = projects, tasks, executions
    s.remote.logs = [{**ENTRY, 'id': 1, 'task_id': 4, 'project_id': 8, 'execution_id': 7, 'date': '2026-10-08', 'consumed': 1.5},
                     {**ENTRY, 'id': 2, 'task_id': 5, 'project_id': 10, 'execution_id': 11, 'date': '2026-10-08', 'consumed': 6.5}]
    choices = client.get('/api/catalog?refresh=true').json()
    assert [p['id'] for p in choices['projects']] == [1]
    assert [t['id'] for t in choices['tasks']] == [3]
    asyncio.run(module.sync_efforts(s, 0))
    data = client.get('/api/worklogs?start=2026-10-01&end=2026-10-31').json()
    assert data['complete'] is True and data['daily']['2026-10-08'] == 8
    assert len(data['rows']) == 2 and s.sync['total'] == 3
    assert {p['id'] for p in data['history_projects']} == {8, 10}
    assert {r['project_name'] for r in data['rows']} == {'挂起项目', '已关闭项目'}
    one = client.get('/api/worklogs?start=2026-10-01&end=2026-10-31&project_id=8').json()
    assert one['daily']['2026-10-08'] == 1.5
    client.get('/api/catalog?refresh=true')
    assert s.efforts[4][0]['consumed'] == 1.5
