#!/bin/bash
# Statement Organizer - final_schedule_c_filler.sh
# Auto-generated bash script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/final_schedule_c_filler.py"

if [ -f "$PYTHON_SCRIPT" ]; then
    echo "🚀 Starting final_schedule_c_filler.py..."
    
    # Try python3 first, then python
    if command -v python3 &> /dev/null; then
        python3 "$PYTHON_SCRIPT" "$@"
    elif command -v python &> /dev/null; then
        python "$PYTHON_SCRIPT" "$@"
    else
        echo "❌ Error: Python not found in PATH"
        echo "Please install Python 3.12+ and try again"
        exit 1
    fi
else
    echo "❌ Error: final_schedule_c_filler.py not found in $SCRIPT_DIR"
    echo "Please ensure you're running this script from the Statement Organizer directory"
    exit 1
fi
