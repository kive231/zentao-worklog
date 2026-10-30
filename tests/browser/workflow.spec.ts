import { test, expect, Page } from '@playwright/test';

const profile = { id: 'test-connection', name: '演示连接', base_url: 'https://zentao.example.test', account: 'tester' };
const catalog = { projects: [{ id: 1, name: '示例 ERP 项目' }], executions: [{ id: 2, name: '开发', project_id: 1 }], tasks: [{ id: 3, name: '分切页面开发', project_id: 1, execution_id: 2, left: 10, consumed: 0, status: 'doing' }] };
const source = '## 2026-09-01\n- 示例ERP项目 / 分切页面开发 | 分切页面开发 | +2\n## 2026-09-02\n- 示例ERP项目 / 分切页面开发 | 功能自测 | +1.5';
const rows = [{ id: 'a', date: '2026-09-01', work: '分切页面开发', consumed: 2, left: 10, project_hint: '示例', task_hint: '分切页面开发', project_id: 1, task_id: 3, selected: true, original: '- 2026-09-01：分切页面开发（2）' }, { id: 'b', date: '2026-09-02', work: '功能自测', consumed: 1.5, left: 10, project_hint: '示例', task_hint: '分切页面开发', project_id: 1, task_id: 3, selected: true, original: '- 2026-09-02：功能自测（1.5）' }];

async function setup(page: Page, signedIn = true) {
  const captured: { review?: any; commit?: any; writes: any[] } = { writes: [] };
  let loggedIn = signedIn;
  await page.route('**/api/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname, method = req.method();
    let data: any = {}, status = 200;
    if (path === '/api/profiles') data = method === 'GET' ? [profile] : profile;
    else if (path.startsWith('/api/profiles/')) data = profile;
    else if (path === '/api/session') {
      if (method === 'POST') loggedIn = true;
      if (method === 'DELETE') loggedIn = false;
      if (!loggedIn && method === 'GET') { status = 401; data = { detail: '请先登录' }; } else data = { profile };
    } else if (path === '/api/catalog') data = catalog;
    else if (path === '/api/worklogs' && method === 'GET') data = { rows: [], daily: {}, complete: true, sync: { running: false, complete: true, done: 1, total: 1, errors: [], project_id: 0 } };
    else if (path === '/api/worklogs' && method === 'POST') { captured.writes.push(req.postDataJSON()); data = { status: 'success', message: '已写入并回读确认' }; }
    else if (path === '/api/import/parse') data = { rows };
    else if (path === '/api/import/review') {
      captured.review = req.postDataJSON(); const r = captured.review.rows;
      data = { id: 'review-edited', rows: r.map((x: any) => ({ ...x, status: 'ready' })), count: r.length, total: r.reduce((n: number, x: any) => n + x.consumed, 0), daily: { '2026-09-01': r[0].consumed, '2026-09-02': r[1].consumed }, existing: { '2026-09-01': 2 }, existing_complete: true };
    } else if (path === '/api/import/commit') { captured.commit = req.postDataJSON(); data = { running: false, rows: captured.review.rows.map((x: any) => ({ ...x, status: 'success', message: '已写入并回读确认' })) }; }
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
  });
  return captured;
}

test('配置登录，日期与工时紧凑显示，快速录入', async ({ page }) => {
  const captured = await setup(page, false);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '连接你的禅道' })).toBeVisible();
  await page.locator('input[type=password]').fill('not-a-real-password');
  await page.getByRole('button', { name: '连接并登录' }).click();
  await expect(page.getByRole('heading', { name: '我的工时' })).toBeVisible();
  await page.getByLabel('项目', { exact: true }).selectOption('1');
  await page.getByLabel('任务', { exact: true }).selectOption('3');
  await page.getByLabel('工作内容', { exact: true }).fill('前端页面开发');
  await page.getByLabel('耗时', { exact: true }).fill('2');
  await page.screenshot({ path: 'test-results/home.png', fullPage: true });
  await page.getByRole('button', { name: '保存工时' }).click();
  await expect(page.getByRole('status')).toContainText('回读确认');
  expect(captured.writes[0].work).toBe('前端页面开发');
  expect(captured.writes[0].consumed).toBe(2);
});

test('文件导入→修改→批量匹配→逐日核对→提交修改稿', async ({ page }) => {
  const captured = await setup(page);
  await page.goto('/');
  await page.getByRole('button', { name: '批量导入', exact: true }).click();
  await page.locator('input[type=file]').setInputFiles({ name: '9月工作日志.md', mimeType: 'text/markdown', buffer: Buffer.from(source) });
  await expect(page.getByLabel('匹配任务').first()).toHaveValue('3');
  await expect(page.getByLabel('工作内容', { exact: true }).first()).toHaveValue('分切页面开发');
  await page.getByLabel('导入耗时').first().fill('1.5');
  await page.getByRole('button', { name: '批量匹配任务' }).click();
  await page.getByLabel('日志项目', { exact: true }).selectOption('示例');
  await page.getByLabel('目标项目', { exact: true }).selectOption('1');
  await page.getByLabel('已有任务', { exact: true }).selectOption('3');
  await page.getByRole('button', { name: '应用到同组记录' }).click();
  const [downloaded] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: '导出修改稿' }).click()]);
  const stream = await downloaded.createReadStream();
  let exported = '';
  for await (const chunk of stream!) exported += chunk.toString();
  expect(exported).toContain('## 2026-09-01');
  expect(exported).toContain('示例 ERP 项目 / 分切页面开发 | 分切页面开发 | +1.5');
  await page.screenshot({ path: 'test-results/import-edit.png', fullPage: true });
  await page.getByRole('button', { name: '下一步：明细核对' }).click();
  await expect(page.getByRole('button', { name: '确认并提交…' })).toBeVisible();
  expect(captured.review.rows[0].consumed).toBe(1.5);
  await expect(page.getByText('禅道已有 2h + 本次选中 1.5h = 导入后预计 3.5h')).toBeVisible();
  await page.screenshot({ path: 'test-results/import-review.png', fullPage: true });
  await page.getByRole('button', { name: '确认并提交…' }).click();
  await expect(page.getByRole('button', { name: '提交 2 条 · 3h' })).toBeDisabled();
  await page.getByText('已核对目标账号、每日明细和提交总量').click();
  await page.getByRole('button', { name: '提交 2 条 · 3h' }).click();
  await expect(page.getByRole('heading', { name: '本批次处理结果' })).toBeVisible();
  expect(captured.commit).toEqual({ review_id: 'review-edited' });
  await page.screenshot({ path: 'test-results/import-result.png', fullPage: true });
});

