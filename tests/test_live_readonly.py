"""Explicitly opt-in read-only integration check. Never creates/edits worklogs."""
import asyncio
import json
import os
from pathlib import Path

import pytest

from backend.zentao import ZenTao


@pytest.mark.skipif(not os.environ.get('WORKLOG_LIVE_CONFIG'), reason='requires explicit existing config path')
def test_read_only_zentao_connection():
    config = json.loads(Path(os.environ['WORKLOG_LIVE_CONFIG']).read_text(encoding='utf-8-sig'))
    async def run():
        remote = ZenTao(config)
        try:
            await remote.login(config['password'])
            projects = await remote.projects()
            assert projects and all('id' in p and 'name' in p for p in projects)
            task_id = int(os.environ.get('WORKLOG_LIVE_TASK', '0'))
            assert task_id > 0, 'explicit read-only task required'
            task = await remote.task(task_id)
            assert task['id'] == task_id
            rows = await remote.efforts(task_id)
            assert all(r['task_id'] == task_id and r['account'] == config['account'] for r in rows)
            if rows:
                reply = await remote.request('GET', f"task-editEffort-{rows[0]['id']}.json")
                data = json.loads(reply['data']) if isinstance(reply['data'], str) else reply['data']
                assert int(data['effort']['id']) == rows[0]['id']
        finally:
            await remote.close()
    asyncio.run(run())
