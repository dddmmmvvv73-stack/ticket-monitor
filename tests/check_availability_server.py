"""Проверка доступности и журнала: только временные файлы."""
import copy
from datetime import date, timedelta
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from competitors import availability as av, journal, venuebook
from competitors.storage import save_json

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    av.FILE = root / 'availability.json'
    venuebook.FILE = root / 'venues.json'
    journal.DIR = root / 'history'
    journal.AREAS['availability']['file'] = av.FILE
    save_json(venuebook.FILE, {'rows':[{'id':'v1','name':'Зал проверки','city':'Город проверки'}]})
    today = date.today().isoformat()
    report = dict(venue='v1', month='2027-02', mode='full', asof=today, free=[5,8], busy=[])
    def put(kind, rec, oid=None):
        op = dict(op='put', kind=kind, data=rec)
        if oid:
            op.update(id=oid, expected=copy.deepcopy(av.load()[kind][oid]))
        return av.apply_op(op)
    assert av.load() == {'reports':{},'bookings':{},'requests':{}}
    batch = dict(op='request_batch', kind='requests', venues=['v1'], months=['2027-02','2027-03'], data={'artist':'Артист А'})
    av.apply_op(batch); av.apply_op(batch)
    assert len(av.load()['requests']) == 2
    av.apply_op(dict(batch, data={'artist':'Артист Б'}))
    assert len(av.load()['requests']) == 4
    put('reports', dict(report, mode='partial'))
    assert all(r['status']=='call' for r in av.load()['requests'].values())
    result = put('reports', report)
    assert sum(r['status']=='answered' for r in result['requests'].values()) == 2
    full_id = next(i for i,r in result['reports'].items() if r['mode']=='full')
    result = put('reports', dict(report, free=[8]))
    second_id = next(i for i,r in result['reports'].items() if r['mode']=='full' and i != full_id)
    av.apply_op(dict(op='void',kind='reports',id=full_id,expected=result['reports'][full_id]))
    assert sum(r['status']=='answered' for r in av.load()['requests'].values()) == 2
    av.apply_op(dict(op='void',kind='reports',id=second_id,expected=result['reports'][second_id]))
    assert all(r['status']=='call' for r in av.load()['requests'].values())
    booking = dict(venue='v1',date='2027-02-05',artist='Артист А',status='hold')
    result = put('bookings', booking); bid = next(iter(result['bookings']))
    stale = copy.deepcopy(result['bookings'][bid])
    for invalid in [dict(booking,artist='Артист Б'), dict(booking,date='2027-02-30'), dict(booking,artist=''),
                    dict(booking,until='2027-02-06')]:
        try: put('bookings',invalid)
        except av.AvailabilityError: pass
        else: raise AssertionError('invalid/conflicting booking accepted')
    result = put('bookings',dict(booking,status='confirmed'),bid)
    assert result['bookings'][bid]['confirmation']=='В разговоре'
    try: av.apply_op(dict(op='put',kind='bookings',id=bid,expected=stale,data=booking))
    except av.AvailabilityError: pass
    else: raise AssertionError('stale write accepted')
    put('bookings',dict(booking,status='cancelled'),bid)
    put('bookings',dict(booking,artist='Артист Б'))
    # Возврат старого резерва через журнал не создаёт двойную бронь.
    cancellation = next(e for e in journal.read('availability') if (e.get('after') or {}).get('status')=='cancelled')
    try: journal.restore(cancellation['id'])
    except journal.JournalError: pass
    else: raise AssertionError('journal restore created conflicting bookings')
    for invalid in [dict(report,free=[29]),dict(report,free=[5],busy=[5]),dict(report,mode='partial',free=[],busy=[]),
                    dict(report,asof=(date.today()+timedelta(days=1)).isoformat())]:
        try: put('reports',invalid)
        except av.AvailabilityError: pass
        else: raise AssertionError('invalid report accepted')
    assert len(journal.read('availability')) >= 8
    assert av.FILE.exists()
print('ok: shared answers, batch deduplication, partial replies, void/reopen, booking conflicts, verbal confirmation, stale writes, journal restore')
