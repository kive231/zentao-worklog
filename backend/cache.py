"""Date coverage and conservative task selection for worklog reads."""
import calendar
from datetime import date, datetime, timedelta, timezone


def month_range(month):
    first = date.fromisoformat(month + '-01')
    return first.isoformat(), first.replace(day=calendar.monthrange(first.year, first.month)[1]).isoformat()


def edited_day(task):
    value = task.get('lastEditedDate', '')
    if not value or value.startswith('0000'):
        return ''
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo:
            dt = dt.astimezone(timezone(timedelta(hours=8)))
        return dt.date().isoformat()
    except ValueError:
        return ''


def version(task):
    return (task.get('lastEditedDate', ''), task.get('consumed'), task.get('left'))


def might_have_efforts(task, start):
    # Recording/editing work updates lastEditedDate; effort dates cannot be future dates.
    # Never use the task's planned dates: late/backdated work must remain visible.
    changed = edited_day(task)
    if not changed:
        return True
    if task.get('consumed') == 0:
        return False
    return not start or changed >= start


def directory_for_month(catalog, month):
    if not month:
        return catalog
    start, end = month_range(month)
    def overlaps(task):
        begin, finish = task.get('estStarted', ''), task.get('deadline', '')
        if not begin or begin.startswith('0000') or not finish or finish.startswith('0000'):
            return True
        return begin <= end and finish >= start
    tasks = [t for t in catalog['tasks'] if overlaps(t)]
    ids = {t['execution_id'] for t in tasks}
    return {**catalog, 'tasks': tasks, 'executions': [e for e in catalog['executions'] if e['id'] in ids]}


def covered(coverages, start, end, project_id):
    return any(c['project_id'] in (0, project_id) and
               (not c['start'] or c['start'] <= start) and
               (not c['end'] or c['end'] >= end) for c in coverages)
