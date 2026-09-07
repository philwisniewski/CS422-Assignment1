#!/usr/bin/env python3

# functions were originally in separate files which were written without AI,
# used AI to refactor/combine them into this singular file

from __future__ import annotations

import argparse
import html
import math
import platform
import random
import re
import shutil
import socket
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import requests
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
)

SERVER_LIST_URL = "https://iperf3serverlist.net/"
GEO_URL = "https://freeipapi.com/api/json/{ip}"
IPIFY_URL = "https://api.ipify.org"
DEFAULT_OUTPUT = "output"
DEFAULT_PING_COUNT = 5
DEFAULT_PING_TIMEOUT = 3
DEFAULT_TRACEROUTE_TIMEOUT = 90
DEFAULT_WORKERS = 8
DEFAULT_RANDOM_SEED = 0



def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def clean_ip_or_host(value: str) -> str:
    value = str(value).strip()
    value = re.sub(r"^\s*[\[\(]+|[\]\),;]+$", "", value)
    return value


def numeric(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def run_command(command: List[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        errors="replace",
    )



def load_servers_from_csv(path: Path) -> List[str]:
    df = pd.read_csv(path)
    if df.empty:
        raise ValueError(f"Input CSV is empty: {path}")

    preferred = None
    for col in df.columns:
        if str(col).strip().lower() in {
            "ip/host", "ip", "host", "hostname", "server", "address"
        }:
            preferred = col
            break
    if preferred is None:
        preferred = df.columns[0]

    values = []
    for value in df[preferred].dropna().tolist():
        item = clean_ip_or_host(value)
        if item and item.lower() not in {"ip", "host", "ip/host", "hostname"}:
            values.append(item)

    return dedupe(values)


def load_servers_from_web() -> List[str]:
    headers = {"User-Agent": "network-analysis-assignment/1.0"}
    response = requests.get(SERVER_LIST_URL, headers=headers, timeout=20)
    response.raise_for_status()
    text = response.text

    found: List[str] = []

    # Prefer tables when the page exposes one.
    try:
        tables = pd.read_html(text)
        for table in tables:
            for col in table.columns:
                for value in table[col].dropna().tolist():
                    s = clean_ip_or_host(value)
                    if looks_like_ip_or_hostname(s):
                        found.append(s)
    except Exception:
        pass

    # Fallback: extract IPv4 addresses directly from HTML.
    ipv4s = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", html.unescape(text))
    found.extend(ipv4s)

    result = []
    for item in dedupe(found):
        if looks_like_ip_or_hostname(item):
            result.append(item)

    if not result:
        raise RuntimeError(
            "Could not parse server addresses from iperf3serverlist.net. "
            "Provide --input with a CSV containing the server list."
        )
    return result


def looks_like_ip_or_hostname(value: str) -> bool:
    if not value or len(value) > 253:
        return False
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", value):
        try:
            return all(0 <= int(x) <= 255 for x in value.split("."))
        except ValueError:
            return False
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.[A-Za-z]{2,}", value))


def dedupe(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


def get_public_ip() -> Optional[str]:
    try:
        response = requests.get(IPIFY_URL, timeout=10)
        response.raise_for_status()
        ip = response.text.strip()
        return ip if ip else None
    except requests.RequestException as exc:
        print(f"[!] Could not determine public IP: {exc}", file=sys.stderr)
        return None


def geolocate(ip: str, session: requests.Session) -> Optional[dict]:
    for attempt in range(3):
        try:
            response = session.get(GEO_URL.format(ip=ip), timeout=15)
            if response.status_code == 200:
                data = response.json()
                lat = numeric(data.get("latitude"))
                lon = numeric(data.get("longitude"))
                if lat is not None and lon is not None:
                    return {
                        "ip": ip,
                        "latitude": lat,
                        "longitude": lon,
                        "city": data.get("city") or "",
                        "country": data.get("countryName") or data.get("country") or "",
                    }
                return None
            if response.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            return None
        except (requests.RequestException, ValueError):
            time.sleep(1.0 * (attempt + 1))
    return None



def ping_one(host: str, count: int, timeout: int) -> Optional[dict]:
    system = platform.system().lower()

    if system == "windows":
        command = ["ping", "-n", str(count), "-w", str(timeout * 1000), host]
    else:
        # macOS and Linux both support -c; Linux supports -W in seconds.
        command = ["ping", "-c", str(count), host]

    try:
        result = run_command(command, timeout=max(20, count * timeout + 5))
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"[!] Ping failed for {host}: {exc}", file=sys.stderr)
        return None

    text = result.stdout + "\n" + result.stderr

    # Unix summary: min/avg/max/stddev = 10.0/12.0/15.0/2.0 ms
    match = re.search(
        r"(?:min/avg/max/(?:mdev|stddev)|round-trip min/avg/max(?:/stddev)?)"
        r"\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms",
        text,
        flags=re.I,
    )
    if match:
        return {
            "host": host,
            "min_rtt": float(match.group(1)),
            "avg_rtt": float(match.group(2)),
            "max_rtt": float(match.group(3)),
            "packets_sent": count,
            "packets_received": count,  # corrected below when detectable
            "packet_loss_pct": 0.0,
        }

    # Windows summary: Minimum = Xms, Maximum = Yms, Average = Zms
    win = re.search(
        r"Minimum\s*=\s*(\d+)ms.*?Maximum\s*=\s*(\d+)ms.*?Average\s*=\s*(\d+)ms",
        text,
        flags=re.I | re.S,
    )
    if win:
        loss = re.search(r"\((\d+)%\s*loss\)", text, flags=re.I)
        loss_pct = float(loss.group(1)) if loss else 0.0
        return {
            "host": host,
            "min_rtt": float(win.group(1)),
            "avg_rtt": float(win.group(3)),
            "max_rtt": float(win.group(2)),
            "packets_sent": count,
            "packets_received": round(count * (1 - loss_pct / 100)),
            "packet_loss_pct": loss_pct,
        }

    # More portable fallback: collect "time=12.3 ms" / "time<1ms".
    samples = []
    for m in re.finditer(r"time[=<]\s*([\d.]+)\s*ms", text, flags=re.I):
        samples.append(float(m.group(1)))
    if samples:
        loss = re.search(r"(\d+(?:\.\d+)?)%\s*packet loss", text, flags=re.I)
        loss_pct = float(loss.group(1)) if loss else max(
            0.0, 100.0 * (count - len(samples)) / count
        )
        return {
            "host": host,
            "min_rtt": min(samples),
            "avg_rtt": statistics.mean(samples),
            "max_rtt": max(samples),
            "packets_sent": count,
            "packets_received": len(samples),
            "packet_loss_pct": loss_pct,
        }

    print(f"[!] No usable ping RTT for {host}", file=sys.stderr)
    return None



def haversine_km(origin: Tuple[float, float],
                 destination: Tuple[float, float]) -> float:
    lat1, lon1 = origin
    lat2, lon2 = destination
    radius = 6371.0088

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))



