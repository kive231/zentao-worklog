import asyncio
import json

import httpx
import pytest

from backend.models import Worklog, EditRequest
from backend.zentao import ZenTao, RemoteError


def test_real_protocol_arrays_auth_and_edit_route():
    calls = []
    def handle(request):
        calls.append(request)
        if request.url.path.endswith('/tokens'):
            return httpx.Response(201, json={'token': 'test-token'})
        assert request.headers['Token'] == 'test-token'
        if request.method == 'GET':
            return httpx.Response(200, json={'status': 'success', 'data': json.dumps({'effort': {'id': 7, 'objectID': 3, 'account': 'tester'}})})
        return httpx.Response(200, json={'result': 'success'})
    async def run():
        remote = ZenTao({'base_url': 'https://zentao.test/zentao', 'account': 'tester'}, httpx.MockTransport(handle))
        await remote.login('secret')
        body = Worklog(task_id=3, date='2026-09-01', work='开发', consumed=2, left=8)
        await remote.create(body)
        await remote.edit(7, EditRequest(**body.model_dump(), expected='x'))
        await remote.close()
    asyncio.run(run())
    assert json.loads(calls[1].content) == {'date': ['2026-09-01'], 'work': ['开发'], 'consumed': ['2'], 'left': ['8']}
    assert calls[2].url.path == '/zentao/task-editEffort-7.json'
    assert calls[3].headers['content-type'].startswith('application/x-www-form-urlencoded')


def test_non_json_post_is_uncertain():
    async def run():
        remote = ZenTao({'base_url': 'https://zentao.test', 'account': 'tester'}, httpx.MockTransport(lambda _: httpx.Response(200, text='<html>login</html>')))
        try:
            await remote.request('POST', 'api.php/v1/tasks/3/estimate', json={})
            assert False
        except RemoteError as e:
            assert e.uncertain
        await remote.close()
    asyncio.run(run())


def test_project_directory_requests_current_user_involvement():
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url.params['involved'] == '1'
        assert request.url.params['status'] == 'undone'
        return httpx.Response(200, json={'projects': [
            {'id': 1, 'name': '我负责的', 'PM': 'tester'},
            {'id': 2, 'name': '我参与的', 'PM': 'someone-else'},
        ], 'total': 2})
    async def run():
        remote = ZenTao({'base_url': 'https://zentao.test', 'account': 'tester'}, httpx.MockTransport(handle))
        try:
            assert [p['id'] for p in await remote.projects()] == [1, 2]
        finally:
            await remote.close()
    asyncio.run(run())
    assert len(calls) == 1


def test_directory_small_pages_retry_without_missing_or_duplicating_rows(monkeypatch):
    calls = []
    pauses = []
    async def pause(seconds):
        pauses.append(seconds)
    monkeypatch.setattr('backend.zentao.asyncio.sleep', pause)
    def handle(request):
        page = int(request.url.params['page'])
        calls.append(page)
        assert request.url.params['limit'] == '100'
        if calls == [1]:
            raise httpx.RemoteProtocolError('Server disconnected', request=request)
        if page == 2 and calls.count(2) == 1:
            return httpx.Response(503)
        start = (page - 1) * 100 + 1
        return httpx.Response(200, json={'total': 205, 'executions': [
            {'id': i, 'name': str(i), 'project': 1} for i in range(start, min(start + 100, 206))
        ]})
    async def run():
        remote = ZenTao({'base_url': 'https://zentao.test', 'account': 'tester'}, httpx.MockTransport(handle))
        try:
            assert [row['id'] for row in await remote.executions()] == list(range(1, 206))
        finally:
            await remote.close()
    asyncio.run(run())
    assert calls == [1, 1, 2, 2, 3]
    assert pauses == [0.5, 0.5]


@pytest.mark.parametrize('method,expected_calls', [('GET', 3), ('POST', 1)])
def test_disconnect_retries_only_reads_and_preserves_uncertain_writes(monkeypatch, method, expected_calls):
    calls = []
    async def pause(_):
        pass
    monkeypatch.setattr('backend.zentao.asyncio.sleep', pause)
    def handle(request):
        calls.append(request)
        raise httpx.RemoteProtocolError('Server disconnected', request=request)
    async def run():
        remote = ZenTao({'base_url': 'https://zentao.test', 'account': 'tester'}, httpx.MockTransport(handle))
        try:
            with pytest.raises(RemoteError) as error:
                await remote.request(method, 'api.php/v1/tasks/3/estimate')
            assert error.value.uncertain == (method == 'POST')
            assert ('服务端中断响应' if method == 'GET' else '写入结果待确认') in str(error.value)
        finally:
            await remote.close()
    asyncio.run(run())
    assert len(calls) == expected_calls


@pytest.mark.parametrize('status', [401, 403, 400])
def test_permission_and_validation_errors_are_not_retried(status):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={'error': 'Rejected'})
    async def run():
        remote = ZenTao({'base_url': 'https://zentao.test', 'account': 'tester'}, httpx.MockTransport(handle))
        try:
            with pytest.raises(RemoteError):
                await remote.request('GET', 'api.php/v1/projects')
        finally:
            await remote.close()
    asyncio.run(run())
    assert len(calls) == 1


def test_read_concurrency_is_bounded():
    async def run():
        active = peak = 0
        async def handle(request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return httpx.Response(200, json={'ok': True})
        remote = ZenTao({'base_url': 'https://zentao.test', 'account': 'tester'}, httpx.MockTransport(handle))
        try:
            await asyncio.gather(*(remote.request('GET', 'api.php/v1/projects') for _ in range(8)))
            assert peak == 2
        finally:
            await remote.close()
    asyncio.run(run())
