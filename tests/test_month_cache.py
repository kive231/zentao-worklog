import asyncio
from copy import deepcopy

from backend import app as module
from backend.cache import covered, directory_for_month, might_have_efforts
from test_backend import client, remote, ENTRY


def test_task_month_filter_keeps_backdated_work_and_unknown_metadata():
    assert not might_have_efforts({'lastEditedDate': '2026-09-15T12:00:00Z', 'consumed': 8}, '2026-10-01')
    assert might_have_efforts({'lastEditedDate': '2026-11-02T00:00:00Z', 'consumed': 8, 'estStarted': '2026-11-01'}, '2026-10-01')
    assert might_have_efforts({'lastEditedDate': '', 'consumed': 8}, '2026-10-01')
    assert might_have_efforts({'lastEditedDate': '2026-09-30T18:00:00Z', 'consumed': 8}, '2026-10-01')
    assert not might_have_efforts({'lastEditedDate': '2026-10-30T12:00:00Z', 'consumed': 0}, '2026-10-01')


def test_entry_directory_is_scoped_to_month_and_used_stages():
    cat = {'projects': [{'id': 1}], 'executions': [{'id': 2}, {'id': 3}], 'tasks': [
        {'id': 1, 'execution_id': 2, 'estStarted': '2026-10-01', 'deadline': '2026-10-31'},
        {'id': 2, 'execution_id': 3, 'estStarted': '2026-09-01', 'deadline': '2026-09-30'},
    ]}
    assert [t['id'] for t in directory_for_month(cat, '2026-10')['tasks']] == [1]
    assert directory_for_month(cat, '2026-10')['executions'] == [{'id': 2}]
    assert not covered([{'start': '2026-10-01', 'end': '2026-10-31', 'project_id': 0}], '2026-09-01', '2026-09-30', 0)


def test_month_and_task_cache_reuse_and_changed_task_refresh(client):
    s = next(iter(module.sessions.values()))
    reads = []
    original_efforts = s.remote.efforts
    async def efforts(tid):
        reads.append(tid)
        return await original_efforts(tid)
    async def tasks():
        return [
            {'id': 3, 'project_id': 1, 'execution_id': 2, 'name': '跨月任务', 'lastEditedDate': '2026-10-30T00:00:00Z', 'consumed': 2, 'left': 8},
            {'id': 4, 'project_id': 1, 'execution_id': 2, 'name': '九月旧任务', 'lastEditedDate': '2026-09-15T00:00:00Z', 'consumed': 1, 'left': 0},
        ]
    s.remote.tasks, s.remote.efforts = tasks, efforts
    s.remote.logs = [{**ENTRY, 'id': 1, 'project_id': 1, 'execution_id': 2, 'consumed': 2, 'date': '2026-10-08'}]
    client.get('/api/catalog?month=2026-10&refresh=true')
    asyncio.run(module.sync_efforts(s, 0, '2026-10-01', '2026-10-31'))
    assert reads == [3]  # September-only task is not requested for October.
    assert client.get('/api/worklogs?start=2026-10-01&end=2026-10-31').json()['daily']['2026-10-08'] == 2
    assert client.post('/api/sync?start=2026-10-01&end=2026-10-31').json()['cached'] is True
    assert reads == [3]
    client.get('/api/catalog?month=2026-11')
    assert client.post('/api/sync?start=2026-10-01&end=2026-10-31').json()['cached'] is True
    assert reads == [3]
    # Another month reuses the already fetched task's entire history.
    asyncio.run(module.sync_efforts(s, 0, '2026-11-01', '2026-11-30'))
    assert reads == [3]
    assert client.get('/api/worklogs?start=2026-10-01&end=2026-10-31').json()['complete'] is True
    # Metadata changes invalidate the per-task cache, including corrections to old dates.
    s.history_catalog['tasks'][0]['lastEditedDate'] = '2026-10-30T01:00:00Z'
    s.remote.logs[0]['consumed'] = 3
    asyncio.run(module.sync_efforts(s, 0, '2026-10-01', '2026-10-31'))
    assert reads == [3, 3]
    assert client.get('/api/worklogs?start=2026-10-01&end=2026-10-31').json()['daily']['2026-10-08'] == 3


def test_reopening_cached_month_directory_does_not_refetch(client):
    s = next(iter(module.sessions.values()))
    calls = []
    original = s.remote.tasks
    async def tasks():
        calls.append('tasks')
        return await original()
    s.remote.tasks = tasks
    client.get('/api/catalog?month=2026-10')
    client.get('/api/catalog?month=2026-10')
    assert len(calls) == 1
    client.get('/api/catalog?month=2026-09')
    client.get('/api/catalog?month=2026-10')
    assert len(calls) == 2


def test_failed_month_read_never_becomes_complete(client):
    from backend.zentao import RemoteError
    s = next(iter(module.sessions.values()))
    async def broken(tid):
        raise RemoteError('upstream failure')
    s.remote.efforts = broken
    asyncio.run(module.sync_efforts(s, 0, '2026-10-01', '2026-10-31'))
    assert not client.get('/api/worklogs?start=2026-10-01&end=2026-10-31').json()['complete']
