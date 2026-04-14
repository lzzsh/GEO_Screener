import json
import re
from typing import Optional
from openai import AsyncOpenAI

PROVIDER_DEFAULTS: dict[str, dict] = {
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "glm":      {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4"},
    "minimax":  {"base_url": "https://api.minimax.chat/v1", "model": "abab6.5s-chat"},
}

SCREENING_PROMPT_TEMPLATE = """\
You are a systematic review screener. Evaluate the following dataset against the criteria.

## Screening Criteria
{criteria_text}

## Dataset Information
ID: {dataset_id}
Title: {title}
Description: {description}

## Instructions
Return ONLY valid JSON with this exact structure:
{{
  "decision": "include" | "exclude" | "uncertain",
  "confidence": 0.0-1.0,
  "summary": "one sentence rationale",
  "rule_checks": {{"criterion_key": true|false}}
}}
"""

class LLMClient:
    def __init__(self, provider: str, api_key: str, base_url: Optional[str] = None, model: Optional[str] = None, temperature: float = 0.1):
        defaults = PROVIDER_DEFAULTS.get(provider, {})
        self.model = model or defaults.get("model", "gpt-3.5-turbo")
        self.temperature = temperature
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or defaults.get("base_url"),
        )

    async def screen_dataset(self, dataset_id: str, title: str, description: str, criteria_text: str) -> dict:
        prompt = SCREENING_PROMPT_TEMPLATE.format(
            criteria_text=criteria_text,
            dataset_id=dataset_id,
            title=title,
            description=description,
        )
        response = await self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        return self._parse_json(raw)

    def _parse_json(self, raw: str) -> dict:
        # Strip markdown code fences if present
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
        text = match.group(1) if match else raw
        return json.loads(text)

    async def test_connection(self) -> bool:
        response = await self._client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            max_tokens=5,
        )
        return bool(response.choices[0].message.content)
