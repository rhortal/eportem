#!/bin/bash

cd "$(dirname "$0")"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
  echo "Installing requirements..."
  source venv/bin/activate
  pip install -r requirements.txt
else
  echo "Virtual environment already exists."
  source venv/bin/activate
fi

# Call main.py with all parameters passed through
python3 main.py "$@"