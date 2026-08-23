#!/usr/bin/env python3
"""Apply hospital metadata via POST /hospitals/bulk-metadata.

Usage:
    python scripts/apply_hospital_metadata.py

Reads scripts/hospital_metadata.json and sends it to the running app.
"""
import json
import os
import sys
import urllib.request
import urllib.error

METADATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "hospital_metadata.json")
BASE_URL = os.environ.get("APP_URL", "http://localhost:8000")


def main():
    if not os.path.exists(METADATA_PATH):
        print(f"ERROR: {METADATA_PATH} not found")
        sys.exit(1)

    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    hospitals = metadata.get("hospitals", [])
    if not hospitals:
        print("No hospitals in metadata file")
        sys.exit(0)

    print(f"Sending {len(hospitals)} hospitals to {BASE_URL}/hospitals/bulk-metadata ...")

    payload = json.dumps(hospitals).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/hospitals/bulk-metadata",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
            print(f"Done: {result}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code}: {body}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Connection failed: {e.reason}")
        print(f"Make sure the app is running on {BASE_URL}")
        sys.exit(1)


if __name__ == "__main__":
    main()
