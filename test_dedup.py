"""Focused local checks for edge multiplexing and backend spatial analytics."""

import asyncio
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import edge_sim
import server
import dispatch_clusters


class UrbanAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        server.DB_FILE = os.path.join(self.temp_dir.name, "backend.db")
        edge_sim.DB_PATH = os.path.join(self.temp_dir.name, "edge_queue.db")
        server.init_db()
        edge_sim.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def telemetry(bus_id, timestamp, longitude):
        return {
            "bus_id": bus_id,
            "timestamp": timestamp,
            "route_id": "R-12",
            "gps": [18.52, longitude],
            "detection": {
                "class": "pothole_severe",
                "confidence": 0.91,
                "bbox": [10, 20, 50, 70],
            },
            "anpr": {"plate_number": None, "confidence": None},
            "imu": {"accel_g": 0.2},
            "vehicle_count": 0,
            "network_status": "ONLINE",
            "payload_bytes": 250,
        }

    def test_frame_multiplexing_alternates_focus(self):
        self.assertEqual(
            [edge_sim.frame_mode_for_sample(number) for number in range(1, 5)],
            ["infrastructure", "traffic", "infrastructure", "traffic"],
        )

    def test_imu_samples_are_read_from_json(self):
        sample_file = os.path.join(os.path.dirname(__file__), "data", "imu_samples.json")
        simulator = edge_sim.EdgeSimulator(
            "TEST-1", "R-12", "mqtt://localhost:1883", imu_path=sample_file
        )
        self.assertEqual(simulator.next_imu_g(), 0.18)
        self.assertEqual(simulator.next_imu_g(), 0.24)

    def test_toy_onnx_model_outputs_sample_detections(self):
        model_file = os.path.join(os.path.dirname(__file__), "models", "toy_yolo.onnx")
        labels_file = os.path.join(os.path.dirname(__file__), "models", "labels.txt")
        with open(labels_file, encoding="utf-8") as source:
            labels = source.read().splitlines()
        detector = edge_sim.OnnxDetector(model_file, labels)
        detections = detector.detect(edge_sim.np.zeros((640, 640, 3), dtype=edge_sim.np.uint8))
        self.assertEqual([item[0] for item in detections], ["pothole_severe", "vehicle"])

    def test_toy_model_simulates_frames_without_video(self):
        model_file = os.path.join(os.path.dirname(__file__), "models", "toy_yolo.onnx")
        labels_file = os.path.join(os.path.dirname(__file__), "models", "labels.txt")
        with open(labels_file, encoding="utf-8") as source:
            labels = source.read().splitlines()
        simulator = edge_sim.EdgeSimulator(
            "TOY-1",
            "R-12",
            "mqtt://localhost:1883",
            model_path=model_file,
            labels=labels,
            offline_probability=0,
        )
        published = []

        def capture(payload):
            published.append(payload)
            simulator.stop_event.set()
            return True

        with patch.object(simulator, "start_mqtt"), patch.object(
            simulator, "publish", side_effect=capture
        ):
            simulator.run()

        self.assertEqual(published[0]["detection"]["class"], "pothole_severe")
        self.assertEqual(published[0]["frame_mode"], "infrastructure")

    def test_dispatch_payload_links_to_cluster_coordinates(self):
        payload = dispatch_clusters.build_dispatch_payload(
            {
                "id": "infrastructure-0",
                "type": "pothole_severe",
                "event_type": "infrastructure",
                "lat": 18.5204,
                "lng": 73.8567,
                "members": 3,
            },
            "919000000000",
        )
        self.assertEqual(payload["to"], "919000000000")
        self.assertIn("3 detections", payload["message"])
        self.assertEqual(
            payload["google_maps_url"],
            "https://www.google.com/maps?q=18.520400,73.856700",
        )

    def test_anpr_only_invokes_ocr_after_both_triggers(self):
        simulator = edge_sim.EdgeSimulator(
            "TEST-2", "R-12", "mqtt://localhost:1883",
            enable_anpr=True, imu_threshold_g=1.5,
        )
        boxes = [[10, 10, 40, 40]]
        with patch.object(
            simulator, "read_plate",
            return_value={"plate_number": "MH12AB1234", "confidence": 0.93},
        ) as ocr:
            self.assertIsNone(simulator.anpr_for_frame(None, 1.2, boxes)["plate_number"])
            self.assertIsNone(simulator.anpr_for_frame(None, 1.8, [])["plate_number"])
            ocr.assert_not_called()
            result = simulator.anpr_for_frame(None, 1.8, boxes)
        ocr.assert_called_once_with(None, boxes)
        self.assertEqual(result["plate_number"], "MH12AB1234")

    def test_nearby_multi_bus_detections_cluster(self):
        now = time.time()
        server.store_telemetry(self.telemetry("BUS-A", now, 73.85000))
        server.store_telemetry(self.telemetry("BUS-B", now + 1, 73.85005))

        async def run_one_clustering_cycle():
            task = asyncio.create_task(server.cluster_worker())
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_one_clustering_cycle())
        with server.connect_db() as conn:
            cluster = conn.execute(
                "SELECT event_type, members_count FROM clusters"
            ).fetchone()
        self.assertIsNotNone(cluster)
        self.assertEqual(cluster["event_type"], "infrastructure")
        self.assertEqual(cluster["members_count"], 2)

    def test_speed_drop_emits_congestion_and_od_summary(self):
        now = time.time()
        server.store_telemetry(self.telemetry("BUS-SLOW", now, 73.85))
        _, congestion, _ = server.store_telemetry(
            self.telemetry("BUS-SLOW", now + 10, 73.85001)
        )
        self.assertIsNotNone(congestion)
        self.assertEqual(congestion["event_type"], "congestion_bottleneck")

        matrix = server.build_od_matrix()
        self.assertEqual(matrix["date"], time.strftime("%Y-%m-%d", time.gmtime(now)))
        self.assertTrue(matrix["matrix"])


if __name__ == "__main__":
    unittest.main()
