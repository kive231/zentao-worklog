import asyncio
import json
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import store
from .cache import covered, directory_for_month, might_have_efforts, month_range, version
from .imports import daily_totals, match_rows, parse_log, validate_row
from .models import CommitRequest, EditRequest, Login, ParseRequest, Profile, ReviewRequest, Worklog
from .zentao import RemoteError, ZenTao, duplicate_key


@dataclass
class Session:
    remote: ZenTao
    profile: dict
    touched: float = field(default_factory=time.time)
    catalog: dict = field(default_factory=dict)
    history_catalog: dict = field(default_factory=dict)
    directory_months: set = field(default_factory=set)
    effort_versions: dict = field(default_factory=dict)
    coverages: list = field(default_factory=list)
    efforts: dict = field(default_factory=dict)
    sync: dict = field(default_factory=lambda: {'running': False, 'complete': False, 'done': 0, 'total': 0, 'errors': [], 'project_id': 0})
    job: asyncio.Task | None = None
    reviews: dict = field(default_factory=dict)
    operations: dict = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    catalog_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


sessions: dict[str, Session] = {}


async def dispose(s):
    if s.job and not s.job.done():
        s.job.cancel()
        try:
            await s.job
        except asyncio.CancelledError:
            pass
    await s.remote.close()


@asynccontextmanager
async def lifespan(app):
    yield
    for s in list(sessions.values()):
        await dispose(s)


