"""Snapshot current backend clusters and optionally send WhatsApp alerts."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(url, *, payload=None):
    body = None
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = Request(url, data=body, headers=headers, method=method)
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def cluster_events(response, limit):
    events = response.get("events")
    if not isinstance(events, list):
        raise ValueError("Backend response must contain an events list")
    clusters = [
        event for event in events
        if isinstance(event, dict)
        and str(event.get("id", "")).startswith(
            ("infrastructure-", "congestion_bottleneck-")
        )
    ]
    return clusters[:limit]


def build_dispatch_payload(cluster, recipient):
    try:
        latitude = float(cluster["lat"])
        longitude = float(cluster["lng"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Cluster is missing numeric latitude/longitude") from exc
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        raise ValueError("Cluster coordinates must be finite numbers")

    event_type = str(cluster.get("event_type", "hazard"))
    hazard = str(cluster.get("type", "unknown"))
    members = cluster.get("members", 1)
    maps_url = f"https://www.google.com/maps?q={latitude:.6f},{longitude:.6f}"
    message = (
        f"SmartRath field alert: {hazard} ({event_type}); "
        f"{members} detections in the cluster at "
        f"{latitude:.6f}, {longitude:.6f}."
    )
    return {
        "to": recipient,
        "message": message,
        "google_maps_url": maps_url,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Snapshot current DBSCAN clusters and prepare WhatsApp alerts."
    )
    parser.add_argument("--to", required=True, help="Recipient number with country code")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument(
        "--dispatcher-url",
        default="http://localhost:3001/api/dispatch-alert",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--send",
        action="store_true",
        help="POST each prepared alert to the local WhatsApp gateway",
    )
    parser.add_argument(
        "--snapshot-file",
        help="Optional path to save the fetched clusters and prepared payloads as JSON",
    )
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    return args


def main():
    args = parse_args()
    api_url = args.api_url.rstrip("/")
    snapshot = request_json(f"{api_url}/api/events")
    clusters = cluster_events(snapshot, args.limit)
    prepared = [build_dispatch_payload(cluster, args.to) for cluster in clusters]

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cluster_count": len(clusters),
        "clusters": clusters,
        "dispatches": prepared,
        "sent": False,
    }
    if args.snapshot_file:
        output = Path(args.snapshot_file)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"[dispatch] snapshot saved to {output}")

    if not prepared:
        print("[dispatch] no current infrastructure or congestion clusters")
        return

    for index, dispatch in enumerate(prepared, start=1):
        print(f"[dispatch] prepared {index}/{len(prepared)}: {dispatch['message']}")
        print(f"[dispatch] map: {dispatch['google_maps_url']}")
        if args.send:
            response = request_json(args.dispatcher_url, payload=dispatch)
            print(f"[dispatch] gateway response: {json.dumps(response)}")

    if args.send:
        result["sent"] = True
    else:
        print("[dispatch] dry run only; pass --send to send through WhatsApp")

    if args.snapshot_file:
        Path(args.snapshot_file).write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    try:
        main()
    except (HTTPError, URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"[dispatch] failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
