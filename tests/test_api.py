import os
import tempfile
import shutil
import pytest
from flask import Flask
from eportem.web_ui import server as webui

@pytest.fixture
def client(monkeypatch):
    # Use a temporary .env file for tests
    temp_dir = tempfile.mkdtemp()
    env_path = os.path.join(temp_dir, ".env")
    # Patch ENV_PATH in server
    monkeypatch.setattr(webui, "ENV_PATH", env_path)
    webui.CONFIG_ERROR = webui.validate_basic_config()

    app = webui.app
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client
    shutil.rmtree(temp_dir)

def test_env_schema(client):
    resp = client.get("/api/env_schema")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    keys = {f["key"] for f in data["schema"]}
    # Basic required keys always present
    for k in ["EPORTEM_USERNAME", "EPORTEM_PASSWORD", "WEB_UI_PORT"]:
        assert k in keys

def test_env_read_write_and_validation(client):
    # 1. Write partial/incomplete config
    resp = client.post("/api/env", json={"env": {"EPORTEM_USERNAME": "test", "WEB_UI_PORT": 8010}})
    assert resp.status_code == 400 or not resp.get_json()["success"]  # Required missing
    # 2. Write valid minimum config
    env = {
        "EPORTEM_USERNAME": "admin",
        "EPORTEM_PASSWORD": "pw",
        "EPORTEM_ENABLED": True,
        "HEADLESS_BROWSING": False,
        "WEB_UI_PORT": 8010,
    }
    resp = client.post("/api/env", json={"env": env})
    data = resp.get_json()
    assert data["success"] is True
    # 3. Re-read and check values persisted
    resp = client.get("/api/env")
    assert resp.status_code == 200
    vals = resp.get_json()["env"]
    for k in env:
        # All bools stored as YES/NO
        if isinstance(env[k], bool):
            target = "YES" if env[k] else "NO"
            assert vals[k] == target
        else:
            assert vals[k] == str(env[k])
    # 4. Invalid Telegram token
    bad_env = dict(env)
    bad_env["TELEGRAM_BOT_TOKEN"] = "BADTOKEN"
    resp = client.post("/api/env", json={"env": bad_env})
    assert resp.status_code == 400 and "format invalid" in resp.get_json()["error"]

def test_config_overlay_for_missing_env(client, monkeypatch):
    # Remove .env so config will be missing
    if os.path.exists(webui.ENV_PATH):
        os.remove(webui.ENV_PATH)
    webui.CONFIG_ERROR = webui.validate_basic_config()
    # Check main page returns config_error in template context
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Configuration is missing" in resp.data or b"Configuration incomplete" in resp.data
    # Also assert API state returns config_error
    resp = client.get("/api/state")
    data = resp.get_json()
    assert ("config_error" in data and data["config_error"])

def test_serverinfo_and_restart_api(client):
    # Serverinfo returns uptime & valid start time
    resp = client.get("/api/serverinfo")
    assert resp.status_code == 200
    info = resp.get_json()
    assert info["success"] is True
    assert "start_time" in info and "uptime_minutes" in info
    # Try restart (should return success immediately)
    resp = client.post("/api/restart")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
