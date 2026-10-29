"""Goals persistence, validation, optimistic concurrency and journal: temporary files only."""
import copy
import pathlib
import sys
import tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from competitors import work, journal

GOAL = dict(title='Подготовить осенний тур', why='Выстроить работу с площадками', sphere='biz', status='active',
            start='2026-10-27', deadline='2026-12-31', projects=['project1'],
            krs=[dict(id='k1', title='Подписать договоры', unit='шт.', start=0, target=10, cur=2, auto='')],
            stages=[dict(id='st1', title='Подготовка', due='2026-11-30', steps=[dict(id='s1', t='Звонок', due='', done=False, task='task1')])],
            habits=[dict(id='h1', title='Звонки', per=3, log={'2026-10-26': 2})],
            checkins=[dict(at='2026-10-27', vals={'k1': 2}, conf='ok', note='Идём по плану', next='')])

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    work.FILE = root / 'work.json'
    journal.DIR = root / 'history'
    journal.AREAS['work']['file'] = work.FILE
    assert work.load()['objectives'] == {}
    work.apply_op(dict(op='put', kind='projects', id='project1', data={'title':'Проект'}))
    work.apply_op(dict(op='put', kind='goals', id='monthly1', data={'month':'2026-10','text':'Цель месяца'}))
    before = journal.snapshot('work')
    first = work.apply_op(dict(op='put', kind='objectives', id='goal1', data=GOAL, expected=None))
    assert journal.record('work', before) == 1
    assert first['objectives']['goal1']['stages'][0]['steps'][0]['task'] == 'task1'
    assert first['goals']['monthly1']['text'] == 'Цель месяца'
    record = first['objectives']['goal1']
    changed = copy.deepcopy(GOAL)
    changed['krs'][0]['cur'] = 4
    second = work.apply_op(dict(op='put', kind='objectives', id='goal1', data=changed, expected=record))
    # Retry after lost response succeeds without conflict.
    assert work.apply_op(dict(op='put', kind='objectives', id='goal1', data=changed, expected=record)) == second
    for operation in [dict(op='put', data=GOAL), dict(op='del')]:
        try:
            work.apply_op(dict(kind='objectives', id='goal1', expected=record, **operation))
        except work.WorkError:
            pass
        else:
            raise AssertionError('stale write overwrote a newer record')
    for mutate in [lambda g: g.update(deadline='2026-02-30'), lambda g: g.update(start='2027-01-01'),
                   lambda g: g['krs'][0].update(cur=float('nan')), lambda g: g['krs'][0].update(target=0),
                   lambda g: g['habits'][0].update(per=-1), lambda g: g['stages'][0]['steps'][0].update(id='<script>'),
                   lambda g: g['krs'].append(copy.deepcopy(g['krs'][0]))]:
        bad = copy.deepcopy(GOAL); mutate(bad)
        try:
            work.apply_op(dict(op='put', kind='objectives', id='goal1', data=bad))
        except work.WorkError:
            pass
        else:
            raise AssertionError('invalid goal accepted')
    assert work.load() == second
    work.apply_op(dict(op='put', kind='goalvision', id='vision', data=dict(text='Моё видение', horizon='2029'), expected=None))
    work.apply_op(dict(op='del', kind='objectives', id='goal1', expected=second['objectives']['goal1']))
    assert not work.load()['objectives']
    assert work.load()['goalvision']['vision']['text'] == 'Моё видение'
    assert work.load()['projects']['project1']['title'] == 'Проект'
print('ok: goals, vision, history, validation, conflict protection, retry, existing data preserved')
