import hashlib
import html
import json
import re
import unicodedata

import httpx


class RemoteError(Exception):
    def __init__(self, message, uncertain=False, status=502):
        super().__init__(message)
        self.uncertain, self.status = uncertain, status


def number_id(value):
    return int((value.get('id', 0) if isinstance(value, dict) else value) or 0)


def plain(value):
    return html.unescape(re.sub(r'<[^>]+>', '', str(value or ''))).strip()


def account_of(value):
    return value.get('account', '') if isinstance(value, dict) else str(value or '')


def rows_of(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.values())
    raise RemoteError('禅道返回的数据结构不符合预期')


def signature(row):
    data = {k: str(row.get(k, '')) for k in ('id', 'date', 'work', 'consumed', 'left', 'account')}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def duplicate_key(row):
    work = unicodedata.normalize('NFKC', row['work']).strip()
    work = re.sub(r'\s+', ' ', work)
    return int(row['task_id']), str(row['date'])[:10], work, round(float(row['consumed']), 2)


class ZenTao:
    def __init__(self, profile, transport=None):
        self.profile = profile
        self.account = profile['account']
        self.client = httpx.AsyncClient(base_url=profile['base_url'].rstrip('/') + '/', timeout=30, follow_redirects=False, transport=transport)

    async def close(self):
        await self.client.aclose()

    async def request(self, method, path, **kwargs):
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError:
            raise RemoteError('禅道连接失败，请检查地址和网络' if method == 'GET' else '连接中断，写入结果待确认，请先核验', uncertain=method != 'GET')
        if response.status_code in (401, 403):
            raise RemoteError('登录已失效或没有操作权限，请重新登录', status=401)
        if len(response.content) > 20_000_000:
            raise RemoteError('禅道响应过大，请缩小查询范围', uncertain=method != 'GET')
        try:
            data = response.json()
        except ValueError:
            raise RemoteError('禅道未返回 JSON，请核对连接地址及接口权限', uncertain=method != 'GET')
        if not isinstance(data, dict):
            raise RemoteError('禅道响应格式错误', uncertain=method != 'GET')
        if response.is_error or data.get('result') == 'fail' or data.get('status') == 'fail' or data.get('error'):
            message = plain(data.get('message', data.get('error', '禅道操作失败')))
            raise RemoteError(message[:300], uncertain=method != 'GET' and response.status_code >= 500)
        return data

    async def login(self, password):
        data = await self.request('POST', 'api.php/v1/tokens', json={'account': self.account, 'password': password})
        token = data.get('token')
        if not token:
            raise RemoteError('登录失败，未获得会话 Token')
        self.client.headers['Token'] = token
        self.client.cookies.set('zentaosid', token)

    async def paged(self, kind, path=None, **params):
        result, seen = [], set()
        for page in range(1, 1001):
            data = await self.request('GET', path or f'api.php/v1/{kind}', params={**params, 'page': page, 'limit': 500})
            chunk = rows_of(data.get(kind, []))
            if not chunk:
                if len(result) < int(data.get('total', len(result))):
                    raise RemoteError('禅道分页数据不完整，请重新刷新')
                return result
            new_ids = {int(x['id']) for x in chunk}
            if new_ids & seen:
                raise RemoteError('禅道分页发生重复，请重试以避免统计不完整')
            seen |= new_ids
            result.extend(chunk)
            if len(result) >= int(data.get('total', len(result))):
                return result
        raise RemoteError('禅道数据量超过本次读取上限')

    async def projects(self, status='undone'):
        # ZenTao's "未完成" scope is wait/doing, intersected with "我参与的".
        return [{'id': int(x['id']), 'name': plain(x['name']), 'status': x.get('status', '')} for x in await self.paged('projects', status=status, involved=1)]

    async def tasks(self):
        data = await self.paged('tasks', search=1)
        return [self.task_summary(t) for t in data]

    def task_summary(self, task):
        return {'id': int(task['id']), 'name': plain(task['name']), 'project_id': number_id(task.get('project')), 'execution_id': number_id(task.get('execution')), 'status': task.get('status', ''), 'left': float(task.get('left') or 0), 'consumed': float(task.get('consumed') or 0), 'lastEditedDate': str(task.get('lastEditedDate') or ''), 'estStarted': str(task.get('estStarted') or '')[:10], 'deadline': str(task.get('deadline') or '')[:10]}

    async def task(self, task_id):
        return self.task_summary(await self.request('GET', f'api.php/v1/tasks/{task_id}'))

    async def executions(self):
        return [{'id': int(x['id']), 'name': plain(x['name']), 'project_id': number_id(x.get('project'))} for x in await self.paged('executions', status='all')]

    async def efforts(self, task_id):
        data = await self.request('GET', f'api.php/v1/tasks/{task_id}/estimate')
        if 'effort' not in data:
            raise RemoteError('工时接口缺少 effort 字段')
        result = []
        for row in rows_of(data['effort']):
            if account_of(row.get('account')) != self.account or str(row.get('deleted', '0')) not in ('0', 'False', ''):
                continue
            r = {'id': int(row['id']), 'task_id': task_id, 'project_id': number_id(row.get('project')), 'execution_id': number_id(row.get('execution')), 'date': str(row['date'])[:10], 'work': plain(row['work']), 'consumed': float(row['consumed']), 'left': float(row.get('left') or 0), 'account': self.account}
            r['signature'] = signature(r)
            result.append(r)
        return result

    async def create(self, entry):
        payload = {k: [v] for k, v in entry.model_dump(mode='json').items() if k != 'task_id'}
        await self.request('POST', f'api.php/v1/tasks/{entry.task_id}/estimate', json=payload)

    async def edit(self, effort_id, entry):
        # 21.4 exposes editEffort as a web JSON controller, not a REST PUT route.
        path = f'task-editEffort-{effort_id}.json'
        before = await self.request('GET', path)
        form = before.get('data', {})
        if isinstance(form, str):
            try:
                form = json.loads(form)
            except ValueError:
                raise RemoteError('当前禅道不支持此修改入口')
        effort = form.get('effort', {}) if isinstance(form, dict) else {}
        if int(effort.get('id', 0)) != effort_id or account_of(effort.get('account')) != self.account or int(effort.get('objectID', 0)) != entry.task_id:
            raise RemoteError('工时归属校验失败，已停止修改')
        payload = {k: v for k, v in entry.model_dump(mode='json').items() if k not in ('task_id', 'expected')}
        result = await self.request('POST', path, data=payload, headers={'X-Requested-With': 'XMLHttpRequest'})
        if result.get('result') != 'success':
            raise RemoteError('修改响应未确认成功，请先核验工时', uncertain=True)
