#!/usr/bin/env python3
"""
Wrapper script for YAML to environment variable conversion.

This script provides a convenient entry point for shell scripts to call
the yaml_to_env functionality from the nos_ofs package.

Usage:
    python3 yaml_to_env.py config.yaml --framework comf
    python3 yaml_to_env.py config.yaml --section domain

Author: NOS/CO-OPS
"""
import sys
import os

# Add Python package to path
script_dir = os.path.dirname(os.path.abspath(__file__))
python_pkg_dir = os.path.join(script_dir, 'python')
sys.path.insert(0, python_pkg_dir)

from nos_ofs.utils.yaml_to_env import main

if __name__ == '__main__':
    sys.exit(main())
