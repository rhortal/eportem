import os
import tempfile
import shutil
import subprocess
import time
import pytest
import socket

def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

@pytest.fixture(scope='session')
def flask_server_with_temp_env():
    # Create temp .env file with minimum valid config for your app
    temp_dir = tempfile.mkdtemp()
    temp_env = os.path.join(temp_dir, "test.env")
    port = find_free_port()
    with open(temp_env, "w") as f:
        f.write(f"EPORTEM_USERNAME=testuser\n")
        f.write(f"EPORTEM_PASSWORD=testpass\n")
        f.write(f"EPORTEM_ENABLED=YES\n")
        f.write(f"HEADLESS_BROWSING=NO\n")
        f.write(f"WEB_UI_PORT={port}\n")
    env = os.environ.copy()
    env["EPORTEM_ENV_PATH"] = temp_env
    env["WEB_UI_PORT"] = str(port)
    env["FLASK_ENV"] = "development"
    proc = subprocess.Popen(
        ["python", "web_ui/server.py"],
        env=env,
        cwd=".",  # run from eportem root, so . is correct
    )
    # Wait for startup (ideally poll the /api/state or /settings endpoint)
    for _ in range(30):
        try:
            import requests
            resp = requests.get(f"http://localhost:{port}/settings", timeout=1)
            if resp.status_code in (200, 401):
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        proc.terminate()
        raise RuntimeError("Flask test server did not start in time.")
    yield f"http://localhost:{port}"
    proc.terminate()
    proc.wait(timeout=5)
    shutil.rmtree(temp_dir)

@pytest.fixture
def flask_server_with_empty_env():
    # Create temp .env file with only a port entry and missing other required fields
    temp_dir = tempfile.mkdtemp()
    temp_env = os.path.join(temp_dir, "test.env")
    port = find_free_port()
    with open(temp_env, "w") as f:
        f.write(f"WEB_UI_PORT={port}\n")
    env = os.environ.copy()
    env["EPORTEM_ENV_PATH"] = temp_env
    env["WEB_UI_PORT"] = str(port)
    env["FLASK_ENV"] = "development"
    proc = subprocess.Popen(
        ["python", "web_ui/server.py"],
        env=env,
        cwd=".",
    )
    for _ in range(30):
        try:
            import requests
            resp = requests.get(f"http://localhost:{port}/settings", timeout=1)
            if resp.status_code in (200, 401):
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        proc.terminate()
        raise RuntimeError("Flask test server did not start in time.")
    yield f"http://localhost:{port}"
    proc.terminate()
    proc.wait(timeout=5)
    shutil.rmtree(temp_dir)
