"""Процессы: схема, сохранение, журнал, обложка и удаление — только временные данные."""
import pathlib
import sys
import tempfile
import base64
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from competitors import work, planning, journal

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    work.FILE, work.MEDIA_DIR = root / 'work.json', root / 'media'
    journal.DIR = root / 'history'
    journal.AREAS['work']['file'] = work.FILE
    def put(kind, oid, rec):
        before = journal.snapshot('work')
        result = work.apply_op(dict(op='put', kind=kind, id=oid, data=rec))
        assert journal.record('work', before) >= 1
        return result[kind][oid]
    data = work.apply_op(dict(op='init', kind='procs', id='defaults'))
    assert len(data['procs']) == 2
    assert work.apply_op(dict(op='init', kind='procs', id='defaults')) == data
    put('projects', 'project1', dict(title='Проект'))
    put('procs', 'proc1', dict(title='Поиск', kind='artists'))
    lead = put('leads', 'lead1', dict(title='Артист', proc='proc1', fee=1200000, cashless=13))
    lead = put('leads', 'lead1', dict(lead, called=True, called_at='2026-10-27', stage='called'))
    assert any('Позвонил: нет → да' in x['text'] for x in lead['log'])
    task = put('tasks', 'task1', dict(text='Подбор', proc='proc1'))
    assert task['proc'] == 'proc1' and not task['project']
    put('notes', 'note1', dict(title='Заметка', proc='proc1'))
    assert planning._validate('lists', dict(title='Артист', work=dict(lead='lead1')))['work']['lead'] == 'lead1'
    data = work.load()
    for kind, rec in [
        ('procs', dict(title='x', kind='unknown')), ('procs', dict(title='x', created='2026-02-30')),
        ('leads', dict(title='x', stage='unknown')), ('leads', dict(title='x', season='summer')),
        ('leads', dict(title='x', next_at='2026-02-30')), ('leads', dict(title='x', fee=-1)),
        ('leads', dict(title='x', cashless=101)), ('leads', dict(title='x', called='yes')),
        ('leads', dict(title='x', task='../bad')), ('leads', dict(title='x', cities=[dict(city='Тула', at='bad')])),
        ('tasks', dict(text='x', proc='proc1', project='project1')),
        ('tasks', dict(text='x', proc='missing')), ('notes', dict(title='x', proc='proc1', project='project1')),
    ]:
        try:
            work._validate(kind, rec, data)
        except work.WorkError:
            pass
        else:
            raise AssertionError((kind, rec))
    image = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n').decode()
    work.apply_op(dict(op='media', kind='procs', id='proc1', what='cover', data=image))
    updated = put('procs', 'proc1', dict(title='Поиск — правка', kind='artists'))
    assert updated['media']['cover'].startswith('proc1-cover.')
    before = journal.snapshot('work')
    data = work.apply_op(dict(op='del', kind='procs', id='proc1'))
    assert journal.record('work', before) == 4
    assert not data['leads']['lead1']['proc'] and not data['tasks']['task1']['proc'] and not data['notes']['note1']['proc']
    assert work.load() == data
    # Рабочая заметка следует за задачей при переносе между процессом и проектом.
    put('procs', 'proc2', dict(title='Даты', kind='venue_dates'))
    moved = put('tasks', 'task2', dict(text='Перенос', proc='proc2'))
    put('notes', 'note2', dict(title='Рабочая', type='work', task='task2', doc={'type':'doc'}))
    assert work.load()['notes']['note2']['proc'] == 'proc2'
    moved = dict(moved, project='project1'); moved.pop('proc', None)
    put('tasks', 'task2', moved)
    assert work.load()['notes']['note2']['project'] == 'project1'
    assert not work.load()['notes']['note2'].get('proc')
print('ok: процессы, воронка, задачи, заметки, связи, журнал, обложка, удаление')
