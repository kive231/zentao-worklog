"""Persist connection metadata only; passwords live in the OS credential vault."""
import os
import sqlite3
import uuid
from pathlib import Path

import keyring

DATA = Path(os.environ.get('WORKLOG_DATA_DIR', Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'ZenTaoWorklog'))


def connection():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / 'profiles.db')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL, account TEXT NOT NULL)')
    return db


def profiles():
    with connection() as db:
        return [dict(row) for row in db.execute('SELECT * FROM profiles ORDER BY name')]


def get_profile(pid):
    with connection() as db:
        row = db.execute('SELECT * FROM profiles WHERE id=?', (pid,)).fetchone()
    return dict(row) if row else None


def save_profile(profile, pid=None):
    pid = pid or uuid.uuid4().hex
    old = get_profile(pid)
    if old and (old['account'], old['base_url']) != (profile.account, profile.base_url):
        forget_password(pid)
    with connection() as db:
        db.execute('INSERT OR REPLACE INTO profiles VALUES (?,?,?,?)', (pid, profile.name, profile.base_url, profile.account))
    return get_profile(pid)


def delete_profile(pid):
    forget_password(pid)
    with connection() as db:
        db.execute('DELETE FROM profiles WHERE id=?', (pid,))


def vault():
    backend = keyring.get_keyring()
    if os.name != 'nt' or not type(backend).__module__.startswith('keyring.backends.Windows'):
        raise RuntimeError('当前系统没有 Windows 凭据存储，请取消记住密码')
    return backend


def password(pid):
    return vault().get_password('ZenTaoWorklog', pid) or ''


def remember_password(pid, value):
    vault().set_password('ZenTaoWorklog', pid, value)


def forget_password(pid):
    try:
        if password(pid):
            vault().delete_password('ZenTaoWorklog', pid)
    except (RuntimeError, keyring.errors.KeyringError):
        pass
