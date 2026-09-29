import json
import time
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

DATA_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "events.json"
)


def load_events():
    with open(DATA_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


@router.get("/events")
def get_events():
    return load_events()


@router.get("/stats")
def get_stats():
    events = load_events()

    total_events = len(events)

    critical_issues = sum(
        1
        for event in events
        if event["severity"] == "High"
    )

    routes_monitored = len(
        set(event["route"] for event in events)
    )

    average_confidence = (
        round(
            sum(event["confidence"] for event in events)
            / total_events,
            1,
        )
        if total_events
        else 0
    )

    return {
        "total_events": total_events,
        "critical_issues": critical_issues,
        "routes_monitored": routes_monitored,
        "ai_confidence": average_confidence,
    }


@router.get("/detections")
def get_detections():
    events = load_events()

    if not events:
        return {
            "status": "idle",
            "model": "YOLOv8",
            "detections": [],
        }

    # Change the displayed detection every 5 seconds
    cycle = int(time.time() // 5)
    current_event = events[cycle % len(events)]

    return {
        "status": "processing",
        "model": "YOLOv8",
        "detections": [current_event],
    }