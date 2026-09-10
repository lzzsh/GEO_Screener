"""Resolve private prompt overrides without hiding the versioned bundled defaults."""
import os
from pathlib import Path

BUNDLED_PROMPTS = Path(__file__).resolve().parent / 'prompts'
PROMPT_TYPES = {'label_prompt', 'gsm_label_prompt', 'paper_calibration_prompt'}


def prompt_path(schema_name, prompt_type):
    if prompt_type not in PROMPT_TYPES:
        raise ValueError('Unknown prompt type')
    root = Path(os.getenv('PROMPT_DIR', BUNDLED_PROMPTS)).resolve()
    path = (root / schema_name / (prompt_type + '.txt')).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Invalid prompt directory')
    return path


def read_prompt(schema_name, prompt_type):
    candidates = [prompt_path(schema_name, prompt_type), prompt_path('default', prompt_type),
                  BUNDLED_PROMPTS / 'default' / (prompt_type + '.txt')]
    for path in dict.fromkeys(candidates):
        if path.is_file():
            content = path.read_text(encoding='utf-8')
            if content.strip():
                return content
    return ''
