#!/bin/bash
# Wrapper script to generate synthetic conversation data
# This ensures the command runs from the correct directory

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Change to the script directory
cd "$SCRIPT_DIR"

# Run the data generator
poetry run generate-data "$@"
