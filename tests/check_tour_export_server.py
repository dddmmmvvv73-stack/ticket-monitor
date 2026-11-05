"""Сверка Excel с настоящей JS-моделью; структура, формулы, кэш, API и неверные входы. Только /tmp."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import openpyxl
from flask import Flask
from competitors.tour_export import bp, build_workbook

ROOT = Path(__file__).resolve().parent.parent


def fixture():
    js = r'''
const {PLAN_DEFAULTS,planCalc}=require('./Design/prototype/plan-model.js');
const base={gross:1000000,seats:500,fill:70,fee:100000,cashless:7,per_diem:2000,crew:4,days:2,author:12000,
 moscow:60000,cities:9,rao_on:true,rao:1.5,kassa:5,agent:2,rent:50000,venue_services:1000,ads:30000,logistics:10000,
 org:{services:4000,transfer:7000,hotel:9000},ad_items:[{name:'Радио',amount:8000}],
 cost_items:Object.fromEntries(['variable','project','org','rent','logistics'].map(g=>[g,[{name:'Своя '+g,amount:g==='variable'?2.5:1200}]]))};
const inputs=[base,{...base,fill:0},{...base,gross:0,seats:0},{...base,kassa:100},{...base,rao_on:false},
 {...base,per_diem_sum:0},{...base,per_diem_sum:9999},
 {...base,zones:[{name:'Первый',price:3000,seats:100,fill:50},{name:'Второй',price:1500,seats:50,fill:0}]},
 {...base,zones:[{name:'Первый',price:3000,seats:100},{name:'Второй',price:1500,seats:50}],fill:90}];
console.log(JSON.stringify({version:1,title:'Сверка =SUM(1,2)',project:'Артист',month:'2027-02',scenario:'По строкам',created:'2026-11-05T12:00:00Z',
 cfg:PLAN_DEFAULTS,options:{zones:true},rows:inputs.map((input,i)=>({id:'r'+i,city:i===0?'=1+2':'Город '+i,venue:'Зал '+i,date:'2027-02-12',
 mode:input.zones?'Распоясовка':i===1?'Средняя цена':'Вал',note:'=HYPERLINK("bad")',decision:'В работу',input,calc:planCalc(input)}))}));
'''
    return json.loads(subprocess.check_output(['node', '-e', js], cwd=ROOT, text=True))


class TourExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = fixture()
        cls.content = build_workbook(cls.snapshot)
        cls.cached = openpyxl.load_workbook(io.BytesIO(cls.content), data_only=True)
        cls.formulas = openpyxl.load_workbook(io.BytesIO(cls.content), data_only=False)

    def test_matches_js_for_all_modes_and_costs(self):
        sh = self.cached['Сводка']
        fields = {4:'seats',5:'avg',6:'fillEff',7:'gross',8:'sales',9:'variable',11:'org',13:'logistics',14:'ads',15:'total',
                  16:'profit',17:'ros',18:'beRub',19:'beTickets',20:'beShare',21:'target',22:'tgTickets',23:'cls'}
        import math
        for i, row in enumerate(self.snapshot['rows'], 8):
            calc = row['calc']
            for col, key in fields.items():
                expected = calc[key]
                if key == 'fillEff': expected /= 100
                if key in ('beTickets','tgTickets') and expected is not None: expected = math.ceil(expected)
                actual = sh.cell(i,col).value
                if expected is None:
                    self.assertIn(actual, (None, ''))
                elif isinstance(expected, str): self.assertEqual(actual,expected)
                else: self.assertAlmostEqual(actual,expected,places=6,msg=f'{row["id"]} {key}')
            self.assertAlmostEqual(sh.cell(i,10).value,calc['project']['total'],places=6)
            self.assertAlmostEqual(sh.cell(i,12).value,calc['rent']+calc['venue_services'],places=6)
        self.assertAlmostEqual(sh.cell(17,16).value,sum(r['calc']['profit'] for r in self.snapshot['rows']),places=6)

    def test_workbook_is_editable_and_safe(self):
        self.assertEqual(self.formulas.sheetnames,['Сводка','Подробные сметы'])
        self.assertIn(self.formulas.calculation.calcMode,(None,'auto'))  # отсутствие атрибута — стандартный auto
        self.assertTrue(self.formulas.calculation.fullCalcOnLoad)
        summary=self.formulas['Сводка']; detail=self.formulas['Подробные сметы']
        self.assertEqual(summary.freeze_panes,'C8')
        self.assertTrue(summary.auto_filter.ref)
        self.assertEqual(summary['A8'].value,'=1+2')
        self.assertEqual(summary['A8'].data_type,'s')
        self.assertEqual(summary['B4'].value,9,'исходный делитель не равен количеству экспортируемых строк')
        self.assertTrue(str(summary['P8'].value).startswith("='Подробные сметы'!"))
        formulas=[c.value for row in detail for c in row if c.data_type=='f']
        self.assertTrue(any('ROUNDUP' in f for f in formulas))
        self.assertTrue(any('IF(' in f and 'Распоясовка' in f for f in formulas))
        self.assertTrue(any("'Сводка'!$B$4" in f for f in formulas))
        self.assertTrue(any(d.outlineLevel==1 for d in detail.row_dimensions.values()))
        for row in detail:
            for cell in row:
                if cell.value=='=HYPERLINK("bad")': self.assertEqual(cell.data_type,'s')
        with zipfile.ZipFile(io.BytesIO(self.content)) as z:
            self.assertFalse(any('externalLink' in n or 'vbaProject' in n for n in z.namelist()))

    def test_rejects_invalid_snapshots(self):
        for mutate in [lambda s:s.update(rows=[]),lambda s:s.update(rows=s['rows']*34),
                       lambda s:s['rows'][0]['input'].update(fill=101),
                       lambda s:s['rows'][0]['input'].update(gross=float('nan')),
                       lambda s:s['rows'][0]['input'].update(ads=True),
                       lambda s:s['rows'][0]['input'].update(zones=[{}]*41),
                       lambda s:s['rows'][0]['input'].update(cost_items={'variable':[{'amount':101}]}),
                       lambda s:s['rows'][1].update(id=s['rows'][0]['id'])]:
            changed=copy.deepcopy(self.snapshot);mutate(changed)
            with self.assertRaises(ValueError): build_workbook(changed)

    def test_subset_keeps_full_tour_cost_allocation(self):
        s=copy.deepcopy(self.snapshot);s['rows']=s['rows'][:2]
        w=openpyxl.load_workbook(io.BytesIO(build_workbook(s)),data_only=True)
        self.assertEqual(w['Сводка']['B4'].value,9)
        for i,r in enumerate(s['rows'],8):
            self.assertAlmostEqual(w['Сводка'].cell(i,10).value,r['calc']['project']['total'],places=6)

    def test_api_download_and_invalid_json(self):
        app=Flask(__name__);app.register_blueprint(bp);client=app.test_client()
        response=client.post('/api/planning/export.xlsx',json=self.snapshot)
        self.assertEqual(response.status_code,200)
        self.assertIn('spreadsheetml',response.content_type)
        self.assertIn('attachment',response.headers['Content-Disposition'])
        self.assertEqual(client.post('/api/planning/export.xlsx',json={}).status_code,400)
        self.assertEqual(client.post('/api/planning/export.xlsx',data='bad').status_code,400)


if __name__ == '__main__':
    unittest.main()
