"""Permanent exclusions and undo; fixtures only, never user events."""
import copy
import gzip
import json
import pathlib
import sys
import tempfile
import unittest
import threading
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from competitors import review as r, curation, storage, myprojects
from unittest.mock import Mock
from collections import Counter
from datetime import date
from flask import Flask
from competitors.market_api import bp


class ReviewTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        for obj, field, value in [(r,'ROOT',self.root),(r,'FILE',self.root/'config/event_review.json'),
                                  (curation,'FILE',self.root/'config/market_curation.json'),(myprojects,'FILE',self.root/'config/my_projects.json'),(storage,'ON_SERVER',False)]:
            p = patch.object(obj,field,value); p.start(); self.addCleanup(p.stop)
        self.now = 1000.0
        p = patch.object(r.time,'time',lambda:self.now); p.start(); self.addCleanup(p.stop)
        p = patch.object(r,'start_worker'); p.start(); self.addCleanup(p.stop)
        r._cache.clear(); r._cur_cache.clear()
        self.market = self.root/'data/competitors/market/events.json'
        self.direct = self.root/'data/competitors/events.json'
        self.rows = [self.e('Музыкант. Весенняя программа','Тверь','ДК','k:1'),
                     self.e('Музыкант. Весенняя программа','Орел','ДК','k:2'),
                     self.e('Музыкант. Осенняя программа','Тверь','ДК','k:3'),
                     self.e('Гамлет','Тверь','Театр драмы','k:4',fmt='Спектакль'),
                     self.e('Гамлет','Орел','Театр драмы','k:5',fmt='Спектакль')]
        storage.save_json(self.market,self.rows)
        storage.save_json(self.direct,{})
        app=Flask(__name__);app.register_blueprint(bp);self.client=app.test_client()

    def e(self,title,city,venue,k,fmt='Концерт'):
        return dict(title=title,city=city,venue=venue,date='2099-12-01',time='19:00',keys=[k],format=fmt,org='')

    def group(self,title,city=None):
        return next(g for g in r.catalogue() if g['title']==title and (not city or g['events'][0]['city']==city))

    def exclude(self,g,**kw):
        return r.apply(dict(op='exclude',ids=[g['id']],reason='uninteresting',**kw))

    def test_keep_and_project_scope(self):
        g=self.group('Музыкант. Весенняя программа')
        self.assertEqual(len(g['events']),2)
        r.apply(dict(op='keep',ids=[g['id']]))
        self.assertEqual(r.view()['kept'],1)
        op=self.exclude(g)
        self.assertEqual(op['until']-self.now,4)
        self.assertTrue(r.blocked(self.rows[0]));self.assertTrue(r.blocked(self.rows[1]))
        self.assertFalse(r.blocked(self.rows[2]))
        self.assertEqual(len(storage.load_json(self.market,[])),5)
        self.now+=3.999;r.finalize_due()
        self.assertEqual(len(storage.load_json(self.market,[])),5)
        r.apply(dict(op='cancel',id=op['id']))
        self.now+=1;r.finalize_due()
        self.assertFalse(r.blocked(self.rows[0]));self.assertEqual(r.view()['deleted'],[])

    def test_permanent_purge_history_and_no_restore(self):
        d=self.e('Музыкант. Весенняя программа','Тверь','ДК','vk:99')
        storage.save_json(self.direct,{'vk:99':dict(d,uid='vk:99')})
        hist=self.root/'data/competitors/history/vk_99.json'
        seats=self.root/'data/competitors/seats/vk_99.json'
        for p in (hist,seats):storage.save_json(p,{'private':'history'})
        archive=self.root/'data/competitors/market/archive.json'
        storage.save_json(archive,{'k:old':dict(self.rows[0],keys=['k:old'],date='2020-01-01')})
        day=self.root/'data/competitors/market/days/2020-01-01.json'
        storage.save_json(day,{'new':self.rows,'gone':self.rows})
        op=self.exclude(self.group(d['title']))
        self.now+=4;r.finalize_due()
        with self.assertRaises(r.ReviewError):r.apply(dict(op='cancel',id=op['id']))
        self.assertFalse(hist.exists());self.assertFalse(seats.exists())
        self.assertEqual(len(storage.load_json(self.market,[])),3)
        self.assertEqual(storage.load_json(archive,{}),{})
        self.assertEqual(len(storage.load_json(day,{})['new']),3)
        self.assertTrue(r.blocked(dict(d,keys=['k:new'])))
        self.assertEqual(len(r.view()['deleted']),3)
        self.assertNotIn('restore',str(r.load()['deleted']))
        before=copy.deepcopy(r.load()['deleted']);r.finalize_due()
        self.assertEqual(before,r.load()['deleted'])

    def test_homonyms_do_not_cross_venues(self):
        g=self.group('Гамлет','Тверь');self.exclude(g);self.now+=4;r.finalize_due()
        self.assertTrue(r.blocked(self.rows[3]));self.assertFalse(r.blocked(self.rows[4]))
        self.assertTrue(any(e['keys']==['k:5'] for e in storage.load_json(self.market,[])))

    def test_separate_undo_windows_and_restart(self):
        a=self.exclude(self.group('Музыкант. Весенняя программа'));self.now+=1
        b=self.exclude(self.group('Музыкант. Осенняя программа'));self.now+=2
        r.apply(dict(op='cancel',id=a['id']))
        r._cache.clear();self.now+=2;r.finalize_due()
        self.assertEqual(r.load()['operations'][b['id']]['status'],'done')
        self.assertEqual(r.load()['operations'][a['id']]['status'],'cancelled')
        self.assertEqual(len(storage.load_json(self.market,[])),4)

    def test_failure_retry_preserves_minimal_journal(self):
        op=self.exclude(self.group('Музыкант. Весенняя программа'));self.now+=4
        original=r.purge
        def fail(active,remember):
            original(active,remember)
            raise OSError('interrupted after file deletion')
        with patch.object(r,'purge',fail):r.finalize_due()
        self.assertEqual(r.load()['operations'][op['id']]['status'],'error')
        self.now+=31;r.finalize_due()
        self.assertEqual(r.load()['operations'][op['id']]['status'],'done')
        self.assertEqual(len(r.view()['deleted']),2)

    def test_short_program_names_stay_separate(self):
        storage.save_json(self.market,[self.e('Артист. Программа А','Тверь','ДК','k:a'),self.e('Артист. Программа Б','Тверь','ДК','k:b')])
        groups=r.catalogue();self.assertEqual(len(groups),2)
        self.exclude(self.group('Артист. Программа А'))
        self.assertFalse(r.blocked(self.e('Артист. Программа Б','Тверь','ДК','k:b')))

    def test_cancel_during_other_operation_cleanup(self):
        a=self.exclude(self.group('Музыкант. Весенняя программа'));self.now+=1
        b=self.exclude(self.group('Музыкант. Осенняя программа'));self.now+=3
        started,release=threading.Event(),threading.Event()
        original=r.purge
        def slow(active,remember):
            started.set();release.wait(3)
            return original(active,remember)
        with patch.object(r,'purge',slow):
            worker=threading.Thread(target=r.finalize_due);worker.start()
            try:
                self.assertTrue(started.wait(2))
                r.apply(dict(op='cancel',id=b['id']))
            finally:
                release.set();worker.join(3)
        self.assertEqual(r.load()['operations'][b['id']]['status'],'cancelled')
        self.assertEqual(r.load()['operations'][a['id']]['status'],'done')

    def test_artist_is_explicit_and_spans_programs(self):
        lookup={k:(11 if k!='k:3' else 12,'',7) for k in ['k:1','k:2','k:3']}
        with patch.object(r,'registry',return_value=(lookup,{}, {7:'Музыкант'})):
            self.exclude(self.group('Музыкант. Весенняя программа'),scope='artist')
            self.assertTrue(r.blocked(self.rows[2]))
            self.now+=4;r.finalize_due()
        self.assertEqual(len(storage.load_json(self.market,[])),2)

    def test_sales_do_not_request_excluded_keys(self):
        from sales import run,archive
        self.exclude(self.group('Музыкант. Весенняя программа'))
        item=(1,date(2099,12,1),'19:00','Тверь','ДК','kassir','k:1','https://example.invalid',False,{},False,False)
        net,conn,br=Mock(),Mock(),Mock()
        with patch.object(run.store,'pool') as pool:
            run._yandex_job(conn,net,[item],Counter())
            run._kassir_job(conn,net,[(item,'first')],Counter())
            run._qtickets_job(conn,br,[item],Counter())
            pool.assert_not_called();net.time_left.assert_not_called();br.start.assert_not_called()
        with patch.object(archive,'ROOT',self.root):
            self.assertIsNone(archive.save('kassir','kit','k:1',b'sales'))
            self.assertFalse((self.root/'data/raw_sales').exists())

    def test_card_date_snapshots_are_removed_profile_preserved(self):
        title='Музыкант. Весенняя программа'
        path=self.root/'config/my_projects.json'
        storage.save_json(path,{'projects':{'p1':{'title':title,'profile':{'about':'own text'},'snap':{'dates':[['2099-12-01','Тверь','ДК',1000,2000]]}}}})
        self.exclude(self.group(title));self.now+=4;r.finalize_due()
        project=storage.load_json(path,{})['projects']['p1']
        self.assertEqual(project['snap']['dates'],[])
        self.assertEqual(project['profile'],{'about':'own text'})

    def test_known_foreign_production_on_same_stage_is_protected(self):
        a=self.e('Гамлет','Тверь','Театр драмы','k:local',fmt='Спектакль')
        b=dict(a,keys=['k:guest'])
        storage.save_json(self.market,[a,b])
        lookup={'k:local':(41,'venue:1',None),'k:guest':(42,'org:guest',None)}
        with patch.object(r,'registry',return_value=(lookup,{},{})):
            groups=r.catalogue();self.assertEqual(len(groups),2)
            g=next(g for g in groups if g['pid']==41)
            self.exclude(g);self.now+=4;r.finalize_due()
        self.assertEqual(storage.load_json(self.market,[]),[b])

    def test_bulk_validation_and_api(self):
        self.assertEqual(self.client.post('/api/event-review',json={}).status_code,409)
        self.assertEqual(self.client.post('/api/event-review',json=[]).status_code,400)
        ids=[self.group(t)['id'] for t in ['Музыкант. Весенняя программа','Музыкант. Осенняя программа']]
        res=self.client.post('/api/event-review',json=dict(op='exclude',ids=ids,reason='local'))
        self.assertEqual(res.status_code,200)
        self.assertEqual(len(self.client.get('/api/event-review').json['pending']),1)
        self.now+=4;r.finalize_due()
        self.assertEqual(len(r.view()['deleted']),3)
        self.assertEqual(len(storage.load_json(self.market,[])),2)

if __name__=='__main__':unittest.main()