def find_traceroute_candidates(hosts: List[str], timeout: int, seed: int,
                               target_count: int = 5) -> List[dict]:
    """
    Test traceroute candidates until target_count destinations are successfully
    reached. Candidates are shuffled with a fixed seed for reproducibility.

    This deliberately performs traceroute only after the ping phase has
    completed, so Part 2 can select from destinations that actually support
    end-to-end traceroute rather than choosing arbitrary servers first.
    """
    candidates = list(hosts)
    random.Random(seed).shuffle(candidates)

    successful = []
    print(f"[*] Searching for {target_count} destinations with working traceroute...")

    for host in candidates:
        if len(successful) >= target_count:
            break

        print(f"[*] Testing traceroute candidate: {host}")
        trace = traceroute_one(host, timeout)
        if trace and trace.get("destination_reached"):
            successful.append(trace)
            print(
                f"    accepted {host}: hops={trace['hop_count']}, "
                f"RTT={trace['destination_rtt_ms']:.2f} ms "
                f"({len(successful)}/{target_count})"
            )
        else:
            print(f"    skipped {host}: destination did not respond to traceroute")

    return successful


def traceroute_one(host: str, timeout: int) -> Optional[dict]:
    if shutil.which("traceroute") is None:
        print(
            "[!] traceroute is not installed. Install it and rerun.",
            file=sys.stderr,
        )
        return None

    command = ["traceroute", "-n", "-q", "3", host]

    try:
        result = run_command(command, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[!] Traceroute timed out for {host}", file=sys.stderr)
        return None
    except FileNotFoundError:
        return None

    text = result.stdout + "\n" + result.stderr
    lines = text.splitlines()

    hop_rows = []
    destination_reached = False

    # Typical Unix line:
    #  1  192.168.1.1  1.123 ms  1.456 ms  1.789 ms
    for line in lines:
        match = re.match(r"^\s*(\d+)\s+(.*)$", line)
        if not match:
            continue

        hop_num = int(match.group(1))
        rest = match.group(2)

        if "*" in rest and not re.search(r"\d+(?:\.\d+)?\s*ms", rest):
            hop_rows.append({
                "hop": hop_num,
                "address": "*",
                "rtt_ms": None,
                "responsive": False,
            })
            continue

        # Extract all reported RTT samples from this hop.
        samples = [
            float(x) for x in re.findall(
                r"(?<![\d.])(\d+(?:\.\d+)?)\s*ms", rest, flags=re.I
            )
        ]

        address_match = re.search(
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b", rest
        )
        address = address_match.group(0) if address_match else "unknown"

        if samples:
            hop_rtt = statistics.mean(samples)
            hop_rows.append({
                "hop": hop_num,
                "address": address,
                "rtt_ms": hop_rtt,
                "responsive": True,
            })
        else:
            hop_rows.append({
                "hop": hop_num,
                "address": address if address else "*",
                "rtt_ms": None,
                "responsive": False,
            })

    responsive = [h for h in hop_rows if h["responsive"] and h["rtt_ms"] is not None]
    if not responsive:
        print(f"[!] Traceroute produced no responsive hops for {host}", file=sys.stderr)
        return None

    # A traceroute "final hop" is considered reached if the final numbered hop
    # contains the destination address, or its address resolves to the destination.
    try:
        destination_ip = socket.gethostbyname(host)
    except socket.gaierror:
        destination_ip = None

    last_numbered = max((h["hop"] for h in hop_rows), default=0)
    final_candidates = [h for h in responsive if h["hop"] == last_numbered]
    final_hop = final_candidates[-1] if final_candidates else responsive[-1]

    if destination_ip and final_hop["address"] == destination_ip:
        destination_reached = True
    elif host == final_hop["address"]:
        destination_reached = True
    elif any(
        h["responsive"] and destination_ip and h["address"] == destination_ip
        for h in hop_rows
    ):
        destination_reached = True

    # Some traceroute implementations omit/alter the destination IP text.
    # If the command succeeded and the last responsive hop is the destination,
    # treat it as reached. Otherwise retain the explicit status.
    if result.returncode == 0 and final_hop["hop"] == last_numbered:
        if destination_ip is None:
            destination_reached = True

    if not destination_reached:
        print(
            f"[!] Traceroute did not clearly reach destination {host}; "
            "marking it non-responsive.",
            file=sys.stderr,
        )
        return None

    return {
        "host": host,
        "hops": hop_rows,
        "responsive_hops": len(responsive),
        "hop_count": final_hop["hop"],
        "destination_rtt_ms": final_hop["rtt_ms"],
        "destination_reached": True,
        "raw_output": text,
    }


# -----------------------------
# Statistics / plots
# -----------------------------

def pearson(x: List[float], y: List[float]) -> Optional[float]:
    if len(x) < 2 or len(y) < 2:
        return None
    try:
        return statistics.correlation(x, y)
    except (AttributeError, statistics.StatisticsError):
        # Compatibility fallback.
        mx, my = statistics.mean(x), statistics.mean(y)
        num = sum((a - mx) * (b - my) for a, b in zip(x, y))
        den = math.sqrt(
            sum((a - mx) ** 2 for a in x) *
            sum((b - my) ** 2 for b in y)
        )
        return num / den if den else None


def make_distance_rtt_plot(rows: List[dict], path: Path) -> None:
    data = [r for r in rows if r.get("distance_km") is not None]
    fig, ax = plt.subplots(figsize=(8, 6))

    for label, key in [
        ("Minimum RTT", "min_rtt"),
        ("Average RTT", "avg_rtt"),
        ("Maximum RTT", "max_rtt"),
    ]:
        ax.scatter(
            [r["distance_km"] for r in data],
            [r[key] for r in data],
            label=label,
            alpha=0.75,
        )

    ax.set_xlabel("Geographical distance from source (km)")
    ax.set_ylabel("RTT (ms)")
    ax.set_title("Distance vs. Round-Trip Time")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def make_stacked_bar_plot(traces: List[dict], path: Path) -> None:
    if not traces:
        return

    fig, ax = plt.subplots(figsize=(11, 7))
    x = list(range(len(traces)))
    bottoms = [0.0] * len(traces)
    max_hops = max(len(t["hops"]) for t in traces)

    trace_deltas = []
    for trace in traces:
        deltas = {}
        last_rtt = 0.0
        for h in sorted(trace["hops"], key=lambda h: h["hop"]):
            if h["rtt_ms"] is not None:
                deltas[h["hop"]] = h["rtt_ms"] - last_rtt
                last_rtt = h["rtt_ms"]
            else:
                deltas[h["hop"]] = 0.0
        trace_deltas.append(deltas)

    # Each segment represents the cumulative RTT reported by traceroute for
    # that responsive hop. Non-responsive hops are left empty rather than
    # inventing latency values.
    for hop_num in range(1, max_hops + 1):
        values = [d.get(hop_num, 0.0) for d in trace_deltas]

        ax.bar(
            x,
            values,
            bottom=bottoms,
            label=f"Hop {hop_num}",
        )
        bottoms = [a + b for a, b in zip(bottoms, values)]

    ax.set_xticks(x)
    ax.set_xticklabels([t["host"] for t in traces], rotation=25, ha="right")
    ax.set_ylabel("Cumulative hop RTT (ms)")
    ax.set_xlabel("Destination")
    ax.set_title("Traceroute RTT Breakdown by Hop")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def make_hop_scatter_plot(traces: List[dict], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 6))
    x = [t["hop_count"] for t in traces]
    y = [t["destination_rtt_ms"] for t in traces]

    ax.scatter(x, y, s=80)
    for trace in traces:
        ax.annotate(
            trace["host"],
            (trace["hop_count"], trace["destination_rtt_ms"]),
            xytext=(6, 5),
            textcoords="offset points",
            fontsize=8,
        )

    ax.set_xlabel("Hop count to destination")
    ax.set_ylabel("Destination RTT (ms)")
    ax.set_title("Hop Count vs. Round-Trip Time")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)



