# 工时簿

基于 React / TypeScript 和 FastAPI 的本地禅道工时工作台，支持日历统计、快速录入、工时修改及 Markdown 批量导入核对。

## 直接使用 Windows 启动包

在 GitHub Releases 下载 `ZenTaoWorklog-v0.1.0-Windows-x64.zip`，完整解压后双击 `Worklog.exe`。自带运行环境，不需要安装 Python 或 Node.js。启动后在网页中配置自己的禅道连接。详见 [Windows 使用说明](WINDOWS使用说明.md)。

此仓库仅含通用示例，不包含用户的连接配置、密码或真实业务数据。

## 运行

Windows / Python 3.11+ / Node.js 20.19+：

```powershell
cd C:\Projects\zentao-worklog
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
npm run build
.\.venv\Scripts\python.exe -m backend
```

打开 http://127.0.0.1:8767 。后端同时提供构建后的前端，不需要同时开启前端开发服务。

开发时保留后端，另一个终端运行 `npm run dev`，访问 http://127.0.0.1:5173。

## 配置与数据

- 首次输入连接名称、禅道根地址、账号和密码。支持新增配置、修改已退出的配置、连接切换和退出登录。
- SQLite 仅存连接名称、地址和账号，默认位于 `%LOCALAPPDATA%\ZenTaoWorklog\profiles.db`。可通过 `WORKLOG_DATA_DIR` 改变目录。
- 记住密码为可选项，仅使用 Windows 凭据管理器。密码、Token 不进入仓库、SQLite 或浏览器存储。
- 项目、执行、任务、工时及导入修改稿只保留在进程/页面内存，关闭或切换连接后需重新读取。可以手动导出修改稿。
- 本服务只绑定本机回环地址，校验 Host、Origin 和请求标记；不应直接开放到公网。

## 使用

1. 登录后按禅道“我参与的”口径加载本人负责或参与的未完成项目（未开始、进行中），录入和导入的执行、任务候选也限制在这些项目中。历史工时读取本人参与的全部状态项目，包含挂起、已完成和关闭项目；有工时的历史项目单独列出，可筛选和修改已有记录。“全部项目”右侧显示项目数量，与工时条数无关。选择项目，点击“读取 / 刷新”；也可选择全部项目。大型禅道首次全量读取较慢，页面显示进度，可停止。尚未读取工时显示“—”，不会用 0 冒充已核对合计。
2. 点击日历按日筛选，再次点击取消。数字用 `+8` 显示当天工时。可切月、搜索、选择日期范围。
3. 新增时选择现有项目、执行、任务并填写内容、耗时、剩余工时。修改已有记录先校验原值是否变化。保存后从禅道回读，未确认成功不会清空表单。
4. 批量导入 `.md` / `.txt` 或粘贴日志。用 `## 2026-09-01` 按天分组，条目格式为 `- 项目完整名称 / 任务完整名称 | 工作内容 | +2`。项目在前、任务在后，匹配时忽略半角、全角空格和其他空白；只在指定项目内精确匹配任务，同名或缺失时等待手动确认。工作内容只去首尾空白，保留正文内部空格。左侧可下载模板，导出修改稿也使用同一格式。旧格式仍可解析，但需要手动指定任务。
5. 右侧按天编辑，可批量将同一日志项目匹配到一个已有任务；单条仍可调整。点击明细查看原文与修改差异。
6. “下一步：明细核对”实时查重，取消重复和无效行的选中。每天展示本次选中工时，只有全量读取完成才显示完整的导入后合计。
7. 确认目标账号和条数后提交服务端冻结的修改稿。提交前再次查重；已提交批次重复点击不会重复写入。
8. 结果按成功、失败、待确认区分。失败可保留草稿修正后重新核对；结果待确认先回读核验，不自动重试。成功条目从重试稿排除。

**剩余工时会影响禅道任务状态，设为 0 可能使任务完成。**不自动创建、修改任务定义，不实现删除工时。

## 接口与兼容性

读取按所选月份进行，同月点击日期只做本地筛选。录入任务按计划时间与月份相交筛选，阶段仅保留这些任务所属阶段；未设置计划日期的任务保留，避免无法录入。月份首次进入时更新目录，返回已进入的月份复用目录缓存。历史统计不按任务计划时间排除记录，而根据最后修改日期排除不可能有该月工时的旧任务；缺少修改日期的任务继续读取，以保留补录记录和挂起项目工时。任务工时和月份覆盖状态只缓存在后端会话内存，退出登录或重启服务后失效。

完整读取过的月份不重复请求禅道。手动刷新先更新任务元数据，仅补读有变化的任务；缺少可靠更新时间的任务仍重新核对。首次目录加载仍需禅道分页接口，因为当前任务接口没有可直接使用的月份参数，不能宣称整个目录请求已经改为服务端按月筛选。

- API 文档：http://127.0.0.1:8767/docs
- REST 登录：`POST /api.php/v1/tokens`
- 工时读取 / 新增：`GET / POST /api.php/v1/tasks/{id}/estimate`，新增字段为数组。
- 工时修改：21.4 的 `task-editEffort-{id}.json` JSON 控制器。先 GET 校验工时归属，再提交表单，并通过 REST 回读。
- 21.4 源码依据：[官方 task/control.php](https://github.com/easysoft/zentaopms/blob/zentaopms_21.4_20250126/module/task/control.php)。远端修改入口读取已联调；真实业务写入未执行，须由用户在页面核对后提交。
- 如果目标部署不支持 PATH_INFO JSON 路由，修改功能会明确报错，不尝试猜测其他写入地址。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm run build
$env:PLAYWRIGHT_CHANNEL='msedge'
npm run test:e2e
```

浏览器测试使用模拟业务数据，不向真实禅道写入。也可不设置 `PLAYWRIGHT_CHANNEL`，先用 `npx playwright install chromium` 安装测试浏览器。

真实接口只读测试需显式设置现有配置路径与任务 ID：

```powershell
$env:WORKLOG_LIVE_CONFIG='你的现有连接配置.json'
$env:WORKLOG_LIVE_TASK='你可读取的任务ID'
.\.venv\Scripts\python.exe -m pytest tests/test_live_readonly.py -q
```

## 目录

- `src/`：React / TypeScript 网页，主工作台与批量导入流程。
- `backend/`：FastAPI、禅道适配器、配置存储与日志解析器。
- `tests/`：后端写入保护、解析查重与浏览器流程测试。
- 本仓库独立于禅道源码；不修改禅道服务端，不包含真实业务凭据。

## 从源码打包 Windows 程序

在 Windows 安装开发依赖并完成 `npm run build` 后：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller==6.22.3
$frontend = (Resolve-Path dist).Path
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed --name Worklog --add-data "$frontend;dist" --collect-all keyring --hidden-import win32ctypes.pywin32.win32cred --hidden-import win32ctypes.pywin32.pywintypes --distpath release --workpath build --specpath build launcher.py
```

发布 `release/Worklog/` 的整个目录。`launcher.py` 是程序启动入口，提供打开工作台和停止服务窗口；命令行参数 `--headless --no-browser --port 18767` 用于不打开浏览器的启动验证。
