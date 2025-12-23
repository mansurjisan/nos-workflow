#!/usr/bin/env python3
"""
NOS OFS Unified Python Package

Installation:
    pip install -e .           # Development install
    pip install -e ".[full]"   # With xarray, netCDF4, scipy
    pip install -e ".[dev]"    # With pytest, black, flake8
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read version from package
version = "1.0.0"

# Read README if available
readme_file = Path(__file__).parent / "README.md"
long_description = ""
if readme_file.exists():
    long_description = readme_file.read_text()

setup(
    name="nos_ofs",
    version=version,
    author="Mansur Ali Jisan",
    author_email="mansur.jisan@noaa.gov",
    description="Unified Python package for NOAA Operational Ocean Forecast Systems",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/NOAA-OCS-Modeling/nosofs",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "License :: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering :: Atmospheric Science",
        "Topic :: Scientific/Engineering :: Hydrology",
    ],
    python_requires=">=3.8",
    install_requires=[
        "numpy>=1.20",
        "pyyaml>=5.4",
    ],
    extras_require={
        "full": [
            "xarray>=0.19",
            "netCDF4>=1.5",
            "scipy>=1.7",
            "pandas>=1.3",
        ],
        "dev": [
            "pytest>=6.0",
            "pytest-cov>=2.0",
            "black>=21.0",
            "flake8>=3.9",
            "mypy>=0.900",
        ],
    },
    entry_points={
        "console_scripts": [
            "nos-ofs=nos_ofs.cli:main",
            "yaml-to-env=nos_ofs.utils.yaml_to_env:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
