"""The site's own details come from settings (BRIDGE_APP_NAME, BRIDGE_ORIGIN, BRIDGE_FEEDBACK_REPO), so the code names
no particular site and a copy of it runs as itself."""
import json
from pathlib import Path

from bridge import app as app_module, site
from bridge.accounts import origin_for
from bridge.coach import instructions
from bridge.connector import slug
from bridge.push import contact

WEB = Path(__file__).resolve().parents[2] / "web"


def test_unset_the_app_is_plain_bridge(monkeypatch):
    for name in ("BRIDGE_APP_NAME", "BRIDGE_ORIGIN", "BRIDGE_FEEDBACK_REPO"):
        monkeypatch.delenv(name, raising=False)
    assert site.app_name() == "Bridge" and site.origin() is None and site.feedback_repo() is None
    assert instructions().startswith("You are coaching a player of Bridge, a bridge app")
    assert contact() == "https://localhost"
    assert origin_for("bridge.example.com", "http").origin == "https://bridge.example.com"


def test_a_site_sets_its_own(monkeypatch):
    monkeypatch.setenv("BRIDGE_APP_NAME", " Card Club ")
    monkeypatch.setenv("BRIDGE_ORIGIN", "https://bridge.example.com/")
    monkeypatch.setenv("BRIDGE_FEEDBACK_REPO", "owner/feedback")
    assert site.app_name() == "Card Club" and site.feedback_repo() == "owner/feedback"
    assert site.origin() == contact() == "https://bridge.example.com"
    assert origin_for("anything:8000", "http").rp_id == "bridge.example.com"
    assert "a player of Card Club, a bridge app" in instructions() and "{name}" not in instructions()
    assert slug("Card Club") == "card-club" and slug("!!") == "bridge"


def test_the_page_and_manifest_carry_the_name(monkeypatch):
    monkeypatch.setenv("BRIDGE_APP_NAME", "Pat & Lee's <Bridge>")
    page = app_module.named_page((WEB / "index.html").read_text())
    assert "<title>Pat &amp; Lee&#x27;s &lt;Bridge&gt;</title>" in page
    assert '<meta name="apple-mobile-web-app-title" content="Pat &amp; Lee&#x27;s &lt;Bridge&gt;" />' in page
    manifest = json.loads(app_module.named_manifest((WEB / "public" / "manifest.webmanifest").read_text()))
    assert manifest["name"] == manifest["short_name"] == "Pat & Lee's <Bridge>"
    assert manifest["start_url"] == "/" and manifest["icons"]


def test_the_page_carries_the_source_link_only_when_set(monkeypatch):
    monkeypatch.delenv("BRIDGE_SOURCE_URL", raising=False)
    assert '<meta name="source-url" content="" />' in app_module.named_page((WEB / "index.html").read_text())
    monkeypatch.setenv("BRIDGE_SOURCE_URL", " https://github.com/owner/name?a=1&b=2 ")
    page = app_module.named_page((WEB / "index.html").read_text())
    assert '<meta name="source-url" content="https://github.com/owner/name?a=1&amp;b=2" />' in page
    monkeypatch.setenv("BRIDGE_SOURCE_URL", "javascript:alert(1)")  # only a web address becomes a link
    assert site.source_url() is None


def test_the_server_sends_the_named_page(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text((WEB / "index.html").read_text())
    (tmp_path / "manifest.webmanifest").write_text((WEB / "public" / "manifest.webmanifest").read_text())
    (tmp_path / "icon.svg").write_text("<svg/>")
    monkeypatch.setattr(app_module, "WEB_DIST", tmp_path)
    monkeypatch.setenv("BRIDGE_APP_NAME", "Card Club")
    for path in ("", "index.html", "some/page"):
        r = app_module.web_response(path)
        assert b"<title>Card Club</title>" in r.body and r.headers["cache-control"] == "no-cache"
    assert json.loads(app_module.web_response("manifest.webmanifest").body)["name"] == "Card Club"
    assert app_module.web_response("icon.svg").path == tmp_path / "icon.svg"  # other files as they are
