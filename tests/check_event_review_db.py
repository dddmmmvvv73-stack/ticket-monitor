"""Run with TM_REVIEW_TEST_DSN pointing ONLY to a disposable database."""
import os
import tempfile
import json
import gzip
from unittest.mock import patch
import pathlib
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent.parent))
import psycopg2
from competitors import review
from db import connect

url=os.environ.get('TM_REVIEW_TEST_DSN','')
if not url:raise SystemExit('Set TM_REVIEW_TEST_DSN to a disposable database')
conn=psycopg2.connect(url)
assert conn.info.dbname.startswith('tm_review_test_'), 'Refusing a non-test database'
try:
    connect.ensure_schema(conn)
    cur=conn.cursor()
    cur.execute("INSERT INTO operators(id,name,kind) VALUES('kassir','test','federal')")
    cur.execute("INSERT INTO cities(name) VALUES('Тверь') RETURNING id");city=cur.fetchone()[0]
    cur.execute("INSERT INTO venues(city_id,name,name_key) VALUES(%s,'ДК','дк') RETURNING id",(city,));venue=cur.fetchone()[0]
    cur.execute("INSERT INTO artists(name,key) VALUES('Музыкант','музыкант') RETURNING id");aid=cur.fetchone()[0]
    sids=[]
    for n,title in enumerate(['Музыкант. Весенняя программа','Музыкант. Осенняя программа']):
        cur.execute("INSERT INTO projects(title,artist_id) VALUES(%s,%s) RETURNING id",(title,aid));pid=cur.fetchone()[0]
        cur.execute("INSERT INTO sessions(project_id,venue_id,local_date,title,status) VALUES(%s,%s,'2099-01-01',%s,'on_sale') RETURNING id",(pid,venue,title));sid=cur.fetchone()[0];sids.append(sid)
        cur.execute("INSERT INTO listings(session_id,operator_id,ext_key,title) VALUES(%s,'kassir',%s,%s)",(sid,'k:test'+str(n),title))
        cur.execute("INSERT INTO pools(session_id,operator_id) VALUES(%s,'kassir') RETURNING id",(sid,));pool=cur.fetchone()[0]
        cur.execute("INSERT INTO observations(pool_id,ts,raw_ref) VALUES(%s,now(),'data/raw_sales/test.json.gz')",(pool,))
        cur.execute("INSERT INTO seat_sales(pool_id,seat_key,ts,price,kind) VALUES(%s,'1',now(),1000,'sale')",(pool,))
        cur.execute("INSERT INTO price_sales(pool_id,ts_from,ts_to,price,qty) VALUES(%s,now()-interval '1 day',now(),1000,1)",(pool,))
        cur.execute("INSERT INTO listing_seen(operator_id,ext_key,first_seen) VALUES('kassir',%s,current_date)",('k:test'+str(n),))
    conn.commit()
    rule=dict(kind='project',pid=1,aid=aid,keys=['k:test0'],names=[review.key('Музыкант. Весенняя программа')],context={},reason='uninteresting')
    targets,raw=review.enforce_db(conn,[rule]);conn.commit()
    assert len(targets)==1 and len(raw)==1
    for table in ['sessions','listings','pools','observations','seat_sales','price_sales','listing_seen']:
        cur.execute('SELECT count(*) FROM '+table);assert cur.fetchone()[0]==1,table
    assert not review.enforce_db(conn,[rule])[0]
    artist=dict(rule,kind='artist',artist_key=review.key('Музыкант'),keys=[])
    assert len(review.enforce_db(conn,[artist])[0])==1
    conn.rollback()
    from db.sync import Sync
    assert callable(Sync.run)
    # Full worker path: database + raw archive + derivative export + minimal journal.
    conn.rollback()
    from competitors import storage, curation, myprojects
    with tempfile.TemporaryDirectory() as tmp:
        root=pathlib.Path(tmp)
        raw_file=root/'data/raw_sales/test.json.gz';raw_file.parent.mkdir(parents=True)
        raw_file.write_bytes(gzip.compress(b'raw response'))
        storage.save_json(root/'data/competitors/market/events.json',[
            {'title':'Музыкант. Осенняя программа','city':'Тверь','venue':'ДК','date':'2099-01-01','keys':['k:test1'],'format':'Концерт'}])
        snap=root/'data/sales_snapshot.json.gz';snap.write_bytes(gzip.compress(b'{"rows":{},"finals":{}}'))
        with patch.object(review,'ROOT',root), patch.object(review,'FILE',root/'config/event_review.json'), patch.object(storage,'ON_SERVER',True), patch.object(curation,'FILE',root/'config/market_curation.json'), patch.object(myprojects,'FILE',root/'config/my_projects.json'), patch.object(review,'db_connection',side_effect=lambda:psycopg2.connect(url)):
            state=review.load()
            state['operations']['full']={'status':'applying','until':0,'rules':[artist],'at':review.stamp(),'entries':[]}
            review.save(state);review.finalize_due()
            assert review.load()['operations']['full']['status']=='done',review.load()['operations']['full']
            assert len(review.load()['deleted'])==1
            assert not raw_file.exists()
            assert storage.load_json(root/'data/competitors/market/events.json',[])==[]
            assert json.loads(gzip.decompress(snap.read_bytes()))['rows']=={}
    print('PostgreSQL: project isolation, cascades, listings cleanup, idempotence, artist scope OK')
finally:conn.close()
