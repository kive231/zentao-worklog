import asyncio
import json

import httpx

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
