"""Best-effort local and DynamoDB state mirror for UI and advisory state."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def sync_advisory_state(state: dict[str, Any]) -> None:
    path = Path("data/dynamodb_ui_sync.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
