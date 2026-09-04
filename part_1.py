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
  for _ in range(3):
    # send 3 packets and take average RTT
    command = ["ping", "-c", "3", ip]
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0:
      print(f"{ip}: ping failed", file=sys.stderr)
      continue
    stats = result.stdout.decode().splitlines()[-1]
    min_time, avg_time, max_time, stddev = stats.split(" ")[3].split("/")
    return (ip, avg_time)

def geolocate_one(ip):
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
      # ip : avg
      ping_results[ping[0]] = float(ping[1])

  with ThreadPoolExecutor(max_workers=10) as exec:
    for i in range(0, len(ips), 30):
      before = time.time()
      cur_ips = ips[i:i + 30]
      results = exec.map(geolocate_one, cur_ips)
      for geo in results:
        if geo is None:
          continue
        geo_results[geo[0]] = distance(my_location, (geo[1], geo[2]))
      after = time.time()
      if after - before < 60:
        print("geolocation: waiting to avoid rate limit")
        time.sleep(after - before + 1)

  x = []
  y = []
  for ip in ping_results:
    if ip in geo_results:
      print(f"{ip}: avg RTT{ping_results[ip]} ms, distance {geo_results[ip]} km")
      x.append(geo_results[ip])
      y.append(ping_results[ip])

  plt.scatter(x, y)
  plt.xlabel("Distance from Purdue (km)")
  plt.ylabel("Average RTT (ms)")
  plt.show()
