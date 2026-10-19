"""Local-only browser interface over the same batch pipeline as the CLI."""
from __future__ import annotations

import argparse
import json
import threading
import uuid
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .core import ROOT, load_clients, run_batch

MAX_UPLOAD = 5 * 1024 * 1024


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=8765):
        super().__init__(('127.0.0.1', port), Handler)
        self.uploads = {}
        self.job = None
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server: StudioServer

    def log_message(self, format, *args):
        # Input names, client data and credentials never go into access logs.
        pass

    def respond(self, status, content, mime='application/json; charset=utf-8', *, attachment=False):
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False).encode('utf-8')
        elif isinstance(content, str):
            content = content.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        if attachment:
            self.send_header('Content-Disposition', 'attachment; filename="studio-document' + ('.pdf' if mime == 'application/pdf' else '.jsonl') + '"')
        if mime.startswith('text/html'):
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(content)

    def valid_host(self):
        port = self.server.server_address[1]
        return self.headers.get('Host', '') in {f'127.0.0.1:{port}', f'localhost:{port}'}

    def do_GET(self):
        if not self.valid_host():
            return self.respond(403, {'error': 'Недопустимый адрес сервера.'})
        path = urlsplit(self.path).path
        static = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if path in static:
            name, mime = static[path]
            return self.respond(200, (ROOT / 'studio' / 'static' / name).read_bytes(), mime)
        if path == '/favicon.ico':
            return self.respond(204, b'', 'image/x-icon')
        if path == '/api/status':
            with self.server.lock:
                job = self.server.job
                result = None if job is None else {k: v for k, v in job.items() if k != 'summary'}
                if job and job.get('summary'):
                    result['results'] = [{
                        'row': e['row'], 'company': e.get('company', ''), 'status': e['status'],
                        'error': e.get('error'),
                        'download': f'/api/file/{job["id"]}/{index}' if e['status'] == 'ok' else None,
                    } for index, e in enumerate(job['summary']['results'])]
            return self.respond(200, {'job': result})
        if path == '/api/example':
            return self.respond(200, (ROOT / 'examples' / 'clients.csv').read_bytes(), 'text/csv; charset=utf-8')
        if path == '/api/journal':
            journal = ROOT / 'output' / 'journal.jsonl'
            return self.respond(200, journal.read_bytes() if journal.exists() else b'', 'application/x-ndjson', attachment=True)
        if path.startswith('/api/file/'):
            parts = path.split('/')
            try:
                with self.server.lock:
                    job = self.server.job
                    if len(parts) != 5 or not job or parts[3] != job['id']:
                        raise ValueError
                    index = int(parts[4])
                    if index < 0:
                        raise ValueError
                    entry = job['summary']['results'][index]
                    target = (ROOT / 'output' / entry['pdf']).resolve()
                    if not target.is_relative_to((ROOT / 'output').resolve()) or target.suffix != '.pdf':
                        raise ValueError
                return self.respond(200, target.read_bytes(), 'application/pdf', attachment=True)
            except (KeyError, TypeError, ValueError, IndexError, OSError):
                return self.respond(404, {'error': 'Документ не найден.'})
        return self.respond(404, {'error': 'Страница не найдена.'})

    def do_POST(self):
        port = self.server.server_address[1]
        origin = self.headers.get('Origin')
        if not self.valid_host() or self.headers.get('X-Studio-Request') != '1' or origin not in {None, f'http://127.0.0.1:{port}', f'http://localhost:{port}'}:
            return self.respond(403, {'error': 'Запрос разрешён только из локального интерфейса.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_UPLOAD:
                return self.respond(413, {'error': 'Выберите непустой файл размером до 5 МБ.'})
            body = self.rfile.read(length)
            path = urlsplit(self.path).path
            if path == '/api/check':
                name = parse_qs(urlsplit(self.path).query).get('name', [''])[0]
                suffix = Path(name).suffix.lower()
                if suffix not in {'.csv', '.xlsx'}:
                    raise ValueError('Выберите таблицу CSV или XLSX.')
                with self.server.lock:
                    if self.server.job and self.server.job['status'] == 'running':
                        return self.respond(409, {'error': 'Дождитесь окончания текущего запуска.'})
                    if len(self.server.uploads) >= 20:
                        oldest = next(iter(self.server.uploads))
                        self.server.uploads.pop(oldest).unlink(missing_ok=True)
                    upload_id = uuid.uuid4().hex
                    target = ROOT / 'output' / '.uploads' / (upload_id + suffix)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(body)
                    try:
                        clients, errors = load_clients(target)
                    except Exception:
                        target.unlink(missing_ok=True)
                        raise
                    self.server.uploads[upload_id] = target
                return self.respond(200, {'upload_id': upload_id, 'clients': [{'row': row, **asdict(c)} for row, c in clients], 'errors': errors})
            if path == '/api/run':
                data = json.loads(body)
                if not isinstance(data, dict) or data.get('mode') not in {'demo', 'api'}:
                    raise ValueError('Выберите способ генерации.')
                with self.server.lock:
                    if self.server.job and self.server.job['status'] == 'running':
                        return self.respond(409, {'error': 'Генерация уже идёт. Дождитесь результата.'})
                    source = self.server.uploads.get(data.get('upload_id', ''))
                    if not source:
                        raise ValueError('Сначала загрузите и проверьте таблицу.')
                    job = {'id': uuid.uuid4().hex, 'status': 'running', 'mode': data['mode'], 'success': 0, 'failed': 0}
                    self.server.job = job
                    threading.Thread(target=self.work, args=(source, job), daemon=True).start()
                return self.respond(202, {'job_id': job['id']})
            return self.respond(404, {'error': 'Действие не найдено.'})
        except (ValueError, UnicodeDecodeError) as exc:
            # JSON errors are controlled; raw input and provider bodies are not echoed.
            message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else 'Не удалось прочитать запрос.'
            return self.respond(400, {'error': message})
        except Exception:
            return self.respond(400, {'error': 'Не удалось прочитать таблицу. Проверьте формат и попробуйте снова.'})

    def work(self, source, job):
        try:
            summary = run_batch(source, ROOT / 'output', demo=job['mode'] == 'demo')
            with self.server.lock:
                job.update(summary=summary, success=summary['success'], failed=summary['failed'], status='completed' if not summary['failed'] else ('partial' if summary['success'] else 'failed'))
        except Exception as exc:
            with self.server.lock:
                job.update(status='failed', error=str(exc) if isinstance(exc, (ValueError, RuntimeError)) else 'Не удалось завершить запуск. Проверьте настройки и доступ к папке результатов.')


def main():
    parser = argparse.ArgumentParser(description='Локальный экран КП-студии')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    with StudioServer(args.port) as server:
        url = f'http://127.0.0.1:{server.server_address[1]}'
        print(f'КП-студия: {url}', flush=True)
        if args.open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
