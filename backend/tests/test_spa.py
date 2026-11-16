"""The built UI: client routes get index.html, real root files (the service worker) are served, nothing outside dist."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main


def _client(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "sw.js").write_text("// sw")
    (tmp_path / "secret.txt").write_text("outside")
    monkeypatch.setattr(main, "_DIST", dist)
    application = FastAPI()
    main._mount_spa(application)
    return TestClient(application)


def test_root_file_is_served(tmp_path, monkeypatch):
    r = _client(tmp_path, monkeypatch).get("/sw.js")
    assert r.status_code == 200 and r.text == "// sw"


def test_client_route_gets_index(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/").text == "<html>app</html>"
    assert c.get("/items/pr-late:some-line").text == "<html>app</html>"


def test_nothing_outside_dist(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for p in ("/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt"):
        assert "outside" not in c.get(p).text


def test_api_paths_stay_404(tmp_path, monkeypatch):
    assert _client(tmp_path, monkeypatch).get("/api/nope").status_code == 404


def test_the_page_is_never_cached_and_the_hashed_bundles_are(tmp_path, monkeypatch):
    """A browser that opened an older build must ask for the page again, or it points at bundles that no longer exist (a blank page)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import main

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>")
    (dist / "assets" / "index-abc123.js").write_text("x")
    monkeypatch.setattr(main, "_DIST", dist)
    app = FastAPI()
    main._mount_spa(app)
    c = TestClient(app)
    assert c.get("/").headers["cache-control"] == "no-cache" and c.get("/approvals/A-1").headers["cache-control"] == "no-cache"
    assert "immutable" in c.get("/assets/index-abc123.js").headers["cache-control"]


def test_a_page_cached_before_a_deploy_still_boots_on_the_current_bundle(tmp_path, monkeypatch):
    """The old index.html asks for index-OLD.js: it gets the current entry bundle, not a 404 (a blank page); other missing files stay 404."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>")
    (dist / "assets" / "index-NEW1.js").write_text("new js")
    (dist / "assets" / "index-NEW1.css").write_text("new css")
    monkeypatch.setattr(main, "_DIST", dist)
    application = FastAPI()
    main._mount_spa(application)
    c = TestClient(application)
    js, css = c.get("/assets/index-OLD9.js"), c.get("/assets/index-OLD9.css")
    assert (js.status_code, js.text, css.text) == (200, "new js", "new css") and js.headers["cache-control"] == "no-cache"
    assert c.get("/assets/chunk-OLD9.js").status_code == 404
