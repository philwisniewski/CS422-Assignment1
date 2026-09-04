from part_1 import part_1
from part_2 import part_2, plot_scatter

FILE_PATH = "listed_iperf3_servers.csv"

if __name__ == "__main__":
    import pandas as pd
    import sys

    part = ""
    if sys.argv[0].startswith("python"):
        if len(sys.argv) < 3:
            print("Usage: {sys.argv[0]} {sys.argv[1]} <part1 | part2>")
            exit(0)
        
        part = sys.argv[2]
        if part != "part1" and part != "part2":
            print("Usage: {sys.argv[0]} {sys.argv[1]} <part1 | part2>")
            exit(0)
    else:
        if len(sys.argv) < 2:
            print("Usage: ./{sys.argv[0]} <part1 | part2>")
            exit(0)
        part = sys.argv[1]
        if part != "part1" and part != "part2":
            print("Usage: ./{sys.argv[0]} <part1 | part2>")
            exit(0)
    
    df = pd.read_csv(FILE_PATH)
    if part == "part1":
        ips = df.iloc[:, 0].tolist()
        part_1(ips)
    else:
        mapping = part_2(df)
        plot_scatter(mapping)