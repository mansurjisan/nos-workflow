DEFAULT_SLURMD_PATH = "/opt/slurm/sbin/slurmd"


def main() -> None:
    """
    Generates a SLURM node file from the slurmd command output.
    """
    import argparse
    import subprocess

    p = argparse.ArgumentParser("SLURM Node File Generator")
    p.add_argument(
        "--output", help="Output file", default="/opt/slurm/etc/auto_nodes.conf"
    )
    p.add_argument("--slurmd", help="Path to slurmd", default=DEFAULT_SLURMD_PATH)
    args = p.parse_args()

    result = subprocess.run([args.slurmd, "-C"], capture_output=True, check=False)
    node_info_str = result.stdout.decode("utf-8").split("\n")[0]

    # Convert the string to a dictionary
    node_info = {}
    for item in node_info_str.split(" "):
        key, value = item.split("=")
        node_info[key] = value

    node_info["NodeHostname"] = node_info["NodeName"]
    node_info["NodeName"] = "c1"

    # Remove Gres if it exists
    if "Gres" in node_info:
        del node_info["Gres"]

    # Write the dictionary to a file in the SLURM node format
    with open(args.output, "w") as f:
        for key, value in node_info.items():
            f.write(f"{key}={value} ")
        f.write("\n")


if __name__ == "__main__":
    main()
