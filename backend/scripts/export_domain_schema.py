"""Run from backend: uv run python scripts/export_domain_schema.py."""

import json
from pathlib import Path

from klegal_gold.domain.schema import domain_json_schema

path = Path(__file__).resolve().parents[2] / "docs/schemas/domain-0.1.0.json"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(
    json.dumps(domain_json_schema(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
