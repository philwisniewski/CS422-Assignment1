import pandas as pd

import subprocess

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

    return

if __name__ == "__main__":
    df = pd.read_csv(FILE_PATH)

    part_1(df)
    part_2(df)
