"""Start the isolated local v2 instance using its prepared data copy."""
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/v2'


def main():
    if not (DATA / 'geo_search.db').exists():
        raise SystemExit('Prepare v2 data first: python scripts/prepare_v2.py --source-db geo_search.db')
    runtime = json.loads((DATA / 'runtime.json').read_text()) if (DATA / 'runtime.json').exists() else {}
    direct_hosts = runtime.get('direct_api_hosts', [])
    if direct_hosts:
        bypass = os.environ.get('NO_PROXY', os.environ.get('no_proxy', ''))
        os.environ['NO_PROXY'] = ','.join(dict.fromkeys(filter(None, bypass.split(',') + ['localhost', '127.0.0.1'] + direct_hosts)))
        os.environ['no_proxy'] = os.environ['NO_PROXY']
    if not os.environ.get('SECRET_KEY'):
        secret_path = DATA / '.secret_key'
        if not secret_path.exists():
            with open(secret_path, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as file:
                file.write(secrets.token_urlsafe(48))
        os.environ['SECRET_KEY'] = secret_path.read_text().strip()
    os.environ['DATABASE_URL'] = f'sqlite+aiosqlite:///{DATA / "geo_search.db"}'
    os.environ['PDF_DIR'] = str(DATA / 'pdfs')
    os.environ['PROTOCOL_DIR'] = str(DATA / 'protocols')
    os.environ['PROMPT_DIR'] = str(DATA / 'prompts')
    os.environ['TASK_EXECUTION'] = 'inline'
    os.environ.setdefault('PROTOCOL_EXECUTION', 'inline')
    sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
    import uvicorn
    uvicorn.run('backend.main:app', host='127.0.0.1', port=8002)


if __name__ == '__main__':
    main()
