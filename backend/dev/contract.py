"""Write api/openapi.yaml from the server's own schema (then `cd frontend && npm run types`)."""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import app  # noqa: E402

(Path(__file__).resolve().parents[2] / "api" / "openapi.yaml").write_text(yaml.safe_dump(app.openapi(), sort_keys=False, allow_unicode=True, width=160))