app = FastAPI(title='工时簿 API', version='0.1.0', lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost'])


@app.middleware('http')
async def protect_local(request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail': '拒绝跨站请求'}, status_code=403)
        if request.headers.get('x-worklog-client') != '1':
            return JSONResponse({'detail': '缺少客户端请求标记'}, status_code=403)
        if int(request.headers.get('content-length', 0)) > 2_000_000:
            return JSONResponse({'detail': '文件过大，最大 1MB 文本'}, status_code=413)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    if request.url.path == '/docs':
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'"
    return response


@app.exception_handler(RemoteError)
async def remote_error(request, exc):
    return JSONResponse({'detail': str(exc), 'uncertain': exc.uncertain}, status_code=exc.status)


def current(request):
    sid = request.cookies.get('worklog_session', '')
    s = sessions.get(sid)
    if not s or time.time() - s.touched > 8 * 3600:
        raise HTTPException(401, '请先登录禅道连接')
    s.touched = time.time()
    return s


async def catalog(s, month=None, refresh=False):
    async with s.catalog_lock:
        if not s.catalog or refresh or (month and month not in s.directory_months):
            previous_versions = {t['id']: version(t) for t in s.history_catalog.get('tasks', [])}
            projects, history_projects, executions, tasks = await asyncio.gather(s.remote.projects(), s.remote.projects(status='all'), s.remote.executions(), s.remote.tasks())
            project_ids = {p['id'] for p in projects}
            s.catalog = {
                'projects': projects,
                'executions': [e for e in executions if e['project_id'] in project_ids],
                'tasks': [t for t in tasks if t['project_id'] in project_ids],
            }
            history_ids = {p['id'] for p in history_projects}
            s.history_catalog = {
                'projects': history_projects,
                'executions': [e for e in executions if e['project_id'] in history_ids],
                'tasks': [t for t in tasks if t['project_id'] in history_ids],
            }
            task_ids = {t['id'] for t in s.history_catalog['tasks']}
            s.efforts = {tid: rows for tid, rows in s.efforts.items() if tid in task_ids}
            for task in s.history_catalog['tasks']:
                if task.get('lastEditedDate') and task.get('consumed') == 0:
                    s.efforts[task['id']] = []
                    s.effort_versions[task['id']] = version(task)
            current_versions = {t['id']: version(t) for t in s.history_catalog['tasks']}
            if current_versions != previous_versions:
                s.coverages.clear()
            if month:
                s.directory_months.add(month)
    return s.catalog


def enrich(s, row):
    cat = s.history_catalog or s.catalog
    task = next((t for t in cat.get('tasks', []) if t['id'] == row['task_id']), {})
    project_id = row.get('project_id') or task.get('project_id', 0)
    execution_id = row.get('execution_id') or task.get('execution_id', 0)
    return {**row, 'project_id': project_id, 'execution_id': execution_id, 'task_name': task.get('name', str(row['task_id'])), 'project_name': next((p['name'] for p in cat.get('projects', []) if p['id'] == project_id), str(project_id)), 'execution_name': next((p['name'] for p in cat.get('executions', []) if p['id'] == execution_id), str(execution_id))}


async def read_efforts(s, task_id):
    rows = await s.remote.efforts(task_id)
    s.efforts[task_id] = rows
    task = next((t for t in s.history_catalog.get('tasks', []) if t['id'] == task_id), None)
    if task:
        s.effort_versions[task_id] = version(task)
    return rows


@app.get('/api/health')
async def health():
    return {'status': 'ok', 'application': 'zentao-worklog', 'version': '0.1.0'}


@app.get('/api/profiles')
async def profiles():
    return store.profiles()


@app.post('/api/profiles')
async def add_profile(body: Profile):
    return store.save_profile(body)


@app.put('/api/profiles/{pid}')
async def update_profile(pid: str, body: Profile):
    if not store.get_profile(pid):
        raise HTTPException(404, '连接不存在')
    if any(s.profile['id'] == pid for s in sessions.values()):
        raise HTTPException(409, '此连接正在使用，请先退出登录再修改')
    return store.save_profile(body, pid)


@app.delete('/api/profiles/{pid}')
async def delete_profile(pid: str):
    if any(s.profile['id'] == pid for s in sessions.values()):
        raise HTTPException(409, '请先退出该连接')
    store.delete_profile(pid)
    return {'ok': True}


@app.post('/api/session')
async def login(body: Login, request: Request, response: Response):
    profile = store.get_profile(body.profile_id)
    if not profile:
        raise HTTPException(404, '连接不存在')
    try:
        password = body.password or store.password(body.profile_id)
        if not password:
            raise HTTPException(400, '请输入密码')
        remote = ZenTao(profile)
        try:
            await remote.login(password)
            if body.remember:
                store.remember_password(body.profile_id, password)
        except Exception:
            await remote.close()
            raise
    except (RuntimeError, store.keyring.errors.KeyringError) as exc:
        raise HTTPException(400, str(exc))
    old_id = request.cookies.get('worklog_session')
    if old_id in sessions:
        old = sessions[old_id]
        if old.lock.locked():
            await remote.close()
            raise HTTPException(409, '正在提交工时，请等待结果后切换')
        await dispose(sessions.pop(old_id))
    for sid in list(sessions):
        if time.time() - sessions[sid].touched > 8 * 3600:
            await dispose(sessions.pop(sid))
    sid = secrets.token_urlsafe(32)
    sessions[sid] = Session(remote, profile)
    response.set_cookie('worklog_session', sid, httponly=True, samesite='strict', max_age=8 * 3600)
    return {'profile': profile}


@app.get('/api/session')
async def session(request: Request):
    return {'profile': current(request).profile}


@app.delete('/api/session')
async def logout(request: Request, response: Response):
    sid = request.cookies.get('worklog_session', '')
    s = sessions.get(sid)
    if s:
        if s.lock.locked():
            raise HTTPException(409, '正在提交，请等待结果后退出')
        await dispose(sessions.pop(sid))
    response.delete_cookie('worklog_session')
    return {'ok': True}


@app.get('/api/catalog')
async def get_catalog(request: Request, refresh: bool = False, month: str | None = None):
    s = current(request)
    if month:
        try:
            month_range(month)
        except ValueError:
            raise HTTPException(400, '月份格式应为 YYYY-MM')
        if s.job and not s.job.done() and s.sync.get('start', '')[:7] != month:
            s.job.cancel()
            try:
                await s.job
            except asyncio.CancelledError:
                pass
    if refresh:
        if s.sync['running']:
            raise HTTPException(409, '正在读取工时，完成或停止后再刷新任务目录')
    return directory_for_month(await catalog(s, month, refresh), month)


async def sync_efforts(s, project_id, start='', end='', force=False):
    s.sync = {'running': True, 'complete': False, 'done': 0, 'total': 0, 'errors': [], 'project_id': project_id, 'start': start, 'end': end, 'cached': 0}
    try:
        await catalog(s)
        tasks = [t for t in s.history_catalog['tasks'] if (not project_id or t['project_id'] == project_id) and might_have_efforts(t, start)]
        s.sync['total'] = len(tasks)
        # Bounded workers keep upstream load and memory predictable for large installations.
        queue = asyncio.Queue()
        for task in tasks:
            queue.put_nowait(task)
        async def worker():
            while not queue.empty():
                task = queue.get_nowait()
                try:
                    if not force and task.get('lastEditedDate') and task['id'] in s.efforts and s.effort_versions.get(task['id']) == version(task):
                        s.sync['cached'] += 1
                    else:
                        await read_efforts(s, task['id'])
                except RemoteError as exc:
                    s.sync['errors'].append({'task_id': task['id'], 'message': str(exc)})
                finally:
                    s.sync['done'] += 1
        await asyncio.gather(*(worker() for _ in range(4)))
        s.sync['complete'] = not s.sync['errors']
        if s.sync['complete']:
            s.coverages.append({'project_id': project_id, 'start': start, 'end': end})
    except RemoteError as exc:
        s.sync['errors'].append({'task_id': 0, 'message': str(exc)})
    finally:
        s.sync['running'] = False


@app.post('/api/sync')
async def sync(request: Request, project_id: int = 0, start: date | None = None, end: date | None = None, force: bool = False):
    s = current(request)
    if s.lock.locked():
        raise HTTPException(409, '正在提交工时，请完成后再读取')
    if (start is None) != (end is None) or (start and (end < start or (end-start).days > 366)):
        raise HTTPException(400, '请提供一年以内的完整日期范围')
    first, last = (start.isoformat(), end.isoformat()) if start else ('', '')
    if not force and covered(s.coverages, first, last, project_id):
        return {'started': False, 'cached': True}
    if s.job and not s.job.done():
        if not force and (s.sync.get('start', ''), s.sync.get('end', ''), s.sync['project_id']) == (first, last, project_id):
            return {'started': True}
        s.job.cancel()
        try:
            await s.job
        except asyncio.CancelledError:
            pass
    if force:
        await catalog(s, refresh=True)
    s.sync['running'] = True
    s.job = asyncio.create_task(sync_efforts(s, project_id, first, last))
    return {'started': True}


@app.delete('/api/sync')
async def cancel_sync(request: Request):
    s = current(request)
    if s.job and not s.job.done():
        s.job.cancel()
        try:
            await s.job
        except asyncio.CancelledError:
            pass
    s.sync.update(running=False, complete=False)
    return s.sync


@app.get('/api/worklogs')
async def worklogs(request: Request, start: date, end: date, project_id: int = 0):
    if end < start or (end - start).days > 366:
        raise HTTPException(400, '查询范围应在一年以内')
    s = current(request)
    monthly = [r for group in s.efforts.values() for r in group if start.isoformat() <= r['date'] <= end.isoformat()]
    rows = [enrich(s, r) for r in monthly if not project_id or r['project_id'] == project_id]
    active_ids = {p['id'] for p in s.catalog.get('projects', [])}
    recorded_ids = {r['project_id'] for r in monthly}
    history_projects = [p for p in s.history_catalog.get('projects', []) if p['id'] in recorded_ids and p['id'] not in active_ids]
    return {'rows': sorted(rows, key=lambda r: (r['date'], r['id']), reverse=True), 'daily': daily_totals(rows), 'sync': s.sync, 'complete': covered(s.coverages, start.isoformat(), end.isoformat(), project_id), 'history_projects': history_projects}


@app.get('/api/tasks/{tid}/worklogs')
async def task_worklogs(tid: int, request: Request):
    s = current(request)
    return [enrich(s, x) for x in await read_efforts(s, tid)]


async def write_entry(s, body, effort_id=None):
    before = await read_efforts(s, body.task_id)
    old = next((r for r in before if r['id'] == effort_id), None)
    if effort_id and (not old or old['signature'] != body.expected):
        raise HTTPException(409, '此工时已被修改或已不存在，请刷新后重新编辑')
    key = duplicate_key(body.model_dump(mode='json'))
    if any(duplicate_key(r) == key and r['id'] != effort_id for r in before):
        raise HTTPException(409, '禅道已有相同工时记录，未重复写入')
    uncertain = False
    try:
        if effort_id:
            await s.remote.edit(effort_id, body)
        else:
            await s.remote.create(body)
    except RemoteError as exc:
        if not exc.uncertain:
            return {'status': 'failed', 'message': str(exc)}
        uncertain = True
    try:
        after = await read_efforts(s, body.task_id)
        match = next((r for r in after if duplicate_key(r) == key and (r['id'] == effort_id if effort_id else r['id'] not in {x['id'] for x in before})), None)
        if match and abs(match['left'] - float(body.left)) < .001:
            return {'status': 'success', 'message': '已写入并从禅道回读确认', 'row': enrich(s, match)}
    except RemoteError:
        pass
    return {'status': 'unknown', 'message': '写入结果待确认，请先刷新或核验，勿再次提交', 'uncertain': uncertain}


async def single_write(request, body, effort_id=None):
    s = current(request)
    key = request.headers.get('idempotency-key', '')
    if not 8 <= len(key) <= 100:
        raise HTTPException(400, '缺少有效操作编号')
    fingerprint = json.dumps({'effort_id': effort_id, **body.model_dump(mode='json')}, sort_keys=True)
    async with s.lock:
        if key in s.operations:
            saved = s.operations[key]
            if saved['fingerprint'] != fingerprint:
                raise HTTPException(409, '操作编号已用于其他数据')
            return saved['result']
        result = await write_entry(s, body, effort_id)
        s.operations[key] = {'fingerprint': fingerprint, 'result': result}
        return result


@app.post('/api/worklogs')
async def add_worklog(body: Worklog, request: Request):
    return await single_write(request, body)


@app.put('/api/worklogs/{eid}')
async def edit_worklog(eid: int, body: EditRequest, request: Request):
    return await single_write(request, body, eid)


@app.post('/api/import/parse')
async def parse(body: ParseRequest, request: Request):
    s = current(request)
    rows = parse_log(body.text)
    if len(rows) > 1000:
        raise HTTPException(400, '单次最多导入 1000 条，请拆分文件')
    rows = match_rows(rows, await catalog(s))
    return {'filename': body.filename, 'rows': rows, 'daily': daily_totals(rows)}


@app.post('/api/import/review')
async def review(body: ReviewRequest, request: Request):
    s = current(request)
    rows = [r.model_dump() for r in body.rows]
    if len({r['id'] for r in rows}) != len(rows):
        raise HTTPException(400, '导入行编号重复')
    cat = await catalog(s)
    tasks = {t['id']: t for t in cat['tasks']}
    for row in rows:
        if row['task_id'] in tasks:
            row['project_id'] = tasks[row['task_id']]['project_id']
        elif row['task_id']:
            row['task_id'] = 0
    task_ids = {r['task_id'] for r in rows if r['selected'] and not validate_row(r)}
    remote_keys = set()
    for tid in task_ids:
        remote_keys.update(duplicate_key(r) for r in await read_efforts(s, tid))
    seen = set()
    for row in rows:
        error = validate_row(row)
        row['status'], row['message'] = ('invalid', error) if error else ('ready', '可导入')
        if not error:
            key = duplicate_key(row)
            if key in remote_keys or key in seen:
                row.update(status='duplicate', message='禅道或本批次已存在相同记录')
            elif row['selected']:
                seen.add(key)
        if row['status'] != 'ready':
            row['selected'] = False
    selected = [r for r in rows if r['selected'] and r['status'] == 'ready']
    rid = secrets.token_urlsafe(20)
    # Reviewed snapshots are immutable; the client sends only this ID on commit.
    existing_complete = bool(selected) and all(covered(s.coverages, r['date'], r['date'], 0) for r in selected)
    snapshot = {'id': rid, 'rows': rows, 'total': round(sum(r['consumed'] for r in selected), 2), 'count': len(selected), 'daily': daily_totals(selected), 'existing': daily_totals([r for group in s.efforts.values() for r in group]), 'existing_complete': existing_complete, 'created': time.time(), 'result': None}
    s.reviews = {k: v for k, v in s.reviews.items() if time.time() - v['created'] < 3600}
    s.reviews[rid] = snapshot
    return snapshot


@app.post('/api/import/commit')
async def commit(body: CommitRequest, request: Request):
    s = current(request)
    async with s.lock:
        review = s.reviews.get(body.review_id)
        if not review:
            raise HTTPException(404, '核对稿不存在，请重新核对')
        if review['result'] is not None:
            return review['result']
        if time.time() - review['created'] > 1800:
            raise HTTPException(409, '核对稿已超过 30 分钟，请重新核对')
        selected = [r for r in review['rows'] if r['selected'] and r['status'] == 'ready']
        if not selected:
            raise HTTPException(400, '没有可提交的记录')
        existing = set()
        for tid in {r['task_id'] for r in selected}:
            existing.update(duplicate_key(r) for r in await read_efforts(s, tid))
        if any(duplicate_key(r) in existing for r in selected):
            raise HTTPException(409, '禅道记录已变化，发现新增重复，请返回重新核对')
        results = []
        review['result'] = {'rows': results, 'running': True}
        for row in sorted(selected, key=lambda r: (r['date'], r['id'])):
            try:
                entry = Worklog(**{k: row[k] for k in ('task_id', 'date', 'work', 'consumed', 'left')})
                result = await write_entry(s, entry)
            except (RemoteError, HTTPException) as exc:
                result = {'status': 'failed', 'message': getattr(exc, 'detail', str(exc))}
            results.append({**row, **result})
        review['result']['running'] = False
        return review['result']


@app.get('/api/import/results/{rid}')
async def results(rid: str, request: Request):
    item = current(request).reviews.get(rid)
    if not item:
        raise HTTPException(404, '此批次已失效')
    return item['result'] or {'rows': [], 'running': False}


@app.post('/api/import/reconcile/{rid}')
async def reconcile(rid: str, request: Request):
    s = current(request)
    async with s.lock:
        item = s.reviews.get(rid)
        if not item or not item['result']:
            raise HTTPException(404, '未找到提交结果')
        for row in item['result']['rows']:
            if row['status'] != 'unknown':
                continue
            remote = await read_efforts(s, row['task_id'])
            found = [r for r in remote if duplicate_key(r) == duplicate_key(row)]
            if len(found) == 1:
                row.update(status='success', message='已在禅道核验到唯一匹配记录')
            else:
                row['message'] = '未找到唯一匹配记录，请到禅道核对；不会自动重试'
        return item['result']


DIST = Path(__file__).resolve().parent.parent / 'dist'
if DIST.is_dir():
    app.mount('/assets', StaticFiles(directory=DIST / 'assets'), name='assets')


@app.get('/')
async def index():
    if (DIST / 'index.html').is_file():
        return FileResponse(DIST / 'index.html')
    return JSONResponse({'message': '前端尚未构建，请运行 npm run build；开发模式运行 npm run dev'})
