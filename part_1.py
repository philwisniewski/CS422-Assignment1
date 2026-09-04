import matplotlib.pyplot as plt
import math
import requests
import subprocess
from concurrent.futures import ThreadPoolExecutor
import time
import sys

# https://stackoverflow.com/questions/19412462/getting-distance-between-two-points-based-on-latitude-longitude
def distance(origin, destination):
    """
    Calculate the Haversine distance.

    Parameters
    ----------
    origin : tuple of float
        (lat, long)
    destination : tuple of float
        (lat, long)

    Returns
    -------
    distance_in_km : float

    Examples
    --------
    >>> origin = (48.1372, 11.5756)  # Munich
    >>> destination = (52.5186, 13.4083)  # Berlin
    >>> round(distance(origin, destination), 1)
    504.2
    """
    lat1, lon1 = origin
    lat2, lon2 = destination
    radius = 6371  # km

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) * math.sin(dlat / 2) +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) * math.sin(dlon / 2))
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    d = radius * c

    return d

def ping_one(ip):
  # retry 3x
  for _ in range(3):
    # send 5 packets and take average RTT
    command = ["ping", "-c", "5", ip]
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0:
      print(f"{ip}: ping failed", file=sys.stderr)
      continue
    stats = result.stdout.decode().splitlines()[-1]
    min_time, avg_time, max_time, stddev = stats.split(" ")[3].split("/")
    return (ip, min_time, avg_time, max_time)

def geolocate_one(ip):
  # retry 3x
  for _ in range(3):
    res = requests.get(f"https://freeipapi.com/api/json/{ip}")
    if res.status_code != 200:
      print(f"{ip}: geolocation failed", file=sys.stderr)
      continue
    geo_data = res.json()
    if geo_data['latitude'] is None or geo_data['longitude'] is None:
      # unknown location
      return
    return (ip, geo_data['latitude'], geo_data['longitude'])

def part_1(ips):
  my_ip = requests.get("https://api.ipify.org").text

  my_location = geolocate_one(my_ip)
  if my_location is None:
    return
  my_location = my_location[1:]
  print(f"my ip: {my_ip}, lat: {my_location[0]}, long: {my_location[1]}")

  ping_results = {}
  geo_results = {}

  with ThreadPoolExecutor(max_workers=10) as exec:
    results = exec.map(ping_one, ips)
    for ping in results:
      if ping is None:
        continue
      ip = ping[0]
      times = (float(t) for t in ping[1:])
      # ip : avg
      ping_results[ip] = times

  with ThreadPoolExecutor(max_workers=10) as exec:
    before = 0
    for i in range(0, len(ips), 30):
      now = time.time()
      if now - before < 60:
        print("geolocation: waiting to avoid rate limit")
        time.sleep(now - before + 1)
      before = now

      cur_ips = ips[i:i + 30]
      results = exec.map(geolocate_one, cur_ips)
      for geo in results:
        if geo is None:
          continue
        geo_results[geo[0]] = distance(my_location, (geo[1], geo[2]))

  x = []
  min_times = []
  avg_times = []
  max_times = []
  for ip in ping_results:
    if ip in geo_results:
      min_time, avg_time, max_time = ping_results[ip]
      print(f"{ip}: min {min_time} ms, avg {avg_time} ms, max {max_time} ms, distance {geo_results[ip]} km")
      x.append(geo_results[ip])
      min_times.append(min_time)
      avg_times.append(avg_time)
      max_times.append(max_time)

  plt.scatter(x, min_times, label="min RTT")
  plt.scatter(x, avg_times, label="avg RTT")
  plt.scatter(x, max_times, label="max RTT")
  plt.legend(loc='lower right')
  plt.xlabel("Distance from Purdue (km)")
  plt.ylabel("RTT (ms)")

  path = "distance_rtt.png"
  plt.savefig(path, dpi=150)
  plt.close()

  print(f"[*] Saved {path}")
