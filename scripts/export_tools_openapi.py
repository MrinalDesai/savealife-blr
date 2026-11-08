#!/usr/bin/env python3
"""Export the /api/tools OpenAPI subset to orchestrate/tools_openapi.json.

Usage:
    python scripts/export_tools_openapi.py

Env:
    PUBLIC_BASE_URL  (default: https://savealife-blr.2gwnl9m982ir.us-south.codeengine.appdomain.cloud)
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

# Make sure the project root is on sys.path so `app.main` can be imported.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402  (import after sys.path tweak)

BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    "https://savealife-blr.2gwnl9m982ir.us-south.codeengine.appdomain.cloud",
)

full_spec = app.openapi()
spec = copy.deepcopy(full_spec)

# Keep only paths under /api/tools
spec["paths"] = {
    path: item
    for path, item in spec.get("paths", {}).items()
    if path.startswith("/api/tools")
}

# Collect component schemas referenced by the kept paths only
# (FastAPI bundles everything; strip the 422 responses and keep the rest)
for path_item in spec["paths"].values():
    for operation in path_item.values():
        if isinstance(operation, dict):
            responses = operation.get("responses", {})
            operation["responses"] = {
                code: resp
                for code, resp in responses.items()
                if code != "422"
            }

# Metadata
spec["info"]["title"] = "SaveAlife BLR tools"
spec["info"]["version"] = "1.0.0"
spec["servers"] = [{"url": BASE_URL}]

# Write output
out_dir = Path(__file__).resolve().parents[1] / "orchestrate"
out_dir.mkdir(exist_ok=True)
out_path = out_dir / "tools_openapi.json"
out_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")

# Report
operation_ids = [
    op.get("operationId")
    for path_item in spec["paths"].values()
    for op in path_item.values()
    if isinstance(op, dict) and "operationId" in op
]
print(f"Wrote {out_path}")
print("operationIds:", ", ".join(sorted(operation_ids)))
