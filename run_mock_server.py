#!/usr/bin/env python3
import os
import argparse
import threading
import time
import signal
import sys
from mock_server.server import start_mock_server

def start_server_thread(host, port, debug):
    """Start the mock server in a separate thread."""
    thread = threading.Thread(
        target=start_mock_server,
        args=(host, port, debug),
        daemon=True
    )
    thread.start()
    return thread

def signal_handler(sig, frame):
    """Handle Ctrl+C to gracefully exit."""
    print("\nShutting down mock server...")
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="Run the ePortem mock server for testing.")
    parser.add_argument("--host", default="localhost", help="Host to run the server on")
    parser.add_argument("--port", type=int, default=5000, help="Port to run the server on")
    parser.add_argument("--debug", action="store_true", help="Run in debug mode")
    args = parser.parse_args()
    
    print(f"Starting ePortem mock server on http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop the server")
    
    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start the server
    server_thread = start_server_thread(args.host, args.port, args.debug)
    
    # Print default test credentials
    print("\nDefault test credentials:")
    print(f"  Username: {os.getenv('EPORTEM_USERNAME', 'test_user')}")
    print(f"  Password: {os.getenv('EPORTEM_PASSWORD', 'test_password')}")
    
    print("\nTest URLs:")
    print(f"  Login: http://{args.host}:{args.port}/Usuario/Login")
    print(f"  Dashboard: http://{args.host}:{args.port}/aplicaciones")
    print(f"  Reset Session: http://{args.host}:{args.port}/reset")
    
    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down mock server...")
        sys.exit(0)

if __name__ == "__main__":
    main()