"""Platform files not yet re-pointed at the HG recipe, each with the phase that rebuilds it (docs/hg/PLAN.md §16). Empty since Phase 4.

Until then they import the removed Halden packages (parts, bom, demand, tariffs, consignments, stock, news) or still write a Halden example. The
import check and the scans skip what is listed here, and fail when a listed path already imports and scans clean, so the list only shrinks.
Mirrored in docs/hg/NOTES.md. Paths are relative to the repository root; a path ending in "/" covers its whole directory.
"""

PENDING: dict[str, str] = {}      # Phases 2-4 re-pointed every platform file at the HG recipe; the list is empty and must stay so


def pending(rel: str) -> str | None:
    """The reason `rel` (a repository-relative path or a dotted module under backend/) is pending, or None."""
    path = rel if "/" in rel else "backend/" + rel.replace(".", "/")      # a module: app.domain.naming -> backend/app/domain/naming
    for key, why in PENDING.items():
        stem = key.removesuffix(".py").rstrip("/")
        if path in (key, stem) or path.startswith(stem + "/"):
            return why
    return None
