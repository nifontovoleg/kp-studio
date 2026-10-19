import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from studio.web import StudioServer


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr('studio.web.ROOT', tmp_path)
    with StudioServer(0) as instance:
        worker = threading.Thread(target=instance.serve_forever, daemon=True)
        worker.start()
        yield instance
        instance.shutdown()
        worker.join(timeout=3)


def request(server, path, data=None, headers=None):
    url = f'http://127.0.0.1:{server.server_address[1]}{path}'
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers


def test_web_rejects_cross_origin_and_host_rebinding(server):
    assert request(server, '/api/check?name=a.csv', b'a', {'X-Studio-Request': '1', 'Origin': 'https://example.com'})[0] == 403
    assert request(server, '/api/check?name=a.csv', b'a')[0] == 403
    assert request(server, '/api/status', headers={'Host': 'attacker.example'})[0] == 403


def test_real_upload_demo_generation_and_download(server):
    csv = 'Название компании;Контактное лицо;Потребности клиента;Бюджет\nТест;Анна;Бот для заказов;25000\n'
    status, body, _ = request(server, '/api/check?name=clients.csv', csv.encode(), {'X-Studio-Request': '1'})
    assert status == 200
    checked = json.loads(body)
    assert checked['clients'][0]['company'] == 'Тест'
    status, _, _ = request(server, '/api/run', json.dumps({'upload_id': checked['upload_id'], 'mode': 'demo'}).encode(), {'X-Studio-Request': '1'})
    assert status == 202
    for _ in range(100):
        _, body, _ = request(server, '/api/status')
        job = json.loads(body)['job']
        if job['status'] != 'running':
            break
        time.sleep(.02)
    assert job['status'] == 'completed'
    assert job['success'] == 1
    status, body, headers = request(server, job['results'][0]['download'])
    assert status == 200 and body.startswith(b'%PDF-')
    assert headers['Content-Type'] == 'application/pdf'
    assert request(server, '/api/file/../../.env')[0] == 404
    assert request(server, f'/api/file/{job["id"]}/-1')[0] == 404
    assert request(server, '/api/journal')[0] == 200


def test_invalid_upload_and_mode(server):
    assert request(server, '/api/check?name=file.exe', b'abc', {'X-Studio-Request': '1'})[0] == 400
    assert request(server, '/api/run', b'{', {'X-Studio-Request': '1'})[0] == 400
    assert request(server, '/api/run', b'{"mode":"unknown"}', {'X-Studio-Request': '1'})[0] == 400
