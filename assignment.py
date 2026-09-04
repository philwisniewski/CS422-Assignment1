import pandas as pd

import subprocess

FILE_PATH = "listed_iperf3_servers.csv"


def part_1(df):
    return

def part_2(df):
    for idx, row in df.head(5).iterrows():
        traceroute_result = subprocess.run([
                "traceroute", "-n", "-q", "1", row["IP/HOST"],
            ], capture_output=True, text=True)
        lines = result.stdout.splitlines()

        num_hops = lines[-1].split(" ")[0]
        final_latency = float(lines[-1].split(" ")[-2])
        
        for line in lines:
            splt = line.split(" ")
            if len(splt) == 4:
                # valid line
                latencies.append(float(splt[-2]))
        

    return

if __name__ == "__main__":
    df = pd.read_csv(FILE_PATH)

    part_1(df)
    part_2(df)