test('窄屏登录和首页无横向溢出', async ({ page }) => {
  await setup(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '我的工时' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test('项目数量独立于未读取工时，正文黑色且提示使用主题色', async ({ page }) => {
  await setup(page);
  await page.route('**/api/worklogs?**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ rows: [], daily: {}, complete: false, sync: { running: false, complete: false, done: 0, total: 0, errors: [], project_id: 0 } }) }));
  await page.goto('/');
  await expect(page.getByRole('button', { name: '全部项目 1 个', exact: true })).toBeVisible();
  await expect(page.locator('.summary-number')).toContainText('— 小时');
  await expect(page.locator('.month-summary')).toContainText('工时待读取');
  await expect(page.locator('.sidebar-caption')).toHaveText('我负责或参与的未完成项目');
  await expect(page.locator('.sidebar-caption')).toHaveCSS('color', 'rgb(82, 118, 97)');
  await expect(page.locator('.project-list .project-item')).toHaveCSS('color', 'rgb(0, 0, 0)');
  await expect(page.locator('.calendar-day').first()).toHaveCSS('color', 'rgb(0, 0, 0)');
  await expect(page.getByLabel('工作内容', { exact: true })).toHaveCSS('color', 'rgb(0, 0, 0)');
  await page.screenshot({ path: 'test-results/project-scope-colors.png', fullPage: true });
});

test('挂起项目的历史工时进入日历统计并可查看修改', async ({ page }) => {
  await setup(page);
  await page.route('**/api/worklogs?**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({
    rows: [{ id: 88, task_id: 4, project_id: 8, execution_id: 7, date: '2026-10-08', work: '历史问题排查', consumed: 1.5, left: 0, signature: 'baseline', project_name: '挂起项目', execution_name: '历史执行', task_name: '历史任务' }],
    daily: { '2026-10-08': 1.5 }, history_projects: [{ id: 8, name: '挂起项目' }], complete: true,
    sync: { running: false, complete: true, done: 3, total: 3, errors: [], project_id: 0 },
  }) }));
  await page.goto('/');
  await page.getByRole('button', { name: '2026-10-08 1.5小时', exact: true }).click();
  await expect(page.locator('.summary-number')).toContainText('1.5 小时');
  await expect(page.getByText('历史问题排查', { exact: true })).toBeVisible();
  await expect(page.locator('.table-head')).toHaveText('项目名称任务名称明细内容消耗（小时）操作');
  const record = page.locator('.record');
  await expect(record.locator('.project-cell')).toHaveText('挂起项目');
  await expect(record.locator('.task-cell')).toHaveText('历史任务');
  await expect(record.locator('.detail-cell')).toHaveText('历史问题排查');
  await expect(record.locator('.hours-cell')).toHaveText('1.5');
  await expect(record).not.toContainText('历史执行');
  await page.screenshot({ path: 'test-results/worklog-detail-columns.png', fullPage: true });
  await expect(page.getByRole('button', { name: '挂起项目', exact: true })).toBeVisible();
  expect(await page.getByLabel('项目', { exact: true }).locator('option[value="8"]').count()).toBe(0);
  await page.getByRole('button', { name: '修改', exact: true }).click();
  const modal = page.locator('.edit-modal');
  await expect(modal.getByLabel('项目', { exact: true })).toHaveValue('8');
  await expect(modal.getByLabel('任务', { exact: true })).toHaveValue('4');
});

test('切换月份自动读取对应范围，点击日期不重新同步', async ({ page }) => {
  await setup(page);
  const starts: string[] = [];
  await page.route('**/api/sync?**', async route => {
    starts.push(new URL(route.request().url()).searchParams.get('start') || '');
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ started: false, cached: true }) });
  });
  await page.goto('/');
  await expect.poll(() => starts.length).toBe(1);
  const initial = starts[0];
  await page.getByRole('button', { name: '上个月', exact: true }).click();
  await expect.poll(() => starts.length).toBe(2);
  expect(starts[1]).not.toBe(initial);
  await page.getByRole('button', { name: '下个月', exact: true }).click();
  await expect.poll(() => starts.length).toBe(3);
  expect(starts[2]).toBe(initial);
  await page.locator('.calendar-day').first().click();
  expect(starts.length).toBe(3);
});
