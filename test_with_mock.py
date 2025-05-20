#!/usr/bin/env python3
import os
import argparse
import time
import threading
import subprocess
from mock_server.server import start_mock_server
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

def run_all_tests():
    """Run tests for all actions with the mock driver."""
    # Set environment variables for mock server
    os.environ['USE_MOCK_SERVER'] = 'YES'
    # Store original credentials
    orig_username = os.environ.get('EPORTEM_USERNAME', '')
    orig_password = os.environ.get('EPORTEM_PASSWORD', '')
    # Set mock credentials for testing
    os.environ['EPORTEM_USERNAME'] = 'test_user'
    os.environ['EPORTEM_PASSWORD'] = 'test_password'
    
    print("Testing all actions with mock server...")
    
    # Test start day from office
    print("\n1. Testing start_day at office:")
    execute_action('start_day', 'office', mock=True, use_mock_server=True)
    
    # Test lunch break
    print("\n2. Testing lunch_break:")
    execute_action('lunch_break', 'office', mock=True, use_mock_server=True)
    
    # Test after lunch at office
    print("\n3. Testing after_lunch at office:")
    execute_action('after_lunch', 'office', mock=True, use_mock_server=True)
    
    # Test start day from home
    print("\n4. Testing start_day at home:")
    execute_action('start_day', 'home', mock=True, use_mock_server=True)
    
    # Test after lunch at home
    print("\n5. Testing after_lunch at home:")
    execute_action('after_lunch', 'home', mock=True, use_mock_server=True)
    
    # Test stop day
    print("\n6. Testing stop_day:")
    execute_action('stop_day', 'office', mock=True, use_mock_server=True)
    
    print("\nAll tests completed successfully!")
    
    # Restore original credentials
    if orig_username:
        os.environ['EPORTEM_USERNAME'] = orig_username
    else:
        os.environ.pop('EPORTEM_USERNAME', None)
        
    if orig_password:
        os.environ['EPORTEM_PASSWORD'] = orig_password
    else:
        os.environ.pop('EPORTEM_PASSWORD', None)

def main():
    parser = argparse.ArgumentParser(description="Test ePortem actions using the mock server.")
    parser.add_argument("--action", choices=["start_day", "lunch_break", "after_lunch", "stop_day"], 
                      help="Specific action to test (tests all actions if not specified)")
    parser.add_argument("--location", choices=["home", "office"], default="office", 
                      help="Location (home or office)")
    args = parser.parse_args()
    
    # Store original credentials
    orig_username = os.environ.get('EPORTEM_USERNAME', '')
    orig_password = os.environ.get('EPORTEM_PASSWORD', '')
    
    # Set environment variables for mock server
    os.environ['USE_MOCK_SERVER'] = 'YES'
    os.environ['EPORTEM_USERNAME'] = 'test_user'
    os.environ['EPORTEM_PASSWORD'] = 'test_password'
    
    # Start the mock server
    server_thread = start_mock_server_thread()
    print("Mock server started on http://localhost:8000")
    print("Using mock credentials: test_user / test_password")
    
    try:
        if args.action:
            # Test specific action
            print(f"Testing {args.action} at {args.location}...")
            os.environ['USE_MOCK_SERVER'] = 'YES'
            execute_action(args.action, args.location, mock=True, use_mock_server=True)
            print("Test completed successfully!")
        else:
            # Test all actions
            run_all_tests()
    except Exception as e:
        print(f"Test failed: {e}")
    
    print("\nPress Ctrl+C to stop the server and exit")
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        # Restore original credentials
        if orig_username:
            os.environ['EPORTEM_USERNAME'] = orig_username
        else:
            os.environ.pop('EPORTEM_USERNAME', None)
            
        if orig_password:
            os.environ['EPORTEM_PASSWORD'] = orig_password
        else:
            os.environ.pop('EPORTEM_PASSWORD', None)

if __name__ == "__main__":
    main()