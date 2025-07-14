#!/bin/bash

# build_singularity.sh
# Script to build the STOFS-3D Atlantic Singularity container

set -e

# Configuration
CONTAINER_NAME="stofs3d.sif"
DEF_FILE="stofs3d.def"
BUILD_ARGS=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root or with sudo
check_privileges() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root or with sudo"
        print_error "Usage: sudo ./build_singularity.sh"
        exit 1
    fi
}

# Check if Singularity is installed
check_singularity() {
    if ! command -v singularity &> /dev/null; then
        print_error "Singularity is not installed or not in PATH"
        print_error "Please install Singularity first: https://docs.sylabs.io/guides/latest/admin-guide/installation.html"
        exit 1
    fi
    
    SINGULARITY_VERSION=$(singularity --version)
    print_status "Found Singularity version: $SINGULARITY_VERSION"
}

# Check if definition file exists
check_def_file() {
    if [[ ! -f "$DEF_FILE" ]]; then
        print_error "Definition file '$DEF_FILE' not found!"
        print_error "Please make sure the Singularity definition file is in the current directory"
        exit 1
    fi
    print_status "Found definition file: $DEF_FILE"
}

# Check required source files
check_source_files() {
    local missing_files=()
    
    # Check for required directories and files
    required_paths=(
        "containers/cgroup.conf"
        "containers/slurm.conf"
        "containers/slurmdbd.conf"
        "containers/get_slurm_node.py"
        "containers/install-cfp.sh"
        "containers/install-mpi-wrapper.sh"
        "containers/environment.sh"
        "containers/run.ver"
        "containers/sample_compaths.list"
        "src"
        "pyproject.toml"
        "examples/stofs_scripts"
        "examples/config_adcirc.yaml"
        "examples/config_schism.yaml"
        "ush/stofs_3d_atl"
        "exec/stofs_3d_atl"
    )
    
    for path in "${required_paths[@]}"; do
        if [[ ! -e "$path" ]]; then
            missing_files+=("$path")
        fi
    done
    
    if [[ ${#missing_files[@]} -gt 0 ]]; then
        print_error "Missing required source files/directories:"
        for file in "${missing_files[@]}"; do
            print_error "  - $file"
        done
        print_error "Please ensure all required files are present in the current directory"
        exit 1
    fi
    
    print_status "All required source files found"
}

# Clean previous build
clean_previous() {
    if [[ -f "$CONTAINER_NAME" ]]; then
        print_warning "Removing existing container: $CONTAINER_NAME"
        rm -f "$CONTAINER_NAME"
    fi
}

# Build the container
build_container() {
    print_status "Starting Singularity container build..."
    print_status "This may take 30-60 minutes depending on your system..."
    
    # Set build arguments if needed
    if [[ -n "$BUILD_ARGS" ]]; then
        print_status "Using build arguments: $BUILD_ARGS"
    fi
    
    # Run the build command
    if singularity build $BUILD_ARGS "$CONTAINER_NAME" "$DEF_FILE"; then
        print_status "Container built successfully: $CONTAINER_NAME"
        
        # Display container size
        local size=$(du -h "$CONTAINER_NAME" | cut -f1)
        print_status "Container size: $size"
        
        return 0
    else
        print_error "Container build failed!"
        return 1
    fi
}

# Test the container
test_container() {
    print_status "Testing container..."
    
    # Test basic functionality
    if singularity exec "$CONTAINER_NAME" echo "Container test successful"; then
        print_status "Basic container test passed"
    else
        print_error "Basic container test failed"
        return 1
    fi
    
    # Test STOFS workflow installation
    if singularity exec "$CONTAINER_NAME" python3 -c "import StofsWorkflow; print('STOFS Workflow imported successfully')"; then
        print_status "STOFS Workflow test passed"
    else
        print_warning "STOFS Workflow test failed - this may be expected if dependencies are missing"
    fi
    
    # Test key executables
    local executables=("wgrib2" "mpirun" "python3" "mysql")
    for exe in "${executables[@]}"; do
        if singularity exec "$CONTAINER_NAME" which "$exe" > /dev/null 2>&1; then
            print_status "Found executable: $exe"
        else
            print_warning "Executable not found: $exe"
        fi
    done
}

# Show usage information
show_usage() {
    cat << EOF
STOFS-3D Atlantic Singularity Container Builder

Usage: sudo $0 [OPTIONS]

OPTIONS:
    -h, --help          Show this help message
    -c, --clean-only    Only clean previous builds, don't build new container
    -t, --test-only     Only test existing container, don't build
    -f, --force         Force rebuild even if container exists
    --sandbox           Build as sandbox (writable) container
    --fakeroot          Use fakeroot for building (if available)

EXAMPLES:
    sudo $0                    # Standard build
    sudo $0 --sandbox          # Build as sandbox container
    sudo $0 --clean-only       # Just clean previous builds
    sudo $0 --test-only        # Just test existing container

NOTES:
    - This script must be run with root privileges (sudo)
    - Build process may take 30-60 minutes
    - Requires ~10-15 GB of free disk space
    - Internet connection required for downloading dependencies

EOF
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_usage
                exit 0
                ;;
            -c|--clean-only)
                CLEAN_ONLY=true
                shift
                ;;
            -t|--test-only)
                TEST_ONLY=true
                shift
                ;;
            -f|--force)
                FORCE_REBUILD=true
                shift
                ;;
            --sandbox)
                BUILD_ARGS="--sandbox"
                CONTAINER_NAME="stofs3d_sandbox"
                shift
                ;;
            --fakeroot)
                BUILD_ARGS="--fakeroot"
                shift
                ;;
            *)
                print_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done
}

# Main execution
main() {
    print_status "STOFS-3D Atlantic Singularity Container Builder"
    print_status "=============================================="
    
    # Parse arguments
    parse_args "$@"
    
    # Handle clean-only option
    if [[ "$CLEAN_ONLY" == "true" ]]; then
        clean_previous
        print_status "Cleanup completed"
        exit 0
    fi
    
    # Handle test-only option
    if [[ "$TEST_ONLY" == "true" ]]; then
        if [[ ! -f "$CONTAINER_NAME" ]]; then
            print_error "Container file '$CONTAINER_NAME' not found!"
            exit 1
        fi
        test_container
        exit $?
    fi
    
    # Standard build process
    check_privileges
    check_singularity
    check_def_file
    check_source_files
    
    # Check if container already exists
    if [[ -f "$CONTAINER_NAME" && "$FORCE_REBUILD" != "true" ]]; then
        print_warning "Container '$CONTAINER_NAME' already exists"
        read -p "Do you want to rebuild it? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_status "Build cancelled by user"
            exit 0
        fi
    fi
    
    clean_previous
    
    if build_container; then
        print_status "Build completed successfully!"
        test_container
        
        print_status ""
        print_status "Container ready for use:"
        print_status "  Interactive: singularity run $CONTAINER_NAME"
        print_status "  Execute cmd: singularity exec $CONTAINER_NAME <command>"
        print_status "  Shell:       singularity shell $CONTAINER_NAME"
    else
        print_error "Build failed!"
        exit 1
    fi
}

# Run main function with all arguments
main "$@"
        
