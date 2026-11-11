"""Сохранность базы репертуара, версии, файлы и восстановление. Только временные данные."""
import base64
import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from flask import Flask
from competitors import journal, myprojects as mp, planning, work
from competitors.market_api import bp


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        for module, name in ((mp, 'my_projects'), (planning, 'planning'), (work, 'work')):
            module.FILE = self.root / (name + '.json')
        mp.MEDIA_DIR = self.root / 'media'
        journal.DIR = self.root / 'history'
        journal.AREAS['projects']['file'] = mp.FILE
        journal.AREAS['planning']['file'] = planning.FILE
        app = Flask(__name__)
        app.register_blueprint(bp)
        self.client = app.test_client()

    def create(self, oid='pfirst', title='Марина Девятова'):
        data, _ = mp.apply_op(dict(op='create', manual=True, id=oid, title=title))
        return data['projects'][mp.find(data['projects'], __import__('competitors.curation', fromlist=['project_key']).project_key(title))]

    def profile(self, **fields):
        rec = mp.load()['projects']['pfirst']
        return mp.apply_op(dict(op='profile', id='pfirst', key=rec['keys'][0], expected=rec.get('rev', 0), **fields))[0]['projects']['pfirst']

    def test_manual_card_stays_without_afisha_or_favorite(self):
        first = self.create()
        self.create('psecond', 'Марина Девятова')
        self.assertEqual(len(mp.load()['projects']), 1)
        self.assertTrue(first['saved'])
        self.profile()
        mp.apply_op(dict(op='fav', key=first['keys'][0], fav=False))
        self.assertIn('pfirst', mp.load()['projects'])

    def test_stale_profile_rejected_without_touching_data(self):
        rec = self.create()
        mp.apply_op(dict(op='fee', id='pfirst', fee='300 000 ₽'))
        before = mp.FILE.read_bytes()
        response = self.client.post('/api/market/myprojects', json=dict(op='profile', key=rec['keys'][0], expected=rec['rev'], fee='250 000 ₽'))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(mp.FILE.read_bytes(), before)
        self.assertEqual(self.client.post('/api/market/myprojects', json=dict(op='profile', key=rec['keys'][0])).status_code, 409)

    def test_parallel_independent_changes_all_survive(self):
        for i in range(24):
            self.create('p' + str(i), 'Артист ' + chr(1072+i)*4)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: mp.apply_op(dict(op='fee', id='p' + str(i), fee=str(i + 100))), range(24)))
        self.assertEqual([mp.load()['projects']['p' + str(i)]['profile']['fee'] for i in range(24)], [str(i + 100) for i in range(24)])

    def test_separate_processes_use_the_same_lock(self):
        for i in range(4):
            self.create('p' + str(i), 'Артист ' + chr(1072+i)*4)
        code = 'from pathlib import Path;from competitors import myprojects as m;import sys;m.FILE=Path(sys.argv[1]);m.apply_op(dict(op="fee",id=sys.argv[2],fee=sys.argv[3]))'
        jobs = [subprocess.Popen([sys.executable, '-c', code, str(mp.FILE), 'p' + str(i), str(i + 200)], cwd=pathlib.Path(__file__).resolve().parent.parent) for i in range(4)]
        self.assertEqual([p.wait(timeout=20) for p in jobs], [0] * 4)
        self.assertEqual([mp.load()['projects']['p' + str(i)]['profile']['fee'] for i in range(4)], [str(i + 200) for i in range(4)])

    def test_rename_preserves_ids_aliases_and_site(self):
        old = self.create()
        mp.apply_op(dict(op='site', key=old['keys'][0], url='https://example.org/afisha'))
        new = self.profile(name='Марина Девятова — новая программа', about='Описание', contact='Директор')
        self.assertEqual(mp.find(mp.load()['projects'], old['keys'][0]), 'pfirst')
        self.assertEqual(new['site']['url'], 'https://example.org/afisha')
        self.assertEqual(len(new['keys']), 2)

    def test_profile_preserves_unknown_fields_and_files(self):
        self.create()
        raw = mp.load(); raw['projects']['pfirst']['profile'] = {'future': {'data': 1}}
        mp.save_json(mp.FILE, raw)
        uri = 'data:application/pdf;base64,' + base64.b64encode(b'%PDF-1.4 test').decode()
        mp.apply_op(dict(op='rider', id='pfirst', name='r.pdf', data=uri, rider_kind='technical'))
        new = self.profile(about='Новое описание')
        self.assertEqual(new['profile']['future'], {'data': 1})
        self.assertEqual(new['profile']['riders'][0]['kind'], 'technical')

    def test_file_replacement_and_delete_can_be_restored(self):
        self.create()
        uri = lambda value: 'data:text/plain;base64,' + base64.b64encode(value).decode()
        def post(**op):
            r = self.client.post('/api/market/myprojects', json=dict(id='pfirst', **op))
            self.assertEqual(r.status_code, 200, r.json)
            return r.json['projects']['pfirst']
        a = post(op='rider', name='Бытовой.txt', data=uri(b'old'), rider_kind='hospitality')['profile']['riders'][0]
        b = post(op='rider', name='Бытовой.txt', data=uri(b'new'), replace=a['file'], rider_kind='hospitality')['profile']['riders'][0]
        self.assertEqual(mp.media_file(a['file']).read_bytes(), b'old')
        self.assertNotEqual(a['file'], b['file'])
        post(op='rider-del', file=b['file'])
        restored = journal.restore(journal.read(area='projects', limit=1)[0]['id'])['record']
        self.assertEqual(restored['profile']['riders'][0], b)
        with self.client.get('/api/market/myprojects/media/' + b['file']) as response:
            self.assertEqual(response.data, b'new')

    def test_photo_versions_and_journal_restore(self):
        rec = self.create()
        def photo(data):
            response = self.client.post('/api/market/myprojects', json=dict(op='media', key=rec['keys'][0], kind='avatar', data='data:image/jpeg;base64,' + base64.b64encode(b'\xff\xd8\xff' + data).decode()))
            self.assertEqual(response.status_code, 200)
            return response.json['projects']['pfirst']['media']['avatar'].split('?')[0]
        a, b = photo(b'old'), photo(b'new')
        self.assertNotEqual(a, b)
        self.assertTrue(mp.media_file(a))
        restored = journal.restore(journal.read(area='projects', limit=1)[0]['id'])['record']
        self.assertEqual(restored['media']['avatar'].split('?')[0], a)

    def test_connections_are_explicit_and_preserve_other_fields(self):
        rec = self.create()
        planning.apply_op(dict(op='put', kind='lists', id='list1', data={'title': 'Подбор'}))
        d, _ = mp.apply_op(dict(op='connections', key=rec['keys'][0], kind='lists', target='list1'))
        self.assertEqual(d['projects']['pfirst']['connections'], {'lists': ['list1']})
        d, _ = mp.apply_op(dict(op='connections', key=rec['keys'][0], kind='lists', target='list1', on=False))
        self.assertFalse(d['projects']['pfirst']['connections']['lists'])
        self.assertEqual(d['projects']['pfirst']['title'], rec['title'])
        with self.assertRaises(mp.MyProjectsError):
            mp.apply_op(dict(op='connections', key=rec['keys'][0], kind='lists', target='missing'))

    def test_row_id_repair_preserves_every_value_and_is_idempotent(self):
        rows = [{'id': 'row1', 'city': c, 'avg': i * 100, 'ovr': {'rent': i}} for i, c in enumerate(('Тула', 'Орёл', 'Рязань'), 1)]
        raw = {'tours': {'tour1': {'title': 'Тур', 'rows': rows}}, 'unknown': {'keep': 1}}
        planning.save_json(planning.FILE, raw)
        with self.assertRaises(planning.PlanningError):
            planning._validate('tours', raw['tours']['tour1'])
        self.assertEqual(planning.repair_row_ids(), 2)
        fixed = json.loads(planning.FILE.read_text())
        self.assertEqual(len({r['id'] for r in fixed['tours']['tour1']['rows']}), 3)
        strip = lambda items: [{k: v for k, v in r.items() if k != 'id'} for r in items]
        self.assertEqual(strip(rows), strip(fixed['tours']['tour1']['rows']))
        self.assertEqual(fixed['unknown'], raw['unknown'])
        self.assertEqual(planning.repair_row_ids(), 0)
        self.assertTrue(list((self.root / 'history').glob('planning-before-row-ids-*.json')))

    def test_existing_links_preview_and_migration_preserve_profiles(self):
        self.create()
        self.profile(about='Сохранённое описание', fee='250 000 ₽')
        planning.apply_op(dict(op='put', kind='lists', id='list1', data={'title': 'Весна', 'project': 'Марина Девятова'}))
        planning.apply_op(dict(op='put', kind='projects', id='econ1', data={'title': 'Марина Девятова', 'fee': 123456}))
        planning.apply_op(dict(op='put', kind='tours', id='tour1', data={'title': 'Весна 2027', 'project': 'econ1'}))
        before = mp.FILE.read_bytes()
        self.assertEqual(len(mp.connect_existing()), 2)
        self.assertEqual(before, mp.FILE.read_bytes())
        old = copy.deepcopy(mp.load()['projects']['pfirst'])
        self.assertEqual(len(mp.connect_existing(write=True)), 2)
        new = mp.load()['projects']['pfirst']
        self.assertEqual(new['profile'], old['profile'])
        self.assertEqual(new['connections'], {'lists': ['list1'], 'tours': ['tour1']})
        self.assertFalse(mp.connect_existing(write=True))
        self.assertEqual(planning.load()['projects']['econ1']['fee'], 123456)

    def test_only_one_of_two_stale_forms_can_save(self):
        rec = self.create()
        def save(text):
            try:
                mp.apply_op(dict(op='profile', key=rec['keys'][0], expected=rec['rev'], about=text))
                return 'saved'
            except mp.MyProjectsConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ['Первое окно', 'Второе окно']))
        self.assertCountEqual(results, ['saved', 'conflict'])

    def test_failed_atomic_write_keeps_original_file(self):
        self.create()
        before = mp.FILE.read_bytes()
        with self.assertRaises(TypeError):
            mp.save_json(mp.FILE, {'not_json': object()})
        self.assertEqual(mp.FILE.read_bytes(), before)
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_backups_exclude_transient_files_and_keep_project_data(self):
        import tarfile
        from db import offsite
        config = self.root / 'config'
        config.mkdir()
        (config / 'my_projects.json').write_text('{"projects": {}}')
        (config / 'work.json.lock').write_text('lock')
        (config / 'my_projects.json.unique.tmp').write_text('in progress')
        out = self.root / 'packed.tar.gz'
        with patch.object(offsite, 'ROOT', self.root), patch.object(offsite, 'INCLUDE', ['config']):
            offsite.pack_data(out)
        with tarfile.open(out) as archive:
            self.assertIn('config/my_projects.json', archive.getnames())
            self.assertFalse(any(n.endswith(('.lock', '.tmp')) for n in archive.getnames()))


if __name__ == '__main__':
    unittest.main()
