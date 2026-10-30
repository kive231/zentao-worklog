import { useCallback, useEffect, useRef, useState } from 'react';
import { Timer, Upload, ChevronDown, LogOut, Settings, Check, X, RefreshCw, Server, ArrowRight, ShieldCheck, LoaderCircle } from 'lucide-react';
import { api, ApiError, Profile, Catalog, today } from './api';
import Home from './Home';
import Importer from './Importer';

export const emptyCatalog: Catalog = { projects: [], executions: [], tasks: [] };
export function ErrorNotice({ error }: { error: string }) { return error ? <div className="notice error" role="alert">{error}</div> : null; }
export function Spinner() { return <LoaderCircle className="spin" size={16} />; }

function Connection({ profiles, onSaved, onLogin, onClose, active }: { profiles: Profile[]; onSaved: () => Promise<void>; onLogin: (p: Profile) => void; onClose?: () => void; active?: Profile }) {
  const [selected, setSelected] = useState(profiles[0]?.id || '');
  const [form, setForm] = useState({ name: '', base_url: '', account: '' });
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { const p = profiles.find(p => p.id === selected); setForm(p || { name: '', base_url: '', account: '' }); setPassword(''); }, [selected, profiles]);
  async function submit(login: boolean) {
    setBusy(true); setError('');
    try {
      let profile = profiles.find(p => p.id === selected);
      if (!profile || ['name', 'base_url', 'account'].some(k => form[k as keyof typeof form] !== profile![k as keyof Profile])) {
        profile = await api<Profile>(selected ? '/profiles/' + selected : '/profiles', selected ? 'PUT' : 'POST', form);
        setSelected(profile.id); await onSaved();
      }
      if (login) { const data = await api<{ profile: Profile }>('/session', 'POST', { profile_id: profile.id, password, remember }); onLogin(data.profile); }
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <section className="connection-form">
    <div className="section-heading"><div><h2>{active ? '连接配置' : '连接你的禅道'}</h2><p>配置一次，随时切换。工时数据保留在禅道。</p></div>{onClose && <button className="icon-btn" aria-label="关闭配置" onClick={onClose}><X /></button>}</div>
    <ErrorNotice error={error} />
    <label className="stack-label">已有连接<select value={selected} onChange={e => setSelected(e.target.value)}><option value="">＋ 新建连接</option>{profiles.map(p => <option key={p.id} value={p.id}>{p.name} · {p.account}</option>)}</select></label>
    <form onSubmit={e => { e.preventDefault(); void submit(true); }}>
      <label className="stack-label">连接名称<input required placeholder="例如：公司禅道" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
      <label className="stack-label">禅道地址<input required type="url" placeholder="https://zentao.example.com/zentao" value={form.base_url} onChange={e => setForm({ ...form, base_url: e.target.value })} /></label>
      <label className="stack-label">登录账号<input required autoComplete="username" value={form.account} onChange={e => setForm({ ...form, account: e.target.value })} /></label>
      <label className="stack-label">密码<input type="password" autoComplete="current-password" placeholder="已记住密码时可留空" value={password} onChange={e => setPassword(e.target.value)} /></label>
      <label className="check-label"><input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} />在 Windows 凭据管理器中记住密码</label>
      {active && <p className="muted">切换连接将清空当前页面草稿。编辑当前连接须先退出登录。</p>}
      <div className="actions"><button type="button" disabled={busy} onClick={() => void submit(false)}>保存配置</button><button className="primary" disabled={busy}>{busy ? <Spinner /> : <ArrowRight size={16} />}连接并登录</button></div>
    </form>
    <div className="connection-foot"><ShieldCheck size={15} />密码不写入 SQLite；登录令牌仅保存在后端内存。</div>
  </section>;
}

