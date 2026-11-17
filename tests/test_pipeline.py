"""Offline checks for sampling order, threshold boundaries, and viewer metadata."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from _common import FIELDS, build_viewer_state, check_row, write_rows
from make_links import reusable
from sample_operations import Evaluator, sample, unique_ids
from validate_outputs import validate


def merge_row():
    return {"operation_id": "123", "operation_type": "merge",
            "timestamp_utc": "2022-01-01 00:00:00.500000+00:00", "filter_side": "before",
            "min_l2_count": "100", "before_root_ids": '["10", "20"]',
            "before_l2_counts": "[100, 200]", "before_total_l2": "300",
            "after_root_ids": '["30"]', "after_l2_counts": "[299]",
            "after_total_l2": "299", "delta_l2": "-1"}


class PipelineTests(unittest.TestCase):
    def test_seed_and_unique_draw_order(self):
        candidates = unique_ids(42, 1, 3000000)
        self.assertEqual([next(candidates) for _ in range(5)],
                         [2681951, 466957, 104903, 1153557, 1027151])
        self.assertEqual(set(unique_ids(42, 1, 10)), set(range(1, 11)))

    def test_quota_handling_and_prefetch_counts(self):
        types = {1: "merge", 2: "merge", 3: "split", 4: "split", 5: "merge", 6: "split"}

        class Graph:
            def get_operation_details(self, ids):
                return {str(op): {"added_edges" if typ == "merge" else "removed_edges": [[1, 2]]}
                        for op, typ in types.items() if op in ids}

        class Evaluation:
            def evaluate(self, item):
                op, _ = item
                return (("below threshold", None) if op == 3 else
                        ("passes threshold", {"operation_id": op, "operation_type": types[op]}))

            def complete(self, row):
                return row

        rows, summary = sample(Graph(), Evaluation(), iter(range(1, 9)), k=2, workers=3, batch_size=8)
        self.assertEqual([r["operation_id"] for r in rows], [1, 2, 4, 6])
        self.assertEqual(summary["considered_operation_ids"], 6)
        self.assertEqual(summary["queried_operation_ids"], 8)
        self.assertEqual(summary["outcomes"]["type quota already full"], 1)
        self.assertEqual(summary["by_operation_type"]["merge"]["threshold_evaluated"], 2)
        self.assertEqual(summary["by_operation_type"]["split"]["below_threshold"], 1)

    def test_threshold_boundary_and_historical_topology(self):
        timestamp = datetime(2022, 1, 1, tzinfo=timezone.utc)

        class Graph:
            def get_roots(self, supervoxels, timestamp):
                return [10, 20] if timestamp < datetime(2022, 1, 1, tzinfo=timezone.utc) else [30, 30]

            def get_leaves(self, root, stop_layer):
                return range({10: 100, 20: 200, 30: 299}[root])

        evaluator = Evaluator("unused", 100)
        evaluator.local.graph = Graph()
        detail = {"added_edges": [[1, 2]], "roots": [30], "timestamp": timestamp.isoformat()}
        outcome, row = evaluator.evaluate((123, detail))
        self.assertEqual(outcome, "passes threshold")
        self.assertEqual(evaluator.complete(row)["min_l2_count"], 100)
        evaluator.threshold = 101
        self.assertEqual(evaluator.evaluate((123, detail))[0], "below threshold")

    def test_viewer_coordinates_timestamp_and_link_reuse(self):
        row = merge_row()
        detail = {"roots": [30], "timestamp": row["timestamp_utc"],
                  "source_coords": [[10, 20, 30]], "sink_coords": [[14, 24, 34]]}
        info = {"segmentation_source": "graphene://example", "viewer_resolution_x": 4,
                "viewer_resolution_y": 4, "viewer_resolution_z": 40}
        state, metadata = build_viewer_state(row, detail, info, [16, 16, 40])
        self.assertEqual(state["navigation"]["pose"]["position"]["voxelCoordinates"], [48, 88, 32])
        self.assertEqual(state["layers"][1]["segments"], ["10", "20"])
        self.assertIn("MERGE", state["layers"][2]["name"])
        self.assertEqual(datetime.fromisoformat(metadata["viewer_timestamp_utc"]),
                         datetime.fromisoformat(row["timestamp_utc"]) - timedelta(milliseconds=1))
        linked = {**row, **metadata, "neuroglancer_url": "https://ngl.flywire.ai/?json_url=https://example/1"}
        self.assertTrue(reusable(row, linked))
        self.assertFalse(reusable({**row, "min_l2_count": "101"}, linked))
        self.assertEqual(validate([row], [linked], 100)["links"], 1)

    def test_failed_write_preserves_previous_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operations.csv"
            path.write_text("previous contents")
            with self.assertRaises(ValueError):
                write_rows(path, [{"unexpected": "column"}], FIELDS)
            self.assertEqual(path.read_text(), "previous contents")
            self.assertEqual([p.name for p in Path(directory).iterdir()], ["operations.csv"])

    def test_validation_rejects_bad_minimum(self):
        with self.assertRaises(ValueError):
            check_row({**merge_row(), "min_l2_count": "101"}, 100)


if __name__ == "__main__":
    unittest.main()
