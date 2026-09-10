import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace


def test_launcher_uses_isolated_files_and_persistent_secret(tmp_path, monkeypatch):
    import scripts.run_v2 as launcher
    data = tmp_path / 'v2'; data.mkdir()
    with sqlite3.connect(data / 'geo_search.db'):
        pass
    (data / 'runtime.json').write_text(json.dumps({'direct_api_hosts': ['api.example.org']}))
    monkeypatch.setattr(launcher, 'DATA', data)
    monkeypatch.setattr(launcher.os, 'chdir', lambda path: None)
    monkeypatch.setattr(launcher.sys, 'path', list(launcher.sys.path))
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.setenv('NO_PROXY', 'localhost')
    monkeypatch.setenv('no_proxy', '')
    for key in ['DATABASE_URL', 'PDF_DIR', 'PROTOCOL_DIR', 'PROTOCOL_EXECUTION', 'PROMPT_DIR', 'TASK_EXECUTION']:
        monkeypatch.setenv(key, '')
    calls = []
    monkeypatch.setitem(launcher.sys.modules, 'uvicorn', SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs))))
    launcher.main()
    assert os.environ['DATABASE_URL'].endswith(str(data / 'geo_search.db'))
    assert os.environ['TASK_EXECUTION'] == 'inline'
    assert os.environ['PROMPT_DIR'] == str(data / 'prompts')
    assert 'api.example.org' in os.environ['NO_PROXY']
    assert (data / '.secret_key').stat().st_mode & 0o777 == 0o600
    secret = (data / '.secret_key').read_text()
    assert len(secret) >= 48
    launcher.main()
    assert (data / '.secret_key').read_text() == secret
    assert calls[-1][1]['host'] == '127.0.0.1'


def test_prompt_edits_and_model_loading_use_v2_copy(tmp_path, monkeypatch):
    from backend.routers import prompts, annotation_schema
    from backend.worker.llm_client import LLMClient
    monkeypatch.setenv('PROMPT_DIR', str(tmp_path))
    (tmp_path / 'default').mkdir()
    (tmp_path / 'default' / 'label_prompt.txt').write_text('isolated v2 prompt')
    assert prompts._get_prompts_dir() == tmp_path
    assert annotation_schema._get_prompts_dir() == str(tmp_path)
    assert LLMClient.__new__(LLMClient)._load_prompt('unknown', 'label_prompt') == 'isolated v2 prompt'
