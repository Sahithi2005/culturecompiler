"""Optional LLM wording polish (Anthropic Messages API over plain HTTPS). Off unless ANTHROPIC_API_KEY set.

The LLM never sees raw user text beyond the hypothesis sentence + evidence summaries and cannot add facts:
localize.maybe_rewrite() rejects any rewrite that introduces numbers not present in the evidence.
NOTE: written to the public API shape but not exercised against the live API in this build.
"""
from __future__ import annotations

import json
import os
import urllib.request

SYSTEM = ("You rewrite one market-entry hypothesis sentence so it reads clearly for a founder. "
          "Do not add facts, numbers, brands or claims that are not in the sentence or evidence. "
          "Keep it a hypothesis (use words like 'test' or 'explore'). Reply with the sentence only.")


class AnthropicLLM:
    def __init__(self, api_key: str, model: str | None = None, opener=None):
        self._key = api_key
        self._model = model or os.environ.get("CC_LLM_MODEL", "claude-sonnet-5-5")
        self._open = opener or urllib.request.urlopen

    def rewrite(self, statement: str, evidence: list[dict]) -> str:
        ev = [{"name": e["name"], "affinity": e.get("affinity"), "tags": [t["name"] for t in e.get("tags", [])]}
              for e in evidence][:10]
        body = json.dumps({
            "model": self._model, "max_tokens": 200, "system": SYSTEM,
            "messages": [{"role": "user", "content": f"Sentence: {statement}\nEvidence: {json.dumps(ev)}"}],
        }).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
            "x-api-key": self._key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with self._open(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
