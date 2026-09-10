from pathlib import Path
import pytest
from backend.worker.llm_client import LLMClient


@pytest.mark.asyncio
async def test_empty_private_directory_uses_shipped_defaults_in_ui_and_worker(tmp_path, monkeypatch):
    from backend.routers.prompts import get_default_prompt
    from backend.worker import protocol_tasks
    monkeypatch.setenv('PROMPT_DIR', str(tmp_path/'empty'))
    monkeypatch.setattr(protocol_tasks, 'PROMPT_PATH', tmp_path/'empty/protocol/extract_v1.txt')
    client = LLMClient(provider='deepseek', api_key='not-real')
    try:
        for kind in ('label_prompt','gsm_label_prompt','paper_calibration_prompt'):
            expected = (Path('backend/prompts/default')/(kind+'.txt')).read_text()
            assert (await get_default_prompt(kind))['content'] == expected
            assert client._load_prompt('new-schema',kind) == expected
        protocol = protocol_tasks.extraction_prompt()
        assert 'GSM extraction contract' in protocol
        assert 'protocol-chain-annotator' in protocol and 'perturbation-extractor' in protocol
    finally:
        await client._client.close()


@pytest.mark.asyncio
async def test_private_custom_prompt_has_priority_and_missing_schema_uses_default(tmp_path, monkeypatch):
    from backend.routers.prompts import get_default_prompt
    monkeypatch.setenv('PROMPT_DIR',str(tmp_path))
    (tmp_path/'default').mkdir();(tmp_path/'study').mkdir()
    (tmp_path/'default/label_prompt.txt').write_text('Local default')
    (tmp_path/'study/label_prompt.txt').write_text('My custom prompt')
    client=LLMClient(provider='deepseek',api_key='not-real')
    try:
        assert client._load_prompt('study','label_prompt') == 'My custom prompt'
        assert client._load_prompt('new-study','label_prompt') == 'Local default'
        assert (await get_default_prompt('label_prompt'))['content'] == 'Local default'
    finally: await client._client.close()


def test_container_initialization_does_not_create_shared_default_accounts(tmp_path):
    import os, subprocess, sys, sqlite3
    path=tmp_path/'fresh.db'
    env=dict(os.environ, DATABASE_URL=f'sqlite+aiosqlite:///{path}')
    subprocess.run([sys.executable,'-m','backend.init_users'],env=env,check=True,capture_output=True)
    with sqlite3.connect(path) as db:
        assert db.execute('select count(*) from users').fetchone()[0] == 0
