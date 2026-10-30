"""Windows desktop entry point; also supports headless packaging verification."""
import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from backend.app import app


def emit(value):
    if sys.stdout is not None:
        print(json.dumps(value, ensure_ascii=True), flush=True)


def bind_socket(port, explicit):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('127.0.0.1', port))
    except OSError:
        if explicit:
            sock.close()
            raise
        sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    return sock


def existing_app(port):
    if not port:
        return False
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as r:
            return json.load(r).get('application') == 'zentao-worklog'
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description='ZenTao Worklog local desktop launcher')
    parser.add_argument('--port', type=int)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        from backend.app import DIST
        from backend.store import vault
        backend = vault()
        assert (DIST / 'index.html').is_file(), 'Missing frontend bundle'
        import tkinter
        emit({'ok': True, 'frontend': True, 'windows_vault': type(backend).__name__, 'tk': tkinter.TkVersion})
        return
    port = args.port if args.port is not None else int(os.environ.get('WORKLOG_PORT', '8767'))
    if not 0 <= port <= 65535:
        raise ValueError('Port must be between 0 and 65535')
    if not args.headless and existing_app(port):
        webbrowser.open(f'http://127.0.0.1:{port}/')
        return
    sock = bind_socket(port, args.port is not None)
    port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}/'
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_config=None, access_log=False))
    if args.headless:
        emit({'url': url, 'application': 'zentao-worklog'})
        try:
            server.run(sockets=[sock])
        finally:
            sock.close()
        return
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.title('工时簿')
    root.geometry('440x238')
    root.resizable(False, False)
    root.configure(bg='#f5f6f3')
    tk.Label(root, text='工时簿', bg='#f5f6f3', fg='#000000', font=('Microsoft YaHei', 22, 'bold')).pack(pady=(22, 6))
    status = tk.StringVar(value='正在启动本地工作台…')
    tk.Label(root, textvariable=status, bg='#f5f6f3', fg='#527661', font=('Microsoft YaHei', 10)).pack(pady=4)
    tk.Label(root, text=url, bg='#f5f6f3', fg='#000000', font=('Segoe UI', 10)).pack(pady=4)
    buttons = tk.Frame(root, bg='#f5f6f3')
    buttons.pack(pady=15)
    open_button = tk.Button(buttons, text='打开工作台', command=lambda: webbrowser.open(url), bg='#dce9dd', fg='#000000', relief='flat', font=('Microsoft YaHei', 10), padx=16, pady=7, state='disabled')
    open_button.pack(side='left', padx=6)
    def close():
        if not messagebox.askokcancel('退出工时簿', '请先确认当前没有正在提交的工时。退出会清空本次登录和未提交草稿。', parent=root):
            return
        server.should_exit = True
        status.set('正在停止服务…')
        open_button.configure(state='disabled')
        def wait_close():
            if thread.is_alive():
                root.after(150, wait_close)
            else:
                sock.close()
                root.destroy()
        wait_close()
    tk.Button(buttons, text='停止并退出', command=close, bg='#ffffff', fg='#000000', relief='flat', font=('Microsoft YaHei', 10), padx=16, pady=7).pack(side='left', padx=6)
    tk.Label(root, text='首次使用请配置自己的禅道地址和账号。', bg='#f5f6f3', fg='#527661', font=('Microsoft YaHei', 9)).pack()
    root.protocol('WM_DELETE_WINDOW', close)
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    started_at = time.monotonic()
    def ready():
        if server.started:
            status.set('服务已启动 · 仅本机可以访问')
            open_button.configure(state='normal')
            if not args.no_browser:
                webbrowser.open(url)
        elif not thread.is_alive() or time.monotonic() - started_at > 30:
            status.set('启动失败，请重新启动或检查端口设置。')
        else:
            root.after(100, ready)
    root.after(100, ready)
    root.mainloop()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if sys.stderr is not None:
            print(f'Launcher failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        if not any(x in sys.argv for x in ('--headless', '--self-test')):
            import tkinter.messagebox
            tkinter.messagebox.showerror('工时簿启动失败', '请确认启动包已完整解压，再重试。\n' + str(exc))
        raise SystemExit(1)
