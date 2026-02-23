#!/bin/bash
# =============================================================================
# modify_gfs_nco.sh - Add ESMF/CF attributes to GFS NetCDF using NCO
# =============================================================================
#
# Alternative to Python script that uses NCO tools (more reliable on WCOSS2)
#
# Usage:
#   ./modify_gfs_nco.sh gfs_raw.nc gfs_for_esmf.nc
#
# =============================================================================

set -x

INPUT_FILE=$1
OUTPUT_FILE=$2

if [ -z "$INPUT_FILE" ] || [ -z "$OUTPUT_FILE" ]; then
    echo "Usage: $0 <input_file> <output_file>"
    exit 1
fi

if [ ! -s "$INPUT_FILE" ]; then
    echo "ERROR: Input file not found: $INPUT_FILE"
    exit 1
fi

echo "============================================"
echo "Modifying GFS NetCDF for ESMF (NCO method)"
echo "============================================"
echo "Input:  $INPUT_FILE"
echo "Output: $OUTPUT_FILE"

# Copy input to output first
cp "$INPUT_FILE" "$OUTPUT_FILE"

# Add global attributes
ncatted -h -a Conventions,global,o,c,"CF-1.6" "$OUTPUT_FILE"
ncatted -h -a title,global,o,c,"GFS 0.25-degree data prepared for ESMF mesh generation" "$OUTPUT_FILE"
ncatted -h -a source,global,o,c,"NCEP GFS" "$OUTPUT_FILE"

# Add/modify longitude attributes
ncatted -h -a units,longitude,o,c,"degrees_east" "$OUTPUT_FILE"
ncatted -h -a axis,longitude,o,c,"X" "$OUTPUT_FILE"
ncatted -h -a long_name,longitude,o,c,"longitude" "$OUTPUT_FILE"
ncatted -h -a standard_name,longitude,o,c,"longitude" "$OUTPUT_FILE"

# Add/modify latitude attributes
ncatted -h -a units,latitude,o,c,"degrees_north" "$OUTPUT_FILE"
ncatted -h -a axis,latitude,o,c,"Y" "$OUTPUT_FILE"
ncatted -h -a long_name,latitude,o,c,"latitude" "$OUTPUT_FILE"
ncatted -h -a standard_name,latitude,o,c,"latitude" "$OUTPUT_FILE"

# Add coordinates attribute to data variables
# Get list of data variables (excluding coordinates)
DATA_VARS=$(ncdump -h "$OUTPUT_FILE" | grep -E "^\s+(float|double|int)" | grep -v "longitude\|latitude\|time" | awk '{print $2}' | cut -d'(' -f1)

for var in $DATA_VARS; do
    echo "Adding coordinates attribute to: $var"
    ncatted -h -a coordinates,$var,o,c,"longitude latitude" "$OUTPUT_FILE" 2>/dev/null || true
done

# Add time attributes if time exists
if ncdump -h "$OUTPUT_FILE" | grep -q "time"; then
    ncatted -h -a axis,time,o,c,"T" "$OUTPUT_FILE" 2>/dev/null || true
    ncatted -h -a long_name,time,o,c,"time" "$OUTPUT_FILE" 2>/dev/null || true
fi

# Verify output
if [ -s "$OUTPUT_FILE" ]; then
    echo "============================================"
    echo "SUCCESS: Created $OUTPUT_FILE"
    ls -lh "$OUTPUT_FILE"
    echo ""
    echo "Coordinate attributes:"
    ncdump -h "$OUTPUT_FILE" | grep -A5 "longitude\|latitude" | head -20
    exit 0
else
    echo "ERROR: Failed to create $OUTPUT_FILE"
    exit 1
fi
