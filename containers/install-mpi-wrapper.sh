#!/bin/bash
# install-mpi-wrapper.sh
# Creates an MPI wrapper that works with the CFP replacement

echo "Creating MPI wrapper..."

# Create the mpiexec wrapper script
cat > /usr/bin/mpiexec << 'EOL'
#!/bin/bash
#
# mpiexec wrapper for use with cfp
# This script ignores MPI-specific arguments and just runs the command
#

# Find the command to execute (last argument)
for arg in "$@"; do
    LAST_ARG="$arg"
done

# Extract "cfp" and its argument if present
if [[ "$LAST_ARG" == cfp* ]]; then
    # If it's a cfp command, run it directly
    eval "$LAST_ARG"
else
    # Otherwise, just run the last argument as a command
    eval "$LAST_ARG"
fi
EOL

# Make the script executable
chmod +x /usr/bin/mpiexec

# Create symbolic link for mpirun
ln -sf /usr/bin/mpiexec /usr/bin/mpirun

echo "MPI wrapper installed successfully"