class NetworkReport:
    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.doc = SimpleDocTemplate(
            str(output_path),
            pagesize=letter,
            rightMargin=45,
            leftMargin=45,
            topMargin=45,
            bottomMargin=45,
        )

        styles = getSampleStyleSheet()
        self.title_style = ParagraphStyle(
            "ReportTitle", parent=styles["Title"], alignment=TA_CENTER,
            fontSize=20, spaceAfter=20
        )
        self.heading_style = ParagraphStyle(
            "Heading", parent=styles["Heading1"], fontSize=15,
            spaceBefore=15, spaceAfter=10
        )
        self.subheading_style = ParagraphStyle(
            "SubHeading", parent=styles["Heading2"], fontSize=12,
            spaceBefore=10, spaceAfter=6
        )
        self.body_style = ParagraphStyle(
            "Body", parent=styles["BodyText"], fontSize=9.5,
            leading=13, spaceAfter=8
        )
        self.small_style = ParagraphStyle(
            "Small", parent=styles["BodyText"], fontSize=7.5,
            leading=9, spaceAfter=5
        )
        self.story = []

    def p(self, text: str, style=None):
        self.story.append(Paragraph(str(text), style or self.body_style))

    def add_title(self, text):
        self.story.append(Paragraph(text, self.title_style))
        self.story.append(Spacer(1, 8))

    def add_heading(self, text):
        self.story.append(Paragraph(text, self.heading_style))

    def add_subheading(self, text):
        self.story.append(Paragraph(text, self.subheading_style))

    def add_image(self, image_path: Path, width=6.6 * inch):
        if not image_path.exists():
            return
        image = Image(str(image_path))
        ratio = image.imageHeight / float(image.imageWidth)
        image.drawWidth = width
        image.drawHeight = width * ratio
        self.story.append(Spacer(1, 8))
        self.story.append(image)
        self.story.append(Spacer(1, 12))

    def add_table(self, data, widths=None, fontsize=7):
        converted = [
            [Paragraph(str(cell), self.small_style) for cell in row]
            for row in data
        ]
        table = Table(converted, colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTSIZE", (0, 0), (-1, -1), fontsize),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        self.story.append(table)
        self.story.append(Spacer(1, 10))

    def page_break(self):
        self.story.append(PageBreak())

    def build(self):
        self.doc.build(self.story)


def build_report(
    report_path: Path,
    plot_distance: Path,
    plot_stacked: Path,
    plot_hops: Path,
    ping_rows: List[dict],
    traces: List[dict],
    source_ip: Optional[str],
    source_geo: Optional[dict],
    input_description: str,
):
    report = NetworkReport(report_path)

    report.add_title("Network Performance Analysis")
    report.p(
        f"<b>Experiment date:</b> {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}"
    )
    report.p(f"<b>Input:</b> {input_description}")
    if source_ip:
        source_text = f"Source public IP: {source_ip}"
        if source_geo:
            source_text += (
                f" (approx. {source_geo['latitude']:.5f}, "
                f"{source_geo['longitude']:.5f}; "
                f"{source_geo.get('city','')}, {source_geo.get('country','')})"
            )
        report.p(source_text)

    # Part 1
    report.add_heading("1. Ping Test and Round-Trip Time (RTT)")
    report.p(
        "For each destination that responded to ICMP ping, the script recorded "
        "minimum, average, and maximum RTT from the local machine. Public IP "
        "geolocation was queried for the source and destination addresses, and "
        "great-circle distance was calculated using the Haversine formula."
    )

    if ping_rows:
        table = [["Destination", "Min RTT (ms)", "Avg RTT (ms)", "Max RTT (ms)",
                  "Loss", "Latitude", "Longitude", "Distance (km)"]]
        for r in ping_rows:
            table.append([
                r["host"],
                f"{r['min_rtt']:.2f}",
                f"{r['avg_rtt']:.2f}",
                f"{r['max_rtt']:.2f}",
                f"{r['packet_loss_pct']:.1f}%",
                f"{r['latitude']:.5f}" if r.get("latitude") is not None else "N/A",
                f"{r['longitude']:.5f}" if r.get("longitude") is not None else "N/A",
                f"{r['distance_km']:.1f}" if r.get("distance_km") is not None else "N/A",
            ])
        report.add_table(table, widths=[
            1.05*inch, .65*inch, .65*inch, .65*inch,
            .45*inch, .7*inch, .7*inch, .75*inch
        ])

    report.add_subheading("Distance vs. RTT")
    report.add_image(plot_distance)
    x = [r["distance_km"] for r in ping_rows if r.get("distance_km") is not None]
    y = [r["avg_rtt"] for r in ping_rows if r.get("distance_km") is not None]
    corr = pearson(x, y)

    if corr is None:
        corr_text = "There were not enough complete observations to calculate a Pearson correlation."
    else:
        strength = (
            "strong" if abs(corr) >= 0.7 else
            "moderate" if abs(corr) >= 0.4 else
            "weak"
        )
        direction = "positive" if corr >= 0 else "negative"
        corr_text = (
            f"The Pearson correlation between geographical distance and average RTT "
            f"was {corr:.3f}, indicating a {strength} {direction} linear relationship "
            f"for this particular measurement set."
        )

    report.p(
        "<b>Interpretation:</b> Distance generally places a lower bound on network "
        "latency because packets must travel farther which takes longer through the network."
        " However, RTT is not determined by geographic "
        "distance alone, as routing paths can be longer than the straight-line path, "
        "and congestion and (lack of) infrastructure quality can "
        "increase RTT."
    )
    report.p(corr_text)
    report.p(
        "<b>Minimum vs. maximum RTT:</b> Minimum RTT is useful as a best-observed "
        "latency under relatively favorable conditions. A much larger maximum RTT "
        "than minimum RTT indicates increased volatility in RTT time, which may result from increased "
        "queueing, congestion, scheduling, or route changes. A large minimum RTT "
        "relative to other destinations often indicates a longer or "
        "less direct path."
    )

    # Part 2
    report.add_heading("2. Latency Breakdown")
    report.p(
        "Destinations were randomized with a fixed seed, then tested until up to "
        "five destinations with successful end-to-end traceroutes were found. "
        "Traceroute used three probes per hop. Non-responsive intermediate hops "
        "are retained as missing values; they are not assigned invented latency. "
        "A destination is included in the analysis only when traceroute clearly "
        "reaches it."
    )

    if traces:
        table = [["Destination", "Final hop", "Responsive hops", "Destination RTT (ms)"]]
        for t in traces:
            table.append([
                t["host"],
                t["hop_count"],
                t["responsive_hops"],
                f"{t['destination_rtt_ms']:.2f}",
            ])
        report.add_table(table, widths=[2.5*inch, 1*inch, 1.2*inch, 1.4*inch])

    report.add_subheading("Traceroute Latency Breakdown")
    report.add_image(plot_stacked)
    report.p(
        "<b>Plot note:</b> calculates RTT deltas by subtracting previous hop RTT from current hop RTT. Non-responsive hops are left empty rather than inventing latency values."
    )

    report.add_subheading("Hop Count vs. RTT")
    report.add_image(plot_hops)

    hx = [t["hop_count"] for t in traces]
    hy = [t["destination_rtt_ms"] for t in traces]
    hop_corr = pearson(hx, hy)

    if hop_corr is None:
        hop_text = "There were not enough complete traceroute observations to calculate a correlation."
    else:
        hop_text = (
            f"The Pearson correlation between hop count and destination RTT was "
            f"{hop_corr:.3f}. With only five destinations, this is descriptive rather "
            f"than statistically conclusive."
        )

    report.p(
        "<b>Interpretation:</b> More hops often correspond to higher RTT because each "
        "additional router introduces propagation, transmission, processing, and "
        "queueing opportunities. However, this is not always the case, as some hops are much"
        " closer to each other than others and can take less time."
    )
    report.p(hop_text)
    report.p(
        "<b>Corner cases:</b> A '*' in traceroute means that a probe did not receive "
        "a response from that hop. This does not necessarily mean packets cannot "
        "pass through that router. The script skips destinations that fail to reach "
        "the final destination so that the hop-count/RTT analysis does not treat "
        "incomplete paths as successful measurements."
    )

    report.add_heading("Reproducibility and Code Map")
    report.p(
        "This report was generated by the same one-shot Python script used to run "
        "the measurements and create the figures. The relevant code sections are:"
    )
    code_table = [
        ["Task", "Functions / section"],
        ["Input / server discovery", "load_servers_from_csv(), load_servers_from_web()"],
        ["Public IP + geolocation", "get_public_ip(), geolocate()"],
        ["Ping / RTT", "ping_one()"],
        ["Distance calculation", "haversine_km()"],
        ["Traceroute", "traceroute_one()"],
        ["Distance-vs-RTT plot", "make_distance_rtt_plot()"],
        ["Stacked latency plot", "make_stacked_bar_plot()"],
        ["Hop-count-vs-RTT plot", "make_hop_scatter_plot()"],
        ["PDF report", "NetworkReport, build_report()"],
        ["One-shot orchestration", "main()"],
    ]
    report.add_table(code_table, widths=[1.8*inch, 4.8*inch])

    report.build()


def main():
    parser = argparse.ArgumentParser(
        description="Run the complete network RTT/traceroute experiment and generate a PDF."
    )
    parser.add_argument(
        "--input", "-i", type=Path, default=Path("listed_iperf3_servers.csv"),
        help="CSV containing IP addresses/hosts (default: listed_iperf3_servers.csv)."
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=Path(DEFAULT_OUTPUT),
        help="Output directory (default: output)"
    )
    parser.add_argument(
        "--download-list", action="store_true",
        help="Download the public iperf3 server list instead of using the local CSV."
    )
    parser.add_argument(
        "--ping-count", type=int, default=DEFAULT_PING_COUNT,
        help="Number of ICMP echo requests per destination."
    )
    parser.add_argument(
        "--traceroute-timeout", type=int, default=DEFAULT_TRACEROUTE_TIMEOUT,
        help="Maximum seconds allowed for each traceroute."
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help="Maximum concurrent ping/geolocation workers."
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_RANDOM_SEED,
        help="Random seed used to select five traceroute destinations."
    )
    args = parser.parse_args()

    if args.ping_count < 1:
        parser.error("--ping-count must be >= 1")
    if args.workers < 1:
        parser.error("--workers must be >= 1")

    ensure_dir(args.output)

    print("[*] Loading server list...")
    if args.download_list:
        servers = load_servers_from_web()
        input_description = SERVER_LIST_URL
    else:
        if not args.input.exists():
            raise FileNotFoundError(
                f"Input file not found: {args.input}. "
                "Create listed_iperf3_servers.csv or use --download-list."
            )
        servers = load_servers_from_csv(args.input)
        input_description = str(args.input)

    if not servers:
        raise RuntimeError("No servers were found.")

    print(f"[*] Loaded {len(servers)} destinations.")

    source_ip = get_public_ip()
    if source_ip:
        servers = dedupe(servers + [source_ip])
        print(f"[*] Public source IP: {source_ip}")
    else:
        print("[!] Continuing without source public IP.", file=sys.stderr)

    session = requests.Session()
    source_geo = geolocate(source_ip, session) if source_ip else None

    # Ping + geolocation in parallel.
    ping_results: Dict[str, dict] = {}
    geo_results: Dict[str, dict] = {}

    print("[*] Running ping tests...")
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(ping_one, host, args.ping_count, DEFAULT_PING_TIMEOUT): host
            for host in servers
        }
        for future in as_completed(futures):
            host = futures[future]
            try:
                result = future.result()
                if result:
                    ping_results[host] = result
                    print(
                        f"    ping {host}: "
                        f"min={result['min_rtt']:.2f} "
                        f"avg={result['avg_rtt']:.2f} "
                        f"max={result['max_rtt']:.2f} ms"
                    )
            except Exception as exc:
                print(f"[!] Ping worker failed for {host}: {exc}", file=sys.stderr)

    print("[*] Looking up geolocation...")
    # Keep requests modest to avoid hammering the public API.
    with ThreadPoolExecutor(max_workers=min(args.workers, 6)) as executor:
        futures = {
            executor.submit(geolocate, host, session): host
            for host in servers
        }
        for future in as_completed(futures):
            host = futures[future]
            try:
                result = future.result()
                if result:
                    geo_results[host] = result
            except Exception as exc:
                print(f"[!] Geolocation failed for {host}: {exc}", file=sys.stderr)

    ping_rows = []
    origin = (
        (source_geo["latitude"], source_geo["longitude"])
        if source_geo else None
    )

    for host, ping in ping_results.items():
        geo = geo_results.get(host)
        row = dict(ping)
        if geo:
            row["latitude"] = geo["latitude"]
            row["longitude"] = geo["longitude"]
            row["city"] = geo.get("city", "")
            row["country"] = geo.get("country", "")
            if origin:
                row["distance_km"] = haversine_km(
                    origin, (geo["latitude"], geo["longitude"])
                )
            else:
                row["distance_km"] = None
        else:
            row["latitude"] = None
            row["longitude"] = None
            row["city"] = ""
            row["country"] = ""
            row["distance_km"] = None
        ping_rows.append(row)

    ping_rows.sort(key=lambda r: r["host"].lower())

    # Save raw ping/geolocation data.
    ping_csv = args.output / "ping_results.csv"
    pd.DataFrame(ping_rows).to_csv(ping_csv, index=False)

    # Plots.
    distance_plot = args.output / "distance_rtt.png"
    stacked_plot = args.output / "stacked_bar_latencies.png"
    hop_plot = args.output / "scatter_hopcount_rtt.png"

    make_distance_rtt_plot(ping_rows, distance_plot)

    # Part 2: search all ping-successful destinations for endpoints that
    # actually complete traceroute, then keep the first five from a seeded
    # randomized order. This avoids wasting the entire Part 2 sample on
    # servers that block or otherwise fail to answer traceroute.
    candidates = [
        r["host"] for r in ping_rows
        if r["host"] != source_ip and r.get("packet_loss_pct", 100.0) < 100.0
    ]
    if len(candidates) < 5:
        candidates = [r["host"] for r in ping_rows if r["host"] != source_ip]

    traces = find_traceroute_candidates(
        candidates,
        timeout=args.traceroute_timeout,
        seed=args.seed,
        target_count=5,
    )

    print(
        f"[*] Completed traceroutes: {len(traces)} "
        f"(requested up to 5)"
    )

    if traces:
        make_stacked_bar_plot(traces, stacked_plot)
        make_hop_scatter_plot(traces, hop_plot)
    else:
        # Create placeholder figures so the report still builds.
        for path, title in [
            (stacked_plot, "No completed traceroutes"),
            (hop_plot, "No completed traceroutes"),
        ]:
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.text(0.5, 0.5, title, ha="center", va="center")
            ax.axis("off")
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)

    # Save traceroute data.
    trace_rows = []
    for trace in traces:
        for hop in trace["hops"]:
            trace_rows.append({
                "destination": trace["host"],
                "hop": hop["hop"],
                "address": hop["address"],
                "rtt_ms": hop["rtt_ms"],
                "responsive": hop["responsive"],
                "destination_reached": trace["destination_reached"],
                "destination_hop_count": trace["hop_count"],
                "destination_rtt_ms": trace["destination_rtt_ms"],
            })
    pd.DataFrame(trace_rows).to_csv(
        args.output / "traceroute_results.csv", index=False
    )

    # Save the selected destinations and raw traceroutes.
    with open(args.output / "traceroute_raw.txt", "w", encoding="utf-8") as f:
        for trace in traces:
            f.write(f"\n{'=' * 80}\n")
            f.write(f"Destination: {trace['host']}\n")
            f.write(f"{'=' * 80}\n")
            f.write(trace["raw_output"])
            f.write("\n")

    report_path = args.output / "network_analysis_report.pdf"
    build_report(
        report_path=report_path,
        plot_distance=distance_plot,
        plot_stacked=stacked_plot,
        plot_hops=hop_plot,
        ping_rows=ping_rows,
        traces=traces,
        source_ip=source_ip,
        source_geo=source_geo,
        input_description=input_description,
    )

    print("\n[*] COMPLETE")
    print(f"    PDF: {report_path}")
    print(f"    Ping data: {ping_csv}")
    print(f"    Traceroute data: {args.output / 'traceroute_results.csv'}")
    print(f"    Plots: {distance_plot}, {stacked_plot}, {hop_plot}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Interrupted by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"[!] Fatal error: {exc}", file=sys.stderr)
        sys.exit(1)
