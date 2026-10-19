"""Build an audited source archive and a connector upload manifest."""
import base64
import hashlib
import json
import zipfile
from pathlib import Path

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
folders = ['studio', 'tests', 'tools', 'docs', 'examples', '.github']
top = ['.gitignore', '.dockerignore', '.env.example', 'README.md', 'PRODUCT.md', 'DESIGN.md', 'requirements.txt', 'requirements.lock.txt', 'setup.ps1', 'start.ps1', 'Dockerfile', 'compose.yaml', 'ДЕМО.cmd', 'СОЗДАТЬ КП.cmd', 'ОТКРЫТЬ СТУДИЮ.cmd']
forbidden = {'.git', '.venv', '.tmp', 'output', '__pycache__', '.pytest_cache', '.env', 'node_modules'}
paths = [root / p for p in top]
for folder in folders:
    paths.extend(p for p in (root / folder).rglob('*') if p.is_file() and not forbidden.intersection(p.relative_to(root).parts))
paths = sorted(set(paths))
secret = dotenv_values(root / '.env').get('OPENAI_API_KEY', '')
files = []
for p in paths:
    data = p.read_bytes()
    rel = p.relative_to(root).as_posix()
    if forbidden.intersection(Path(rel).parts):
        raise RuntimeError('Forbidden file selected')
    if secret and secret.encode() in data:
        raise RuntimeError('Secret detected; packaging stopped')
    if p.suffix == '.docx':
        with zipfile.ZipFile(p) as doc:
            if secret and any(secret.encode() in doc.read(name) for name in doc.namelist()):
                raise RuntimeError('Secret detected in document; packaging stopped')
    files.append({'path': rel, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'content': base64.b64encode(data).decode()})
release = root / 'release'
release.mkdir(exist_ok=True)
target = release / 'КП-студия-для-сдачи.zip'
with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
    for p in paths:
        archive.write(p, 'kp-studio/' + p.relative_to(root).as_posix())
with zipfile.ZipFile(target) as archive:
    if archive.testzip() is not None:
        raise RuntimeError('Archive integrity check failed')
    for entry in files:
        if hashlib.sha256(archive.read('kp-studio/' + entry['path'])).hexdigest() != entry['sha256']:
            raise RuntimeError('Archive content mismatch')
manifest = [{k: v for k, v in e.items() if k != 'content'} for e in files]
(release / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
(root / '.tmp' / 'upload-manifest.json').write_text(json.dumps(files), encoding='utf-8')
print(json.dumps({'files': len(files), 'archive': str(target), 'bytes': target.stat().st_size, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'secret_scan': 'passed', 'integrity': 'passed'}, ensure_ascii=False))
