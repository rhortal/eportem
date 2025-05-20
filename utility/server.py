#!/usr/bin/env python3
import os
import json
from flask import Flask, request, render_template, redirect, url_for, jsonify, session

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates'))
app.secret_key = 'mock_server_secret_key'

# Default credentials for testing
DEFAULT_USERNAME = 'test_user'
DEFAULT_PASSWORD = 'test_password'

# Store session data
user_sessions = {}

@app.route('/Usuario/Login', methods=['GET', 'POST'])
def login():
    """Mock login endpoint for ePortem."""
    if request.method == 'POST':
        username = request.form.get('user')
        password = request.form.get('password')
        
        # Check if credentials match expected values or env variables
        expected_username = os.getenv('EPORTEM_USERNAME', DEFAULT_USERNAME)
        expected_password = os.getenv('EPORTEM_PASSWORD', DEFAULT_PASSWORD)
        
        if username == expected_username and password == expected_password:
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='Invalid credentials')
    
    return render_template('login.html')

@app.route('/aplicaciones', methods=['GET'])
def dashboard():
    """Mock dashboard endpoint for ePortem."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    return render_template('dashboard.html', username=session.get('username'))

@app.route('/api/action', methods=['POST'])
def handle_action():
    """API endpoint to handle actions (start day, lunch break, etc.)."""
    if not session.get('logged_in'):
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401
    
    data = request.json
    action_type = data.get('action_type')
    location = data.get('location', 'office')
    
    # Log the action for testing verification
    print(f"Action: {action_type}, Location: {location}")
    
    return jsonify({
        'status': 'success',
        'message': f"Action {action_type} performed successfully from {location}",
        'timestamp': session.get('timestamp', '12:00:00')
    })

@app.route('/reset', methods=['GET'])
def reset_session():
    """Reset the session state for testing."""
    session.clear()
    return redirect(url_for('login'))

@app.route('/status', methods=['GET'])
def server_status():
    """Check if mock server is running."""
    return jsonify({
        'status': 'running',
        'version': '1.0.0',
        'mode': 'mock'
    })

def start_mock_server(host='localhost', port=5000, debug=False):
    """Start the mock server."""
    app.run(host=host, port=port, debug=debug)

if __name__ == '__main__':
    start_mock_server(debug=True)