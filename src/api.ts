export type Profile = { id: string; name: string; base_url: string; account: string };
export type Project = { id: number; name: string; status?: string };
export type Execution = { id: number; name: string; project_id: number };
export type Task = { id: number; name: string; project_id: number; execution_id: number; left: number; consumed: number; status: string };
export type Catalog = { projects: Project[]; executions: Execution[]; tasks: Task[] };
export type Row = { id: number; task_id: number; project_id: number; execution_id: number; date: string; work: string; consumed: number; left: number; signature: string; task_name: string; project_name: string; execution_name: string };
export type DraftRow = { id: string; date: string; work: string; consumed: number | null; left: number | null; project_hint: string; task_hint?: string; format_error?: string; project_id: number; task_id: number; selected: boolean; original: string; status?: string; message?: string };
export type Review = { id: string; rows: DraftRow[]; total: number; count: number; daily: Record<string, number>; existing: Record<string, number>; existing_complete: boolean };
export type Result = { rows: DraftRow[]; running: boolean };
export type Sync = { running: boolean; complete: boolean; done: number; total: number; project_id: number; errors: { task_id: number; message: string }[] };
export type Worklogs = { rows: Row[]; daily: Record<string, number>; complete: boolean; sync: Sync; history_projects?: Project[] };
export class ApiError extends Error { constructor(message: string, public status: number, public uncertain = false) { super(message); } }
export async function api<T>(path: string, method = 'GET', data?: unknown, key?: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch('/api' + path, { method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Worklog-Client': '1', ...(key ? { 'Idempotency-Key': key } : {}) }, body: data === undefined ? undefined : JSON.stringify(data) });
  } catch { throw new ApiError(method === 'GET' ? '无法连接本地服务，请检查后端是否启动' : '请求中断，结果可能尚未返回，请先核验后再重试', 0, method !== 'GET'); }
  const result = await response.json();
  if (!response.ok) {
    const detail = result.detail;
    throw new ApiError(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((x: { msg: string }) => x.msg).join('；') : '请求失败', response.status, result.uncertain);
  }
  return result;
}
export function today() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }
export function hours(n: number | null | undefined) { return Number(n || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 }); }
export function monthDays(month: string) { const [y, m] = month.split('-').map(Number); return new Date(y, m, 0).getDate(); }
export function dayLabel(value: string) { const d = new Date(value + 'T12:00:00'); return Number.isNaN(d.valueOf()) ? '日期待补充' : d.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }); }
export function download(name: string, content: string, type = 'text/plain') { const url = URL.createObjectURL(new Blob([content], { type: type + ';charset=utf-8' })); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 500); }
