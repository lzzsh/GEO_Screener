"""Copy a v1 SQLite snapshot and PDFs into an isolated v2 data directory."""
import argparse
import os
from pathlib import Path
import shutil
import sqlite3


def prepare(source_db, source_pdfs, destination):
    source_db, source_pdfs, destination = map(lambda p: Path(p).resolve(), (source_db, source_pdfs, destination))
    if not source_db.is_file():
        raise ValueError(f'Source database does not exist: {source_db}')
    if destination.exists():
        raise ValueError(f'Refusing to overwrite existing v2 data: {destination}')
    os.umask(0o077)
    destination.mkdir(parents=True)
    temporary = destination / 'geo_search.db.partial'
    with sqlite3.connect(source_db.as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(temporary) as target:
            source.backup(target)
            check = target.execute('PRAGMA integrity_check').fetchone()[0]
            if check != 'ok':
                raise ValueError('SQLite integrity check failed')
    temporary.replace(destination / 'geo_search.db')
    if source_pdfs.is_dir():
        shutil.copytree(source_pdfs, destination / 'pdfs')
    else:
        (destination / 'pdfs').mkdir()
    (destination / 'protocols').mkdir()
    shutil.copytree(Path(__file__).resolve().parents[1] / 'backend/prompts', destination / 'prompts')
    print(f'v2 database: {destination / "geo_search.db"}')
    print('SQLite integrity_check: ok; v1 files were opened read-only.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-db', required=True)
    parser.add_argument('--source-pdfs', default='pdfs')
    parser.add_argument('--destination', default='data/v2')
    args = parser.parse_args()
    prepare(args.source_db, args.source_pdfs, args.destination)
