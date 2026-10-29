"""Воронка v2 (PROCESSES_PLAN.md, раздел 10): этапы, отказ с причиной, перенос записей, задачи записи, ответ коллектива,
связь с «Репертуаром» (карточка, гонорар, райдеры) — только временные данные. python3 tests/check_processes_v2_server.py"""
import base64
import json
import pathlib
import sys
import tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from competitors import work, planning, journal, myprojects


def fails(fn, *a):
    try:
        fn(*a)
    except (work.WorkError, myprojects.MyProjectsError):
        return True
    return False


with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    work.FILE, work.MEDIA_DIR = root / 'work.json', root / 'media'
    myprojects.FILE, myprojects.MEDIA_DIR = root / 'my_projects.json', root / 'project_media'
    journal.DIR = root / 'history'
    journal.AREAS['work']['file'] = work.FILE
    put = lambda kind, oid, rec: work.apply_op(dict(op='put', kind=kind, id=oid, data=rec))[kind][oid]

    # перенос: «Решение» → «Согласование», причина отказа из «Следующего шага», задача знает свою запись
    work.FILE.write_text(json.dumps({'procs': {'procartists': {'title': 'Поиск', 'kind': 'artists'}},
        'tasks': {'task1': {'text': 'Подбор городов: Браво', 'proc': 'procartists'}},
        'leads': {'lead1': {'title': 'Браво', 'proc': 'procartists', 'stage': 'decided', 'task': 'task1'},
                  'lead2': {'title': 'Садко', 'proc': 'procartists', 'stage': 'declined', 'next': 'Работают на эксклюзиве'},
                  'lead3': {'title': 'Иванушки', 'proc': 'procartists', 'stage': 'declined'}}}, ensure_ascii=False))
    d = work.load()
    assert d['leads']['lead1']['stage'] == 'approve' and d['tasks']['task1']['lead'] == 'lead1'
    assert d['leads']['lead2']['why'] == 'Работают на эксклюзиве' and not d['leads']['lead2']['next']
    assert work.load() == d   # перенос повторяется одинаково

    # отказ — только с причиной; старый отказ без причины можно править
    assert fails(put, 'leads', 'lead4', dict(title='Новый', proc='procartists', stage='declined'))
    l4 = put('leads', 'lead4', dict(title='Новый', proc='procartists', stage='called'))
    assert fails(put, 'leads', 'lead4', dict(l4, stage='declined'))
    l4 = put('leads', 'lead4', dict(l4, stage='declined', why='Нет свободных дат'))
    assert any('Причина: — → Нет свободных дат' in x['text'] for x in l4['log']) and any('→ Отказ' in x['text'] for x in l4['log'])
    assert fails(put, 'leads', 'lead4', dict(l4, why=''))   # причину нельзя стереть
    l3 = put('leads', 'lead3', dict(d['leads']['lead3'], contact='Директор'))
    assert l3['stage'] == 'declined' and l3['contact'] == 'Директор'
    assert put('leads', 'lead5', dict(title='Старый клиент', stage='decided'))['stage'] == 'approve'
    for s in ('discuss', 'approve', 'booking', 'reserve'):
        assert put('leads', 'lead5', dict(title='Старый клиент', stage=s, why='позже' if s == 'reserve' else ''))['stage'] == s

    # ответ коллектива: даты этого сезона и следующий сезон
    l1 = put('leads', 'lead1', dict(d['leads']['lead1'], dates=[dict({'from': '2026-11-10', 'to': '2026-11-20', 'note': 'Поволжье'})],
                                  ns=dict(ok=True, months=[3, 10, 10, 9], note='весна')))
    assert l1['dates'][0]['note'] == 'Поволжье' and l1['ns']['months'] == [9, 10, 3] and l1['ns']['ok'] is True
    data = work.load()
    for bad in (dict(dates=[{'from': '2026-11-20', 'to': '2026-11-10'}]), dict(dates=['x']), dict(dates=[{}] * 51),
                dict(ns=dict(months=[6])), dict(ns=dict(ok='yes')), dict(ns='x'), dict(pj='../x')):
        assert fails(work._validate, 'leads', dict(title='x', **bad), data), bad

    # задачи записи: несколько, связь проверяется, при удалении записи снимается
    put('tasks', 'task2', dict(text='Согласовать с руководителем: Браво', proc='procartists', lead='lead1'))
    assert fails(put, 'tasks', 'task3', dict(text='x', proc='procartists', lead='missing'))
    data = work.apply_op(dict(op='del', kind='leads', id='lead1'))
    assert data['tasks']['task2']['lead'] == '' and data['tasks']['task1']['lead'] == ''

    # ответ коллектива по городу — в подборе
    city = planning._validate('lists', dict(title='Браво', cities={'Тула': dict(art='busy', art_org='Иванов-концерт'), 'Орёл': dict(art='ok')}))['cities']
    assert city['Тула'] == {'art': 'busy', 'art_org': 'Иванов-концерт'} and city['Орёл'] == {'art': 'ok'}
    try:
        planning._validate('lists', dict(title='x', cities={'Тула': dict(art='maybe')}))
    except planning.PlanningError:
        pass
    else:
        raise AssertionError('art: неизвестное значение принято')

    # «Репертуар»: карточка для записи, гонорар, райдеры; связанная пустая карточка не удаляется
    mp, _ = myprojects.apply_op(dict(op='create', key='браво группа', title='Группа Браво', id='pbravo1'))
    assert mp['projects']['pbravo1']['title'] == 'Группа Браво'
    assert myprojects.apply_op(dict(op='create', key='браво группа', title='Группа Браво', id='pother'))[0]['projects'].keys() == {'pbravo1'}
    put('leads', 'lead6', dict(title='Группа Браво', proc='procartists', stage='ready', pj='pbravo1', fee=600000))
    mp, _ = myprojects.apply_op(dict(op='fee', id='pbravo1', fee='600 000 ₽'))
    assert mp['projects']['pbravo1']['profile']['fee'] == '600 000 ₽'
    pdf = 'data:application/pdf;base64,' + base64.b64encode(b'%PDF-1.4 rider').decode()
    mp, _ = myprojects.apply_op(dict(op='rider', id='pbravo1', name='Технический райдер.pdf', data=pdf))
    rider = mp['projects']['pbravo1']['profile']['riders'][0]
    assert rider['label'] == 'Технический райдер.pdf' and myprojects.media_file(rider['file']).read_bytes() == b'%PDF-1.4 rider'
    assert fails(myprojects.apply_op, dict(op='rider', id='pbravo1', name='вирус.exe', data=pdf))
    assert fails(myprojects.apply_op, dict(op='rider', id='pbravo1', name='r.pdf', data='data:application/pdf;base64,'))
    # правка профиля на странице проекта (ссылки) не теряет райдеры-файлы
    mp, _ = myprojects.apply_op(dict(op='profile', key='браво группа', fee='700 000', riders=[dict(label='Бытовой', url='https://example.com/r')]))
    riders = mp['projects']['pbravo1']['profile']['riders']
    assert [r.get('url') or r.get('file') for r in riders] == ['https://example.com/r', rider['file']]
    mp, _ = myprojects.apply_op(dict(op='rider-del', id='pbravo1', file=rider['file']))
    assert not myprojects.media_file(rider['file']) and len(mp['projects']['pbravo1']['profile']['riders']) == 1
    mp, _ = myprojects.apply_op(dict(op='profile', key='браво группа'))   # профиль очищен — но карточка связана с воронкой
    assert 'pbravo1' in mp['projects']
    put('leads', 'lead6', dict(work.load()['leads']['lead6'], pj=''))
    mp, _ = myprojects.apply_op(dict(op='profile', key='браво группа'))   # связь снята — пустая карточка удаляется, как раньше
    assert 'pbravo1' not in mp['projects']
    assert fails(myprojects.apply_op, dict(op='fee', id='pmissing', fee='1'))
print('ok: воронка v2 — этапы, отказ с причиной, перенос, даты и сезон, задачи записи, ответ по городам, «Репертуар»')
