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

    def test_ticket_link_survives_grouping_and_duplicate_sources(self):
        self.rows[1]['date']='2099-12-02'
        self.rows[1]['url_y']='https://afisha.yandex.ru/orel/concert/example'
        self.rows[2]['url_q']='https://example.qtickets.ru/event/123'
        storage.save_json(self.market,self.rows)
        direct=dict(self.rows[0],uid='vk:link',buy_url='https://tver.kassir.ru/concert/example')
        storage.save_json(self.direct,{'vk:link':direct})
        groups=self.client.get('/api/event-review').json['groups']
        spring=next(g for g in groups if g['title']=='Музыкант. Весенняя программа')
        self.assertEqual(len(spring['events']),2)
        self.assertEqual(spring['ticket'],{'url':direct['buy_url'],'label':'Кассир'})
        autumn=next(g for g in groups if g['title']=='Музыкант. Осенняя программа')
        self.assertEqual(autumn['ticket']['label'],'Qtickets')
        self.assertTrue(any(g['ticket'] is None for g in groups))
        self.assertEqual(r.ticket_link({'url_k':'javascript:alert(1)','url_y':self.rows[1]['url_y']})['label'],'Яндекс Афиша')
        self.assertIsNone(r.ticket_link({'url':'javascript:alert(1)'}))

    def test_conditional_and_compressed_api(self):
        first=self.client.get('/api/event-review',headers={'Accept-Encoding':'gzip'})
        self.assertEqual(first.headers['Content-Encoding'],'gzip')
        value=json.loads(gzip.decompress(first.data))
        self.assertEqual(len(value['groups']),4)
        self.assertNotIn('title',value['groups'][0]['events'][0])
        tag=first.headers['ETag']
        self.assertEqual(self.client.get('/api/event-review',headers={'If-None-Match':tag}).status_code,304)
        r.apply(dict(op='keep',ids=[self.group('Музыкант. Весенняя программа')['id']]))
        fresh=self.client.get('/api/event-review',headers={'If-None-Match':tag})
        self.assertEqual(fresh.status_code,200)
        self.assertNotEqual(fresh.headers['ETag'],tag)

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

    def bulk_groups(self, count):
        rows=[self.e('Массовый проект %d'%i,'Тверь','ДК','k:bulk:%d'%i) for i in range(count)]
        storage.save_json(self.market,self.rows+rows)
        return [g['id'] for g in r.catalogue() if g['title'].startswith('Массовый проект ')]

    def test_large_exclusion_is_one_operation_with_one_undo(self):
        ids=self.bulk_groups(1201)
        for reason in ('local','uninteresting'):
            with self.subTest(reason=reason):
                response=self.client.post('/api/event-review',json={
                    'op':'exclude','ids':ids,'reason':reason,'scope':'project'})
                self.assertEqual(response.status_code,200)
                op=response.json
                state=r.load()['operations'][op['id']]
                self.assertEqual(len(state['rules']),1201)
                self.assertEqual(op['until']-self.now,4)
                self.assertEqual(len(r.view()['pending']),1)
                self.assertEqual(len(r.view()['groups']),4)
                self.now+=3.999
                self.assertEqual(self.client.post('/api/event-review',json={
                    'op':'cancel','id':op['id']}).status_code,200)
                self.now+=1;r.finalize_due()
                self.assertEqual(r.load()['operations'][op['id']]['status'],'cancelled')
                self.assertEqual(len(storage.load_json(self.market,[])),1206)
                self.assertEqual(len(r.view()['groups']),1205)
                self.assertEqual(r.load()['deleted'],[])

    def test_large_exclusion_finishes_without_duplicates_or_unrelated_deletions(self):
        ids=self.bulk_groups(1501)
        response=self.client.post('/api/event-review',json={
            'op':'exclude','ids':ids+ids[:10],'reason':'local'})
        self.assertEqual(response.status_code,200)
        oid=response.json['id']
        self.assertEqual(len(r.load()['operations'][oid]['rules']),1501)
        self.now+=3.999;r.finalize_due()
        self.assertEqual(len(storage.load_json(self.market,[])),1506)
        self.now+=.001
        with patch.object(r,'purge',wraps=r.purge) as purge:
            r.finalize_due()
        self.assertEqual(purge.call_count,1)
        self.assertEqual(r.load()['operations'][oid]['status'],'done')
        self.assertEqual(storage.load_json(self.market,[]),self.rows)
        self.assertEqual(len(r.load()['deleted']),1501)
        self.assertTrue(all(e['reason']=='local' for e in r.load()['deleted']))
        self.assertTrue(r.blocked(self.e('Массовый проект 1500','Орел','Другой ДК','k:new')))
        r.finalize_due()
        self.assertEqual(len(r.load()['deleted']),1501)

    def test_large_exclusion_validates_whole_selection_before_writing(self):
        ids=self.bulk_groups(501)
        before=r.load()
        for invalid in (ids+['missing-project'],ids+[None],[],ids[0]):
            with self.subTest(invalid_type=type(invalid).__name__):
                response=self.client.post('/api/event-review',json={
                    'op':'exclude','ids':invalid,'reason':'uninteresting'})
                self.assertEqual(response.status_code,409)
                self.assertEqual(r.load(),before)
        self.assertEqual(len(storage.load_json(self.market,[])),506)

    def test_due_operations_share_one_purge_and_keep_reasons(self):
        a=self.exclude(self.group('Музыкант. Весенняя программа'))
        b=r.apply(dict(
            op='exclude',ids=[self.group('Музыкант. Осенняя программа')['id']],reason='local'))
        self.now+=4
        with patch.object(r,'purge',wraps=r.purge) as purge:
            r.finalize_due()
        self.assertEqual(purge.call_count,1)
        data=r.load()
        self.assertEqual([data['operations'][x['id']]['status'] for x in (a,b)],['done','done'])
        self.assertEqual({e['reason'] for e in data['deleted'] if 'Осенняя' in e['title']},{'local'})
        self.assertEqual({e['reason'] for e in data['deleted'] if 'Весенняя' in e['title']},{'uninteresting'})

    def test_batched_failure_retry_retains_journal_after_files_removed(self):
        ops=[self.exclude(self.group(t)) for t in ['Музыкант. Весенняя программа','Музыкант. Осенняя программа']]
        self.now+=4;original=r.purge
        def interrupted(active,remember):
            original(active,remember)
            raise OSError('after file cleanup')
        with patch.object(r,'purge',interrupted):r.finalize_due()
        self.assertTrue(all(r.load()['operations'][op['id']]['status']=='error' for op in ops))
        self.now+=31;r.finalize_due()
        self.assertTrue(all(r.load()['operations'][op['id']]['status']=='done' for op in ops))
        self.assertEqual(len(r.load()['deleted']),3)

    def test_unchanged_files_not_rewritten_and_raw_prefix_is_exact(self):
        folder=self.root/'data/competitors/market'
        day=folder/'days/2099-01-01.json';seen=folder/'seen.json'
        storage.save_json(day,{'new':[self.rows[2]],'gone':[]})
        storage.save_json(seen,{'k:3':'2099-01-01'})
        raw=self.root/'data/raw_sales/kassir'
        raw.mkdir(parents=True)
        removed=raw/'k:1_2099-01-01.json.gz';untouched=raw/'k:10_2099-01-01.json.gz'
        removed.write_bytes(b'raw');untouched.write_bytes(b'raw')
        snapshot=self.root/'data/sales_snapshot.json.gz'
        snapshot.write_bytes(gzip.compress(json.dumps({'at':'original','rows':{'k:1':{},'k:3':{'sold':3}},'finals':{}}).encode()))
        before=[p.stat().st_mtime_ns for p in (day,seen)]
        self.exclude(self.group('Музыкант. Весенняя программа'));self.now+=4;r.finalize_due()
        self.assertEqual([p.stat().st_mtime_ns for p in (day,seen)],before)
        self.assertFalse(removed.exists());self.assertTrue(untouched.exists())
        result=json.loads(gzip.decompress(snapshot.read_bytes()))
        self.assertEqual(result['rows'],{'k:3':{'sold':3}});self.assertEqual(result['at'],'original')

    def test_content_version_does_not_change_for_queue_phase(self):
        self.exclude(self.group('Музыкант. Весенняя программа'))
        before=r.view()['content_version']
        data=r.load();next(iter(data['operations'].values()))['status']='applying';r.save(data)
        self.assertEqual(r.view()['content_version'],before)
        self.now+=4;r.finalize_due()
        self.assertNotEqual(r.view()['content_version'],before)

    def test_keep_refresh_only_transfers_decisions_without_building_catalogue(self):
        first=self.client.get('/api/event-review').json
        gid=self.group('Музыкант. Весенняя программа')['id']
        self.assertEqual(self.client.post('/api/event-review',json={'op':'keep','ids':[gid]}).json['ids'],[gid])
        with patch.object(r,'catalogue',side_effect=AssertionError('must not rebuild catalogue')):
            response=self.client.get('/api/event-review',query_string={
                'catalogue_version':first['catalogue_version'],'deleted_count':len(first['deleted'])})
        self.assertEqual(response.status_code,200)
        delta=response.json
        self.assertEqual(delta['kept_ids'],[gid])
        for field in ('groups','rules','deleted'):self.assertNotIn(field,delta)
        self.assertNotEqual(delta['content_version'],first['content_version'])
        self.assertEqual(delta['catalogue_version'],first['catalogue_version'])
        tag=response.headers['ETag']
        self.assertEqual(self.client.get('/api/event-review',headers={'If-None-Match':tag}).status_code,304)

    def test_catalogue_changes_fall_back_to_full_response(self):
        first=self.client.get('/api/event-review').json
        storage.save_json(self.market,self.rows+[self.e('Новый гастрольный проект','Москва','Зал','k:new')])
        changed=self.client.get('/api/event-review',query_string={'catalogue_version':first['catalogue_version']}).json
        self.assertNotEqual(changed['catalogue_version'],first['catalogue_version'])
        self.assertTrue(any(g['title']=='Новый гастрольный проект' for g in changed['groups']))
        self.assertIn('rules',changed);self.assertIn('deleted',changed)

    def test_cached_catalogue_keeps_current_decisions_and_previous_response(self):
        before=r.view();gid=self.group('Музыкант. Весенняя программа')['id']
        r.apply({'op':'keep','ids':[gid]})
        after=r.view()
        self.assertEqual(after['kept'],1)
        self.assertTrue(next(g for g in after['groups'] if g['id']==gid)['kept'])
        self.assertFalse(next(g for g in before['groups'] if g['id']==gid)['kept'])

    def test_s3_delete_uses_batches_and_reports_partial_errors(self):
        import types
        client=Mock();client.delete_objects.return_value={}
        session=Mock();session.client.return_value=client
        boto=types.SimpleNamespace(session=types.SimpleNamespace(Session=Mock(return_value=session)))
        modules={'boto3':boto,'botocore.config':types.SimpleNamespace(Config=Mock())}
        refs=['s3://archive/key%d'%i for i in range(2001)]
        with patch.dict(sys.modules,modules), patch.dict('os.environ',{'S3_KEY_ID':'test','S3_SECRET':'test'}):
            r._delete_raw_many(refs+refs)
            self.assertEqual(client.delete_objects.call_count,3)
            self.assertEqual(sum(len(c.kwargs['Delete']['Objects']) for c in client.delete_objects.call_args_list),2001)
            client.close.assert_called_once()
            client.delete_objects.return_value={'Errors':[{'Code':'AccessDenied'}]}
            with self.assertRaises(RuntimeError):r._delete_raw_many(refs[:1])

    def test_context_applies_even_with_shared_database_project_id(self):
        lookup={k:(41,'',None) for k in ('k:4','k:5')}
        with patch.object(r,'registry',return_value=(lookup,{},{})):
            g=self.group('Гамлет','Тверь');self.exclude(g)
            other=dict(self.rows[4],pid=41,aid=None)
            self.assertFalse(r.blocked(other))
            self.now+=4;r.finalize_due()
        self.assertIn(self.rows[4],storage.load_json(self.market,[]))

    def test_keep_protects_a_version_from_a_global_homonym_rule(self):
        cur=curation.load()
        cur['venues'][curation.venue_key('Орел','Театр драмы')]={'type':'rental'}
        storage.save_json(curation.FILE,cur)
        lookup={k:(41,'',None) for k in ('k:4','k:5')}
        with patch.object(r,'registry',return_value=(lookup,{},{})):
            kept=self.group('Гамлет','Тверь');other=self.group('Гамлет','Орел')
            self.assertEqual(other['context'],{})
            r.apply({'op':'keep','ids':[kept['id']]})
            self.exclude(other);self.now+=4;r.finalize_due()
            self.assertFalse(r.blocked(dict(self.rows[3],pid=41)))
            self.assertFalse(r.blocked_key('k:4'))
            self.assertTrue(r.blocked_key('k:5'))
            self.assertIn(self.rows[3],storage.load_json(self.market,[]))
            self.assertNotIn(self.rows[4],storage.load_json(self.market,[]))
            fresh=dict(self.rows[3],date='2099-12-31',keys=['k:fresh'])
            self.assertFalse(r.blocked(fresh))
            self.assertEqual(r.view()['kept'],1)

    def test_explicit_delete_of_kept_group_can_be_cancelled_and_kept_restored(self):
        g=self.group('Музыкант. Весенняя программа')
        r.apply({'op':'keep','ids':[g['id']]})
        op=self.exclude(g)
        self.assertNotIn(g['id'],r.load()['kept'])
        self.assertTrue(r.blocked(self.rows[0]))
        r.apply({'op':'cancel','id':op['id']})
        self.assertIn(g['id'],r.load()['kept'])
        self.assertTrue(r.load()['kept'][g['id']]['rule'])
        self.assertFalse(r.blocked(self.rows[0]))

    def test_known_different_project_cannot_be_deleted_via_polluted_key(self):
        rule={'kind':'project','pid':1,'keys':['k:other'],'names':[r.key('Гамлет')],
              'context':{},'qualifier':[]}
        self.assertFalse(r.matches(dict(self.rows[3],pid=2,keys=['k:other']),rule))

    def test_artist_exclusion_preserves_explicitly_kept_other_program(self):
        lookup={k:(11 if k!='k:3' else 12,'',7) for k in ['k:1','k:2','k:3']}
        with patch.object(r,'registry',return_value=(lookup,{}, {7:'Музыкант'})):
            kept=self.group('Музыкант. Осенняя программа')
            r.apply({'op':'keep','ids':[kept['id']]})
            self.exclude(self.group('Музыкант. Весенняя программа'),scope='artist')
            self.now+=4;r.finalize_due()
            self.assertIn(self.rows[2],storage.load_json(self.market,[]))
            self.assertFalse(r.blocked_key('k:3'))

if __name__=='__main__':unittest.main()
