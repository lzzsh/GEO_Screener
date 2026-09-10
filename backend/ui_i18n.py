"""Explicit UI translations; research content and API values stay unchanged."""
import json
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parents[1] / 'frontend/locales/ui.json').read_text())


def ui_context(request):
    language = 'en' if request.cookies.get('geo_ui_lang') == 'en' else 'zh'
    messages = {source: values[language] for source, values in CATALOG.items()}
    return {'ui_lang': language, 'ui_messages': messages, 't': lambda source: messages.get(source, source)}
