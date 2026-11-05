"""Новые расходы тура: валидация и сохранение только во временном файле."""
import copy
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from competitors import planning as p

with tempfile.TemporaryDirectory() as tmp:
    p.FILE = Path(tmp) / 'planning.json'
    org = {key: (i + 1) * 100 for i, key in enumerate(p.ORG)}
    assert p.PICK_ORG == p.ORG
    p.apply_op({'op':'put','kind':'cities','id':'Город проверки','data':{'org':org}})
    p.apply_op({'op':'put','kind':'venues','id':'Город проверки|Зал','data':{
        'city':'Город проверки','venue':'Зал','rent':10000,'venue_services':2000}})
    row = {'id':'r1','city':'Город проверки','ovr':dict(org, venue_services=3000),
           'ads':5000,'ad_items':[{}, {'name':'Таргет','amount':1200.5}, {'name':'Афиши','amount':0}],
           'zmode':True,'zones':[{'name':'Первый','seats':100,'price':1500,'fill':70}]}
    tour = {'title':'Тур проверки','rows':[row]}
    p.apply_op({'op':'put','kind':'tours','id':'t1','data':tour})
    saved = p.load()
    assert saved['cities']['Город проверки']['org'] == org
    assert saved['venues']['Город проверки|Зал']['venue_services'] == 2000
    actual = saved['tours']['t1']['rows'][0]
    assert actual['ovr'] == row['ovr'] and actual['ad_items'] == row['ad_items']
    assert actual['zones'] == row['zones']
    # Другая правка тура сохраняет все новые расходы и прежнюю распоясовку.
    changed = copy.deepcopy(saved['tours']['t1']); changed['note'] = 'другая правка'
    p.apply_op({'op':'put','kind':'tours','id':'t1','data':changed})
    assert p.load()['tours']['t1']['rows'][0] == actual
    for items in ['bad', [None], [{'name':'x','amount':-1}], [{'name':'x','amount':True}],
                  [{'name':'x','amount':'100'}], [{'name':'x'*121}], [{}]*41]:
        invalid = copy.deepcopy(tour); invalid['rows'][0]['ad_items'] = items
        try: p.apply_op({'op':'put','kind':'tours','id':'t1','data':invalid})
        except p.PlanningError: pass
        else: raise AssertionError(f'Недопустимые расходы приняты: {items}')
    assert p.load()['tours']['t1']['rows'][0] == actual
    invalid = copy.deepcopy(tour); invalid['rows'][0]['ovr']['venue_services'] = -10
    try: p._validate('tours',invalid)
    except p.PlanningError: pass
    else: raise AssertionError('Отрицательные службы площадки приняты')
print('ok: общие статьи, отдельные службы, реклама, пустая новая строка, повторное сохранение, прежние пояса, проверка ввода')
