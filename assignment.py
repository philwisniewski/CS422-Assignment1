import pandas as pd

import subprocess
import matplotlib.pyplot as plt

FILE_PATH = "listed_iperf3_servers.csv"


def part_1(df):
    return

def part_2(df):
    mapping = {}

    for idx, row in df.head(5).iterrows():
        print("running traceroute for ", row["IP/HOST"])

        traceroute_result = subprocess.run([
                "traceroute", "-n", "-q", "1", row["IP/HOST"],
            ], capture_output=True, text=True)
        lines = traceroute_result.stdout.splitlines()

        # for part (b)
        latencies = []
        # for part (c)
        num_hops = lines[-1].split()[0]
        final_latency = float(lines[-1].split()[-2])

        for line in lines:
            splt = line.split()
            if len(splt) == 4:
                # valid line
                latencies.append(float(splt[-2]))
        
        # for part (b)
        per_hop_latencies = [latencies[i] - latencies[i - 1] for i in range(1, len(latencies))]

        mapping[row["IP/HOST"]] = {}
        mapping[row["IP/HOST"]]["per_hop_latencies"] = per_hop_latencies
        mapping[row["IP/HOST"]]["num_hops"] = num_hops
        mapping[row["IP/HOST"]]["final_latency"] = final_latency
        mapping[row["IP/HOST"]]["last_line"] = lines[-1]

    return mapping

def plot_scatter(mapping, path="scatter_hopcount_rtt.png"):
    """(c) Scatter: hop count vs total RTT, one point per destination."""
    fig, ax = plt.subplots(figsize=(7, 6))
    i = 0
    for dest, data in mapping.items():
        if dest not in data["last_line"]:
            print(f"[!] {dest} never reached destination, skipping")
            continue
        hop_count = int(data["num_hops"])
        total_rtt = data["final_latency"]
        ax.scatter(hop_count, total_rtt, s=80)
        ax.annotate(dest, (hop_count, total_rtt), textcoords="offset points",
                    xytext=(6, 4 + (i % 5) * 12), fontsize=8)
        i += 1

    ax.set_xlabel("Hop count (responsive hops to destination)")
    ax.set_ylabel("Total RTT to destination (ms)")
    ax.set_title("Hop count vs. round-trip time")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"[*] Saved {path}")

if __name__ == "__main__":
    df = pd.read_csv(FILE_PATH)

    part_1(df)
    mapping = part_2(df)
    plot_scatter(mapping)