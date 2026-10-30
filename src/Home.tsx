import { useCallback, useEffect, useRef, useState } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, Cloud, Folder, Plus, RefreshCw, Search, SlidersHorizontal, X } from 'lucide-react';
import { api, ApiError, Catalog, Row, Worklogs, today, hours, monthDays, dayLabel } from './api';
import { ErrorNotice, Spinner } from './App';

const emptyLogs: Worklogs = { rows: [], daily: {}, complete: false, sync: { running: false, complete: false, done: 0, total: 0, errors: [], project_id: 0 } };
export default function Home({ catalog, onDirty, month, onMonthChange, ready }: { catalog: Catalog; onDirty: (dirty: boolean) => void; month: string; onMonthChange: (month: string) => void; ready: boolean }) {
  const [day, setDay] = useState(month === today().slice(0, 7) ? today() : '');
  const [project, setProject] = useState(0);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState(false);
  const [range, setRange] = useState({ start: '', end: '' });
  const [logs, setLogs] = useState<Worklogs>(emptyLogs);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState<Row | null>(null);
  const [tick, setTick] = useState(0);
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    const epoch = ++generation.current;
    try { const data = await api<Worklogs>(`/worklogs?start=${range.start || month + '-01'}&end=${range.end || month + '-' + monthDays(month)}&project_id=${project}`); if (epoch === generation.current) setLogs(data); } catch (e) { setError((e as Error).message); }
  }, [month, project, range.start, range.end]);
  useEffect(() => { void refresh(); }, [refresh, tick]);
  useEffect(() => { if (!logs.sync.running) return; const t = setInterval(() => void refresh(), 1800); return () => clearInterval(t); }, [logs.sync.running, refresh]);
  const sync = useCallback(async (force = true) => { if (!ready) return; setBusy(true); setError(''); try { const state = await api<{started: boolean}>(`/sync?project_id=${project}&start=${range.start || month + '-01'}&end=${range.end || month + '-' + monthDays(month)}&force=${force}`, 'POST'); if (state.started) setLogs(x => ({ ...x, sync: { ...x.sync, running: true } })); await refresh(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }, [ready, project, range.start, range.end, month, refresh]);
  useEffect(() => { if (ready) void sync(false); }, [ready, sync]);
  function changeMonth(offset: number) { const [y, m] = month.split('-').map(Number); const d = new Date(y, m - 1 + offset, 1); const next = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; onMonthChange(next); setDay(''); setRange({ start: '', end: '' }); }
  const filtered = logs.rows.filter(r => (!day || r.date === day) && (!query || `${r.work} ${r.task_name} ${r.project_name}`.toLowerCase().includes(query.toLowerCase())));
  const groups = [...new Set(filtered.map(r => r.date))].sort().reverse();
  const total = filtered.reduce((n, r) => n + r.consumed, 0);
  const hasReadData = logs.complete || logs.rows.length > 0;
  const historyProjects = logs.history_projects || [];
  const days = monthDays(month);
  const offset = (new Date(month + '-01T12:00:00').getDay() + 6) % 7;
  return <main className="workspace">
    <div className="summary-bar"><h1>我的工时</h1><div className="summary-number">{hasReadData ? hours(total) : '—'} <small>小时</small><span>/ {hasReadData ? filtered.length : '—'} 条记录 · {logs.complete ? '当前筛选合计' : '已读取记录，尚非完整合计'}</span></div><div className="search-box"><Search size={15} /><input aria-label="搜索工时" placeholder="搜索工作内容或任务" value={query} onChange={e => setQuery(e.target.value)} /><button className="icon-btn" aria-label="筛选" onClick={() => setFilter(!filter)}><SlidersHorizontal size={15} /></button></div><button disabled={!ready || busy || logs.sync.running} onClick={() => void sync()}><RefreshCw size={14} />{busy ? '启动中' : '读取 / 刷新'}</button></div>
    {filter && <div className="filter-popover panel"><strong>时间范围</strong><div className="actions"><button onClick={() => { setRange({ start: '', end: '' }); setDay(''); }}>本月</button><button onClick={() => { const end = today(); const d = new Date(); d.setDate(d.getDate() - 6); const start = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; setRange({ start, end }); setDay(''); }}>近 7 天</button></div><div className="range-inputs"><input aria-label="开始日期" type="date" value={range.start} onChange={e => { setDay(''); setRange({ ...range, start: e.target.value }); }} /><span>—</span><input aria-label="结束日期" type="date" value={range.end} onChange={e => { setDay(''); setRange({ ...range, end: e.target.value }); }} /></div><button className="primary" onClick={() => setFilter(false)}>完成筛选</button></div>}
    <ErrorNotice error={error} />
    {logs.sync.running && <div className="sync-strip"><Spinner />正在读取工时 {logs.sync.done} / {logs.sync.total || '…'} 个任务，完整读取后再核对合计。<button onClick={async () => { await api('/sync', 'DELETE'); await refresh(); }}>停止读取</button></div>}
    {!!logs.sync.errors.length && <div className="notice warning">{logs.sync.errors.length} 个任务读取失败，统计不完整。{logs.sync.errors[0].message}</div>}
    <div className="work-columns">
      <aside className="sidebar"><div className="calendar-head"><strong>{month.replace('-', ' 年 ')} 月</strong><div><button aria-label="上个月" className="icon-btn" onClick={() => changeMonth(-1)}><ChevronLeft size={17} /></button><button aria-label="下个月" className="icon-btn" onClick={() => changeMonth(1)}><ChevronRight size={17} /></button></div></div><div className="calendar-week">{'一二三四五六日'.split('').map(d => <span key={d}>{d}</span>)}</div><div className="calendar-grid">{Array.from({ length: offset }).map((_, i) => <span key={'pad' + i} />)}{Array.from({ length: days }, (_, i) => { const date = `${month}-${String(i + 1).padStart(2, '0')}`; const amount = logs.daily[date]; return <button key={date} className={`calendar-day ${amount ? 'has-hours' : ''} ${day === date ? 'selected' : ''}`} aria-label={`${date} ${hours(amount)}小时`} onClick={() => { setDay(day === date ? '' : date); setRange({ start: '', end: '' }); }}><span>{i + 1}</span>{amount !== undefined && <small>+{hours(amount)}</small>}</button>; })}</div><p className="calendar-note">＋数字为当日工时 · 点击日期筛选</p><div className="month-summary"><b>{hasReadData ? hours(logs.rows.reduce((n, r) => n + r.consumed, 0)) : '—'} 小时</b><small>{hasReadData ? `${Object.keys(logs.daily).length} 天 · ${logs.rows.length} 条` : '工时待读取'}{!logs.complete && hasReadData && ' · 尚未完整读取'}</small></div><button className={`project-item ${project === 0 ? 'active' : ''}`} onClick={() => setProject(0)}><Folder size={14} /><span>全部项目</span><small>{catalog.projects.length + historyProjects.length} 个</small></button><div className="sidebar-caption">我负责或参与的未完成项目</div><div className="project-list">{catalog.projects.map(p => <button title={p.name} className={`project-item ${project === p.id ? 'active' : ''}`} key={p.id} onClick={() => setProject(p.id)}><span>{p.name}</span></button>)}</div>{historyProjects.length > 0 && <><div className="sidebar-caption">有工时的历史项目（含挂起）</div>{historyProjects.map(p => <button title={p.name} className={`project-item ${project === p.id ? 'active' : ''}`} key={p.id} onClick={() => setProject(p.id)}><span>{p.name}</span></button>)}</>}</aside>
      <section className="work-main"><div className="panel records-panel"><div className="tags">{day && <button className="tag" onClick={() => setDay('')}>{day}<X size={11} /></button>}<span className="tag">{[...catalog.projects, ...historyProjects].find(p => p.id === project)?.name || '全部项目'}</span><button className="text-btn" onClick={() => { setDay(''); setProject(0); setQuery(''); setRange({ start: '', end: '' }); }}>清除筛选</button><span className="spacer" /><span className="small muted">{logs.complete ? '已完整读取' : '等待 / 部分读取'}</span></div><h2>{day ? dayLabel(day) : range.start ? `${range.start} 至 ${range.end || month + '-' + days}` : month.replace('-', ' 年 ') + ' 月'}</h2><p className="subline">{hasReadData ? filtered.length : '—'} 条记录 · 按工作日期统计 · 当前账号</p><div className="table-head worklog-columns"><span>项目名称</span><span>任务名称</span><span>明细内容</span><span className="hours-cell">消耗（小时）</span><span>操作</span></div>
        {!filtered.length && <div className="empty"><CalendarDays size={32} /><h3>{logs.complete ? '这个范围还没有工时' : '先读取禅道工时'}</h3><p>{logs.complete ? '从下方新增一条，或批量导入工作日志。' : '可先选择一个项目快速读取，也可读取全部项目。'}</p>{!logs.complete && <button onClick={() => void sync()} disabled={!ready || busy || logs.sync.running}>读取当前范围</button>}</div>}
        <div className="record-scroll">{groups.map(date => <div key={date}>{!day && <div className="day-divider">{dayLabel(date)} <span>{hours(filtered.filter(r => r.date === date).reduce((n, r) => n + r.consumed, 0))}h</span></div>}{filtered.filter(r => r.date === date).map(r => <div className="record worklog-columns" key={r.id}><span className="project-cell">{r.project_name}</span><span className="task-cell">{r.task_name}</span><span className="detail-cell">{r.work}</span><b className="hours-cell">{hours(r.consumed)}</b><button className="text-btn" onClick={() => setEditing(r)}>修改</button></div>)}</div>)}</div></div>
        <WorklogForm catalog={catalog} date={day || today()} total={logs.daily[day || today()] || 0} complete={logs.complete} onSaved={() => setTick(t => t + 1)} onDirty={onDirty} />
      </section>
    </div>
    {editing && <div className="modal-backdrop"><div className="modal edit-modal"><WorklogForm catalog={catalog} date={editing.date} row={editing} total={logs.daily[editing.date] || 0} complete={logs.complete} onSaved={() => { setEditing(null); setTick(t => t + 1); }} onClose={() => setEditing(null)} onDirty={() => {}} /></div></div>}
  </main>;
}

function WorklogForm({ catalog, date, row, total, complete, onSaved, onClose, onDirty }: { catalog: Catalog; date: string; row?: Row; total: number; complete: boolean; onSaved: () => void; onClose?: () => void; onDirty: (v: boolean) => void }) {
  const [project, setProject] = useState(row?.project_id || 0);
  const [execution, setExecution] = useState(row?.execution_id || 0);
  const [task, setTask] = useState(row?.task_id || 0);
  const [dateValue, setDateValue] = useState(date);
  const [work, setWork] = useState(row?.work || '');
  const [consumed, setConsumed] = useState(row ? String(row.consumed) : '');
  const [left, setLeft] = useState(row ? String(row.left) : '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [unknown, setUnknown] = useState(false);
  const op = useRef(crypto.randomUUID());
  useEffect(() => { if (!row) setDateValue(date); }, [date, row]);
  useEffect(() => { onDirty(!!work); }, [work, onDirty]);
  const tasks = catalog.tasks.filter(t => (!project || t.project_id === project) && (!execution || t.execution_id === execution));
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      const result = await api<{ status: string; message: string }>(row ? `/worklogs/${row.id}` : '/worklogs', row ? 'PUT' : 'POST', { task_id: task, date: dateValue, work, consumed: Number(consumed), left: Number(left), ...(row ? { expected: row.signature } : {}) }, op.current);
      if (result.status === 'success') { setMessage(result.message); setWork(''); setConsumed(''); op.current = crypto.randomUUID(); onDirty(false); onSaved(); }
      else if (result.status === 'unknown') { setUnknown(true); setError(result.message); }
      else { setError(result.message); op.current = crypto.randomUUID(); }
    } catch (e) { const err = e as ApiError; setError(err.message); if (err.uncertain) setUnknown(true); else op.current = crypto.randomUUID(); } finally { setBusy(false); }
  }
  return <form className="panel entry-panel" onSubmit={e => void save(e)}><div className="entry-heading"><h2>{row ? '修改工时' : '新增一条'}</h2><span className="muted">{dateValue} · {row ? '修改后回读确认' : '日期随左侧选择'}</span><span className="spacer" />{onClose ? <button type="button" className="icon-btn" aria-label="关闭修改" onClick={onClose}><X size={18} /></button> : <small className="muted">{busy ? '正在提交' : '未提交'}</small>}</div><ErrorNotice error={error} />{message && <div className="notice success" role="status">{message}</div>}
    {row && <label className="field"><span>日期</span><input type="date" required max={today()} value={dateValue} onChange={e => setDateValue(e.target.value)} /></label>}
    <div className="form-selects"><label className="field"><span>项目</span><select aria-label="项目" disabled={!!row} required value={project || ''} onChange={e => { setProject(Number(e.target.value)); setExecution(0); setTask(0); }}><option value="">选择项目</option>{row && !catalog.projects.some(p => p.id === row.project_id) && <option value={row.project_id}>{row.project_name}</option>}{catalog.projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label className="field execution-field"><span>执行</span><select aria-label="执行" disabled={!!row} value={execution} onChange={e => { setExecution(Number(e.target.value)); setTask(0); }}><option value={0}>全部执行</option>{row && !catalog.executions.some(e => e.id === row.execution_id) && <option value={row.execution_id}>{row.execution_name}</option>}{catalog.executions.filter(e => !project || e.project_id === project).map(e => <option key={e.id} value={e.id}>{e.name}</option>)}</select></label><label className="field"><span>任务</span><select aria-label="任务" required disabled={!!row} value={task || ''} onChange={e => { const t = catalog.tasks.find(t => t.id === Number(e.target.value)); setTask(Number(e.target.value)); if (t) { setProject(t.project_id); setExecution(t.execution_id); setLeft(String(t.left)); } }}><option value="">选择已有任务</option>{row && !catalog.tasks.some(t => t.id === row.task_id) && <option value={row.task_id}>{row.task_name}</option>}{tasks.map(t => <option key={t.id} value={t.id}>#{t.id} {t.name}</option>)}</select></label></div>
    <div className="form-inputs"><label className="field"><span>工作内容</span><input required placeholder="本次完成了什么工作" value={work} onChange={e => setWork(e.target.value)} /></label><label className="field number-field"><span>耗时</span><input aria-label="耗时" type="number" required min="0.01" max="24" step="0.01" value={consumed} onChange={e => setConsumed(e.target.value)} /><small>h</small></label><label className="field number-field"><span>剩余</span><input aria-label="剩余工时" type="number" required min="0" max="99999" step="0.01" value={left} onChange={e => setLeft(e.target.value)} /><small>h</small></label></div>
    <div className="entry-actions"><span className="calculation">{complete && dateValue === date ? `当天 ${hours(total)} ${row ? '− ' + hours(row.consumed) : ''} + 本次 ${hours(Number(consumed))} = ${hours(total - (row?.consumed || 0) + Number(consumed))} 小时` : `本次 ${hours(Number(consumed))}h · 当日总量以完整读取为准`}</span>{unknown ? <button type="button" onClick={async () => { setBusy(true); try { const rows = await api<Row[]>(`/tasks/${task}/worklogs`); const matches = rows.filter(r => r.date === dateValue && r.work === work.trim() && r.consumed === Number(consumed)); if (matches.length === 1) { setUnknown(false); setMessage('已核验到记录'); onSaved(); } else setError('未找到唯一匹配，请到禅道核对。此页面不会自动重试。'); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }} disabled={busy}>核验写入结果</button> : <button className="primary" disabled={busy || !task}>{busy ? <Spinner /> : <Plus size={15} />}{row ? '保存修改' : '保存工时'}</button>}</div><p className="entry-hint">任务由你在禅道维护；剩余工时会影响任务状态，填写 0 可能使任务完成。</p><p className="source-note"><Cloud size={14} />正式记录以禅道回读为准，保存失败时保留输入。</p>
  </form>;
}
