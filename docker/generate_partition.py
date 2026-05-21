#!/usr/bin/env python3
"""
Generate partition.prop for SCHISM with reduced core count.

SCHISM requires partition.prop to assign each element to an MPI rank.
On WCOSS2, this is pre-generated for 960+ procs. For container testing,
we generate a round-robin partition for a small number of compute procs.

Usage:
    python3 generate_partition.py <hgrid.gr3> <n_compute_procs> [output_file]

Example:
    python3 generate_partition.py secofs.hgrid.gr3 9 partition.prop
"""
import sys


def count_elements(hgrid_path):
    """Read element count from SCHISM hgrid.gr3 header (line 2)."""
    with open(hgrid_path, 'r') as f:
        f.readline()  # title
        line2 = f.readline().split()
        n_elements = int(line2[0])
        n_nodes = int(line2[1])
    return n_elements, n_nodes


def generate_round_robin(n_elements, n_procs, output_path):
    """Generate round-robin partition.prop file."""
    with open(output_path, 'w') as f:
        for i in range(n_elements):
            f.write(f"{i % n_procs}\n")
    return output_path


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    hgrid = sys.argv[1]
    n_procs = int(sys.argv[2])
    output = sys.argv[3] if len(sys.argv) > 3 else "partition.prop"

    n_elements, n_nodes = count_elements(hgrid)
    print(f"Grid: {n_nodes} nodes, {n_elements} elements")
    print(f"Partitioning for {n_procs} compute procs (round-robin)")

    generate_round_robin(n_elements, n_procs, output)
    print(f"Written: {output}")


if __name__ == "__main__":
    main()