export default function App() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [catalog, setCatalog] = useState<Catalog>(emptyCatalog);
  const [month, setMonth] = useState(today().slice(0, 7));
  const [catalogMonth, setCatalogMonth] = useState('');
  const [view, setView] = useState<'home' | 'import'>('home');
  const [settings, setSettings] = useState(false);
  const [loading, setLoading] = useState(true);
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [error, setError] = useState('');
  const [dirty, setDirty] = useState(false);
  const generation = useRef(0);
  const loadProfiles = useCallback(async () => setProfiles(await api<Profile[]>('/profiles')), []);
  useEffect(() => { void Promise.all([loadProfiles().catch(e => setError(e.message)), api<{ profile: Profile }>('/session').then(r => setProfile(r.profile)).catch(e => { if ((e as ApiError).status !== 401) setError(e.message); })]).finally(() => setLoading(false)); }, [loadProfiles]);
  const loadCatalog = useCallback(async (force = false) => {
    const epoch = ++generation.current; setCatalogBusy(true); setError('');
    try { const c = await api<Catalog>(`/catalog?month=${month}&refresh=${force}`); if (epoch === generation.current) { setCatalog(c); setCatalogMonth(month); } } catch (e) { if (epoch === generation.current) setError((e as Error).message); } finally { if (epoch === generation.current) setCatalogBusy(false); }
  }, [month]);
  useEffect(() => { if (profile) void loadCatalog(); }, [profile, loadCatalog]);
  useEffect(() => { const fn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } }; window.addEventListener('beforeunload', fn); return () => window.removeEventListener('beforeunload', fn); }, [dirty]);
  function navigate(next: 'home' | 'import') { if (next !== view && dirty && !window.confirm('当前有未提交的草稿，离开将清空。是否继续？')) return; setDirty(false); setView(next); }
  async function logout() {
    if (dirty && !window.confirm('退出会清空当前未提交草稿，是否继续？')) return;
    try { await api('/session', 'DELETE'); generation.current++; setProfile(null); setCatalog(emptyCatalog); setDirty(false); setSettings(false); } catch (e) { setError((e as Error).message); }
  }
  if (loading) return <main className="boot"><Spinner />正在连接工时簿…</main>;
  if (!profile) return <main className="login-shell"><div className="login-brand"><div className="brand"><Timer size={25} />工时簿</div><div className="brand-copy"><span className="eyebrow">每一天，清晰有数</span><h1>记录工作，<br />把时间理清楚。</h1><p>每日录入、按月核对、批量导入。<br />一个简洁的禅道工时工作台。</p><div className="brand-pills"><span><Check size={14} />数据直连禅道</span><span><Check size={14} />多连接配置</span></div></div><small>LOCAL WORKSPACE · 本地工作台</small></div><div className="login-panel"><ErrorNotice error={error} /><Connection profiles={profiles} onSaved={loadProfiles} onLogin={p => { setProfile(p); setError(''); }} /></div></main>;
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="#" onClick={e => { e.preventDefault(); navigate('home'); }}><Timer size={22} />工时簿</a><nav><button className={view === 'home' ? 'active' : ''} onClick={() => navigate('home')}>我的工时</button><button className={view === 'import' ? 'active' : ''} onClick={() => navigate('import')}>批量导入</button></nav><div className="topbar-right"><span className="connection-dot" /><span className="small muted">禅道直连</span><button className="profile-btn" onClick={() => { if (!dirty || window.confirm('切换连接会清空草稿。打开连接配置？')) setSettings(true); }}><Server size={15} />{profile.name}<ChevronDown size={14} /></button><span className="avatar">{profile.account.slice(0, 1).toUpperCase()}</span><span>{profile.account}</span><button className="icon-btn" aria-label="刷新项目与任务" disabled={catalogBusy} onClick={() => void loadCatalog(true)}><RefreshCw size={16} /></button><button className="icon-btn" aria-label="连接设置" onClick={() => setSettings(true)}><Settings size={16} /></button><button className="icon-btn" aria-label="退出登录" onClick={() => void logout()}><LogOut size={16} /></button></div></header>
    {error && <div className="global-error"><ErrorNotice error={error} /><button onClick={() => void loadCatalog(true)}><RefreshCw size={14} />重试目录</button></div>}
    {catalogBusy && <div className="loading-strip"><Spinner />正在读取项目、执行和任务目录…</div>}
    {view === 'home' ? <Home key={profile.id} catalog={catalog} month={month} onMonthChange={setMonth} ready={!catalogBusy && catalogMonth === month} onDirty={setDirty} /> : <Importer key={profile.id} catalog={catalog} profile={profile} onDirty={setDirty} onHome={() => { setDirty(false); setView('home'); }} />}
    {settings && <div className="modal-backdrop"><div className="modal connection-modal"><Connection profiles={profiles} active={profile} onSaved={loadProfiles} onClose={() => setSettings(false)} onLogin={p => { setProfile(p); setCatalog(emptyCatalog); setSettings(false); setDirty(false); setView('home'); }} /></div></div>}
  </div>;
}
