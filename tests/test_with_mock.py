#!/usr/bin/env python3
import os
import argparse
import time
import threading
import subprocess
from utility.server import start_mock_server
from eportem_action import execute_action

def start_mock_server_thread():
    """Start the mock server in a background thread."""
    thread = threading.Thread(
        target=start_mock_server,
        args=('localhost', 8000, False),
        daemon=True
    )
    thread.start()
    # Wait for server to start
    time.sleep(1)
    return thread

import pytest

@pytest.fixture(scope="module", autouse=True)
def setup_mock_environment():
    """Set up the mock environment for all tests."""
    os.environ['USE_MOCK_SERVER'] = 'YES'
    os.environ['EPORTEM_USERNAME'] = 'test_user'
    os.environ['EPORTEM_PASSWORD'] = 'test_password'
    yield
    os.environ.pop('USE_MOCK_SERVER', None)
    os.environ.pop('EPORTEM_USERNAME', None)
    os.environ.pop('EPORTEM_PASSWORD', None)

def test_start_day_office():
    """Test start day from office."""
    execute_action('start_day', 'office', mock=True, use_mock_server=True)

def test_lunch_break():
    """Test lunch break."""
    execute_action('lunch_break', 'office', mock=True, use_mock_server=True)

def test_after_lunch_office():
    """Test after lunch at office."""
    execute_action('after_lunch', 'office', mock=True, use_mock_server=True)

def test_start_day_home():
    """Test start day from home."""
    execute_action('start_day', 'home', mock=True, use_mock_server=True)

def test_after_lunch_home():
    """Test after lunch at home."""
    execute_action('after_lunch', 'home', mock=True, use_mock_server=True)

def test_stop_day():
    """Test stop day."""
    execute_action('stop_day', 'office', mock=True, use_mock_server=True)

if __name__ == "__main__":
    print("This script is now refactored for pytest compatibility. Run `pytest` to execute the tests.")