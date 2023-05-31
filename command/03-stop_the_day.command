#!/bin/bash

# Get the absolute path of the directory where the command file is located
command_dir="$(cd "$(dirname "$0")" && pwd)"

# Get the filename of the script by removing characters to the left of the dash
script_filename="$(basename "$0" | sed 's/^[^-]*-//')"

# Remove the .command extension from script_filename
script_filename="${script_filename%.*}"

# Build the absolute path to the script in the parent directory
script_path="$command_dir/../$script_filename.py"

# Check if the script file exists
if [ ! -f "$script_path" ]; then
  echo "Error: could not find script file '$script_path'"
  exit 1
fi

# Execute the script
python3 "$script_path"