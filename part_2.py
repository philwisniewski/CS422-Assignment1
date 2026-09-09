import subprocess
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statistics import mean

def part_2(df, num_rows=5, max_hops=30):
    mapping = {}

    for idx, row in df.sample(frac=1, random_state=0).iterrows():
        if len(mapping) >= num_rows:
            break

        print("--- Running traceroute for", row["IP/HOST"], "---")

        traceroute_result = subprocess.run([
                "traceroute", "-m", f"{max_hops+1}", "-w", "1", "-q", "4", "-n", row["IP/HOST"],
            ], capture_output=True, text=True)
        lines = traceroute_result.stdout.splitlines()

        # for part (b)
        latencies = []

        cur_hop = 1
        for line in lines:
            items = line.split()

            # update to current hop number
            if items[0] == str(cur_hop + 1):
                cur_hop += 1

            # ignore hop num in further line parsing
            if items[0] == str(cur_hop):
                items = items[1:]

            # allocate current hop's space in latencies list if necessary
            if len(latencies) < cur_hop:
                latencies.append([])

            for latency_str in items:
                if latency_str.count(".") > 1:
                    continue

                # skip anything that isn't a latency value
                if latency_str.count(".") != 1:
                    continue

                latency = float(latency_str)
                latencies[-1].append(latency)

        # for part (b)
        # calculate average latency for each hop if not all invalid
        avg_latencies = [mean(lats) for lats in latencies if lats]

        # for part (c)
        num_hops = cur_hop

        if num_hops > max_hops or not avg_latencies:
            print("Status: Non-responsive")
            print()
            continue

        final_latency = avg_latencies[-1]

        # calculate latency diff between each hop
        per_hop_latencies = []
        prev = 0.0
        for lat in avg_latencies:
            total_lat = min(final_latency, max(prev, lat))
            per_hop_latencies.append(total_lat - prev)
            prev = total_lat

        mapping[row["IP/HOST"]] = {}
        mapping[row["IP/HOST"]]["avg_latencies"] = avg_latencies
        mapping[row["IP/HOST"]]["per_hop_latencies"] = per_hop_latencies
        mapping[row["IP/HOST"]]["num_hops"] = num_hops
        mapping[row["IP/HOST"]]["final_latency"] = final_latency

        print("Avg Latencies per Hop:", avg_latencies)
        print("Per Hop Latencies:", per_hop_latencies)
        print("Num Hops:", num_hops)
        print("Final Latency:", final_latency)
        print("Status: Responsive")
        print()

    return mapping

def plot_scatter(mapping, path="scatter_hopcount_rtt.png"):
    fig, ax = plt.subplots(figsize=(7, 6))
    i = 0
    for dest, data in mapping.items():
        # if dest not in data["last_line"]:
        #    print(f"[!] {dest} never reached destination, skipping")
        #    continue
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
    ax.margins(0.15)
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[*] Saved {path}")


def plot_stacked_bar(mapping, path="stacked_bar_latencies.png"):
    ips = []
    per_hop_latencies = []
    for k, v in mapping.items():
        ips.append(k)
        per_hop_latencies.append(v["per_hop_latencies"])

    max_hops = max(len(hops) for hops in per_hop_latencies)
    padded_latencies = []
    for hops in per_hop_latencies:
        # pad the end with zeros so that the dataframe will be rectangular
        padded = hops + [0] * (max_hops - len(hops))
        padded_latencies.append(padded)

    columns = [
        "IP Address",
        *[f"Hop #{i + 1}" for i in range(max_hops)]
    ]

    data = [
        [ips[i], *padded_latencies[i]]
        for i in range(len(ips))
    ]

    df = pd.DataFrame(data, columns=columns)
    ax = df.plot(x="IP Address", kind='bar', stacked=True, title="Per Hop Latencies by IP Address")
    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1), ncol=2, fontsize=8)
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[*] Saved {path}")
