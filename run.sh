#!/bin/bash

cd "$(dirname "$0")"

# Check if virtual environment exists and works (a system Python minor upgrade
# leaves it unable to import its packages, so rebuild it in that case)
if [ ! -d "venv" ] || ! venv/bin/python3 -c "import selenium, requests, dotenv" &> /dev/null; then
  echo "Creating virtual environment..."
  rm -rf venv
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