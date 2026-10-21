#!/bin/bash
# Simple CFP installer

echo "Installing CFP replacement..."

# Create the CFP script
cat > /usr/bin/cfp << 'EOL'
#!/bin/bash
#
# CFP Replacement Script (v2.0.4 compatible)
# This script mimics the behavior of the WCOSS2 cfp utility
#

# Print version information
VERSION="2.0.4"

# Check arguments
if [ "$#" -ne 1 ]; then
    echo "Error: Invalid number of arguments"
    echo "Usage: cfp <command_file>"
    exit 1
fi

COMMAND_FILE="$1"

# Check if the command file exists
if [ ! -f "$COMMAND_FILE" ]; then
    echo "Error: Command file '$COMMAND_FILE' not found"
    exit 1
fi

# Get environment variables
CFP_VERBOSE=${CFP_VERBOSE:-}
CFP_DOALL=${CFP_DOALL:-}
CFP_DELAY=${CFP_DELAY:-0}
CFP_MINMEM=${CFP_MINMEM:-0}

# Print verbose information if requested
if [ -n "$CFP_VERBOSE" ]; then
    echo "CFP_VERBOSE: Enabled"
    echo "CFP_DOALL: ${CFP_DOALL:+Enabled}"
    echo "CFP_DELAY: $CFP_DELAY seconds"
    echo "CFP_MINMEM: $CFP_MINMEM GB"
    echo "Command file: $COMMAND_FILE"
fi

# Count total commands
TOTAL_CMDS=$(grep -v '^[[:space:]]*#' "$COMMAND_FILE" | grep -v '^[[:space:]]*$' | wc -l)
echo "Total commands to execute: $TOTAL_CMDS"

# Read and process commands
CMD_NUM=0
FAILED=0

# Process all commands sequentially
while IFS= read -r CMD || [[ -n "$CMD" ]]; do
    # Skip empty lines and comments
    if [[ -z "$CMD" || "$CMD" =~ ^[[:space:]]*# ]]; then
        continue
    fi

    CMD_NUM=$((CMD_NUM + 1))
    echo "[$CMD_NUM/$TOTAL_CMDS] Executing: $CMD"

    # Execute the command
    eval "$CMD"
    STATUS=$?

    if [ $STATUS -ne 0 ]; then
        echo "Command $CMD_NUM failed with exit code $STATUS"
        FAILED=$((FAILED + 1))

        # If CFP_DOALL is not set, stop processing
        if [ -z "$CFP_DOALL" ]; then
            echo "Error detected and CFP_DOALL not set. Stopping."
            break
        fi
    fi
done < <(grep -v '^[[:space:]]*#' "$COMMAND_FILE" | grep -v '^[[:space:]]*$')

# Final status report
echo "CFP execution completed"
echo "Total commands executed: $CMD_NUM"
echo "Failed commands: $FAILED"

# Return non-zero if any command failed
if [ $FAILED -gt 0 ]; then
    exit 1
fi

exit 0
EOL

# Make the script executable
chmod +x /usr/bin/cfp

# Verify installation
if [ -x /usr/bin/cfp ]; then
    echo "CFP successfully installed at /usr/bin/cfp"
else
    echo "ERROR: Failed to install CFP"
    exit 1
fi

# Create a module file for CFP
mkdir -p /usr/share/modulefiles/cfp
cat > /usr/share/modulefiles/cfp/2.0.4 << 'EOL'
#%Module 1.0
#
#  Modulefile for CFP (Command Farm Package) replacement
#
conflict    cfp
prepend-path    PATH    /usr/bin
setenv        CFP_VERSION    2.0.4
EOL

# Add to module initialization if it exists
if [ -f /etc/environment-modules/initrc ]; then
    if ! grep -q "module load cfp" /etc/environment-modules/initrc; then
        echo "module load cfp/2.0.4" >> /etc/environment-modules/initrc
        echo "Added CFP module to auto-load list"
    fi
fi

echo "CFP installation complete!"
echo "Create a test file and try it with: cfp <command_file>"
