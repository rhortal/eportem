#!/usr/bin/env python3
import os
import argparse
import threading
import time
import signal
import sys
import colorama
from colorama import Fore, Style
from utility.server import start_mock_server

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
    # Initialize colorama for colored terminal output
    colorama.init()
    
    parser = argparse.ArgumentParser(description="Run the ePortem mock server for testing.")
    parser.add_argument("--host", default="localhost", help="Host to run the server on")
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on")
    parser.add_argument("--debug", action="store_true", help="Run in debug mode")
    args = parser.parse_args()
    
    print(f"{Fore.GREEN}Starting ePortem mock server on http://{args.host}:{args.port}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}*** MOCK MODE - NO REAL CREDENTIALS WILL BE USED ***{Style.RESET_ALL}")
    print("Press Ctrl+C to stop the server")
    
    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start the server
    server_thread = start_server_thread(args.host, args.port, args.debug)
    
    # Print default test credentials
    print("\nMOCK SERVER MODE - Using test credentials only:")
    print(f"  Username: test_user")
    print(f"  Password: test_password")
    print("\nWARNING: Real credentials will NOT be used in mock mode for security.")
    
    print("\nTest URLs:")
    print(f"  Login: http://{args.host}:{args.port}/Usuario/Login")
    print(f"  Dashboard: http://{args.host}:{args.port}/aplicaciones")
    print(f"  Reset Session: http://{args.host}:{args.port}/reset")
    print("\nNote: If port 8000 is already in use, you can specify a different port with --port")
    
    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down mock server...")
        sys.exit(0)

if __name__ == "__main__":
    main()