"""Lookout API entry point. ORCH owns this file; lanes expose routers that ORCH mounts here."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

import os  # noqa: E402
import sys  # noqa: E402

if not os.environ.get("ANTHROPIC_API_KEY") and (os.environ.get("OPENAI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
    print("Lookout's agent runs on Anthropic models only: OPENAI_API_KEY / GOOGLE_API_KEY are not used. Set ANTHROPIC_API_KEY in .env, or leave it unset to use the saved runs.", file=sys.stderr)

from . import watcher  # noqa: E402  (after dotenv so LOOKOUT_EVENTS_DIR applies)
from .api import health  # noqa: E402
from .organism.prepare import on_startup as prepare_on_startup  # noqa: E402

app = FastAPI(title="Lookout", version="0.1.0", description="A procurement workspace: a system of record and a system of action")
app.router.add_event_handler("startup", prepare_on_startup)
app.add_middleware(GZipMiddleware, minimum_size=1024)  # the parts and orders tables carry provenance per row; over the wire they are 10-20 KB


@app.middleware("http")
async def request_events(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:10]}"
    request.state.request_id = request_id
    response = await call_next(request)
    if not request.url.path.startswith("/assets"):
        watcher.emit(
            "api", "request", f"{request.method} {request.url.path} -> {response.status_code}",
            request_id=request_id, status=response.status_code,
        )
    response.headers["x-request-id"] = request_id
    return response


app.include_router(health.router, prefix="/api")
# Lanes expose routers under backend/app/domain/<entity>/api.py and backend/app/organism/api.py; ORCH mounts them here.
from .organism import api as organism_api  # noqa: E402

app.include_router(organism_api.router, prefix="/api")
from .organism import agents_api  # noqa: E402

app.include_router(agents_api.router, prefix="/api")
from .domain.attention.api import router as attention_router  # noqa: E402
from .domain.orders.api import router as orders_router  # noqa: E402
from .domain.suppliers.api import router as suppliers_router  # noqa: E402
from .domain.parts.api import router as parts_router  # noqa: E402
from .domain.inbox.api import router as inbox_router  # noqa: E402
from .domain.demand.api import router as demand_router  # noqa: E402
from .domain.imports.api import router as imports_router  # noqa: E402

app.include_router(attention_router, prefix="/api")
app.include_router(orders_router, prefix="/api")
app.include_router(suppliers_router, prefix="/api")
app.include_router(parts_router, prefix="/api")
app.include_router(inbox_router, prefix="/api")
app.include_router(demand_router, prefix="/api")
app.include_router(imports_router, prefix="/api")
from .domain.quotes.api import router as quotes_router  # noqa: E402
app.include_router(quotes_router, prefix="/api")
from .domain.actions.api import router as actions_router  # noqa: E402
app.include_router(actions_router, prefix="/api")
from .domain.bom.api import router as bom_router  # noqa: E402
app.include_router(bom_router, prefix="/api")
from .domain.phases.api import router as phases_router  # noqa: E402
app.include_router(phases_router, prefix="/api")
from .domain.people.api import router as people_router  # noqa: E402
app.include_router(people_router, prefix="/api")
from .domain.consignments.api import router as consignments_router  # noqa: E402
app.include_router(consignments_router, prefix="/api")
from .domain.events.api import router as events_router  # noqa: E402
app.include_router(events_router, prefix="/api")
from .domain.annotate.api import router as annotate_router  # noqa: E402
app.include_router(annotate_router, prefix="/api")
from .domain.search.api import router as search_router  # noqa: E402
app.include_router(search_router, prefix="/api")

# Live counts owned by the ledger and the run store, registered with the sidebar's /api/counts.
from . import db as _db  # noqa: E402
from .domain.actions import ledger as _ledger  # noqa: E402
from .domain.attention.api import COUNT_PROVIDERS  # noqa: E402
from .organism.runs import store as _runs  # noqa: E402

COUNT_PROVIDERS["approvals_pending"] = lambda _s: len(_ledger.list_actions(_db.DB_PATH, "proposed"))


def _runs_running(_s) -> int:
    with _runs.connect(_db.DB_PATH) as con:
        return con.execute("SELECT count(*) FROM runs WHERE status = 'running' AND parent_run_id IS NULL").fetchone()[0]


COUNT_PROVIDERS["runs_running"] = _runs_running

# The built UI is mounted last so it never shadows an API route; unknown /api paths answer 404, not the SPA.
_DIST = _ROOT / "frontend" / "dist"


# The page and the service worker are asked for again on every visit, so a new build is never hidden behind a cached page that
# points at bundles that no longer exist; the bundles carry a content hash in their names and never change, so they are cached for good.
NO_CACHE = {"Cache-Control": "no-cache"}


class _ForeverStatic(StaticFiles):
    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as e:
            # A page cached before a deploy asks for the old entry bundle: serve the current one (not cached), so the old page still boots.
            m = re.fullmatch(r"index-[\w-]+\.(js|css)", path)
            current = sorted((_DIST / "assets").glob(f"index-*.{m.group(1)}")) if m and e.status_code == 404 else []
            if len(current) == 1:
                return FileResponse(current[0], headers=NO_CACHE)
            raise
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def _mount_spa(application: FastAPI) -> None:
    if not _DIST.exists():
        return
    application.mount("/assets", _ForeverStatic(directory=_DIST / "assets"), name="assets")

    @application.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        # root files the build emits (the service worker must be served from /), never anything outside dist
        candidate = (_DIST / full_path).resolve()
        if full_path and candidate.is_file() and _DIST.resolve() in candidate.parents:
            return FileResponse(candidate, headers=NO_CACHE)
        return FileResponse(_DIST / "index.html", headers=NO_CACHE)


_mount_spa(app)
