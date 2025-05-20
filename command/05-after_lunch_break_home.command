#!/usr/bin/env bash

# Get the absolute path of the directory where the command file is located
command_dir="$(cd "$(dirname "$0")" && pwd)"

# Build the absolute path to the new after_lunch.py script in the parent directory
script_path="$command_dir/../after_lunch.py"

# Check if the script file exists
if [ ! -f "$script_path" ]; then
  echo "Error: could not find script file '$script_path'"
  exit 1
fi

# Find the location of python or python3 interpreter
PYTHON=$(which python3 || which python)

# Call the Python script using the interpreter location with the home parameter
$PYTHON "$script_path" --location home