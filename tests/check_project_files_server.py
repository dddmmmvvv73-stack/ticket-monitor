"""Both project riders: independent persistence, preview, replacement and restoration; temporary files only."""
import base64
import copy
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from flask import Flask
from competitors import journal, work
from competitors.market_api import bp

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    work.FILE = root / 'work.json'
    work.MEDIA_DIR = root / 'work_media'
    journal.DIR = root / 'history'
    journal.AREAS['work']['file'] = work.FILE
    app = Flask(__name__)
    app.register_blueprint(bp)
    client = app.test_client()

    def post(**op):
        return client.post('/api/work', json=dict(kind='projects', id='project1', **op))

    def upload(what, name, raw):
        return post(op='pfile', what=what, name=name,
                    data='data:text/plain;base64,' + base64.b64encode(raw).decode())

    assert post(op='put', data={'title': 'Проверка райдеров'}).status_code == 200
    assert upload('rider', 'Технический.txt', b'Sound and light').status_code == 200
    assert upload('hospitality', 'Бытовой.txt', b'Hotel and catering').status_code == 200
    files = client.get('/api/work').json['projects']['project1']['pfiles']
    assert set(files) == {'rider', 'hospitality'}
    technical = copy.deepcopy(files['rider'])
    url = '/api/work/file/' + files['hospitality']['file']
    assert client.get(url).data == b'Hotel and catering'
    download = client.get(url + '?dl=1')
    assert download.status_code == 200 and 'attachment' in download.headers['Content-Disposition']
    assert work.doc_name(files['hospitality']['file']) == 'Бытовой.txt'
    preview = client.get('/api/work/preview/' + files['hospitality']['file'])
    assert preview.status_code == 200 and b'Hotel and catering' in preview.data
    assert upload('hospitality', 'Обновлённый.txt', b'Transfer and hotel').status_code == 200
    assert client.get(url).data == b'Transfer and hotel'
    assert post(op='put', data={'title': 'Новое название'}).json['projects']['project1']['pfiles']['rider'] == technical
    before = copy.deepcopy(work.load()['projects']['project1'])
    assert post(op='del').status_code == 200
    restored = post(op='put', data=before).json['projects']['project1']
    assert restored['pfiles'] == before['pfiles']
    assert post(op='pfile', what='hospitality', data='').status_code == 200
    assert client.get(url).status_code == 404
    assert work.load()['projects']['project1']['pfiles'] == {'rider': technical}
    assert work.media_file(technical['file']).read_bytes() == b'Sound and light'
    before_bad = work.load()
    assert upload('hospitality', 'bad.exe', b'bad').status_code == 400
    assert upload('unknown', 'bad.txt', b'bad').status_code == 400
    assert work.load() == before_bad

print('ok: independent riders, persistence, preview, download, replace, restore, remove, validation')
