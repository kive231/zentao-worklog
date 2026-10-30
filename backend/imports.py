import re
import uuid
import unicodedata
from collections import defaultdict

from .models import ImportRow, Worklog


def parse_log(text):
    """Keep every non-heading source line; never invent missing dates or hours."""
    result, project, current_date = [], '', ''
    for line_number, source in enumerate(text.splitlines(), 1):
        line = source.strip().lstrip('\ufeff')
        if not line or line.startswith(('>', '---', '```')):
            continue
        if line.startswith('#'):
            heading = line.lstrip('#').strip()
            match = re.match(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?$', heading)
            if match:
                current_date = '%s-%02d-%02d' % (match[1], int(match[2]), int(match[3]))
            elif line.startswith('##'):
                project = re.sub(r'[（(]本月.*$', '', heading).strip()
            continue
        line = re.sub(r'^[-*•]\s*', '', line)
        date_match = re.match(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?\s*[：:]?\s*', line)
        date = current_date
        if date_match:
            date = '%s-%02d-%02d' % (date_match[1], int(date_match[2]), int(date_match[3]))
            line = line[date_match.end():]
        task_hint, project_hint, format_error = '', project, ''
        structured = '|' in line
        parts = [p.strip() for p in line.split('|')]
        if structured:
            if len(parts) < 3 or parts[0].count('/') != 1:
                format_error = '请按“项目 / 任务 | 工作内容 | +工时”填写'
            else:
                project_hint, task_hint = [p.strip() for p in parts[0].split('/', 1)]
                if not project_hint or not task_hint:
                    format_error = '项目和任务名称不能为空'
                line = parts[-1]
        hours = re.search(r'(?:[（(]\s*(\d+(?:\.\d+)?)\s*(?:h|小时)?\s*[）)]|\+\s*(\d+(?:\.\d+)?)\s*(?:h|小时)?)\s*[✅✔\s]*$', line, re.I)
        consumed = float(hours[1] or hours[2]) if hours else None
        work = '|'.join(parts[1:-1]).strip() if structured and not format_error else line[:hours.start()].strip() if hours else line.strip()
        if structured and not format_error and (not hours or hours.start() != 0):
            format_error = '工时栏请填写 +2 或 +1.5'
        if date_match and not work and hours is None:
            current_date = date
            continue
        result.append(ImportRow(id=uuid.uuid4().hex, date=date, work=work, consumed=consumed, project_hint=project_hint, task_hint=task_hint, format_error=format_error, original=f'第 {line_number} 行：{source}').model_dump())
    return result


def normalize_name(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))


def match_rows(rows, catalog):
    for row in rows:
        row.update(project_id=0, task_id=0, left=None)
        if row.get('format_error'):
            row['message'] = row['format_error']
            continue
        projects = [p for p in catalog['projects'] if normalize_name(p['name']) == normalize_name(row['project_hint'])]
        if len(projects) != 1:
            row['message'] = '项目名称重名，请手动确认' if projects else '未匹配到本人未完成项目，请核对完整名称'
            continue
        row['project_id'] = projects[0]['id']
        if not row['task_hint']:
            row['message'] = '请指定任务名称或手动选择任务'
            continue
        tasks = [t for t in catalog['tasks'] if t['project_id'] == row['project_id'] and normalize_name(t['name']) == normalize_name(row['task_hint'])]
        if len(tasks) != 1:
            row['message'] = '该项目存在同名任务，请手动确认' if tasks else '未匹配到该项目下的任务，请核对完整名称'
            continue
        row.update(task_id=tasks[0]['id'], left=tasks[0]['left'], message='已按项目和任务名称匹配（忽略空格）')
    return rows


def validate_row(row):
    if row.get('format_error'):
        return row['format_error']
    try:
        Worklog(task_id=row['task_id'], date=row['date'], work=row['work'], consumed=row['consumed'], left=row['left'])
        return ''
    except Exception:
        if not row['task_id']:
            return '未匹配任务'
        if row['left'] is None:
            return '请填写剩余工时'
        return '请检查日期、工作内容和工时（耗时 > 0 且 ≤ 24，最多两位小数）'


def daily_totals(rows):
    totals = defaultdict(float)
    for r in rows:
        totals[r['date']] += float(r.get('consumed') or 0)
    return {k: round(v, 2) for k, v in sorted(totals.items())}
