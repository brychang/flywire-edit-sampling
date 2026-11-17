"""Shared CSV and viewer-state helpers. No filesystem writes on import."""

import csv
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = ROOT / "outputs" / "operations.csv"
LINKS = ROOT / "outputs" / "operations_with_links.csv"
FIELDS = [
    "operation_id", "operation_type", "timestamp_utc", "filter_side", "min_l2_count",
    "before_root_ids", "before_l2_counts", "before_total_l2",
    "after_root_ids", "after_l2_counts", "after_total_l2", "delta_l2",
]
LINK_FIELDS = [
    "shown_side", "edit_center_voxels", "edit_center_nm",
    "viewer_timestamp_utc", "neuroglancer_url",
]


def read_rows(path):
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path}: no operations")
    return rows


def write_rows(path, rows, fields):
    """Replace a CSV only after the complete new file has been written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", newline="", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def check_row(row, threshold=100):
    typ = row["operation_type"]
    if typ not in {"merge", "split"}:
        raise ValueError(f"Unknown operation type: {typ}")
    counts = {}
    roots = {}
    for side in ("before", "after"):
        roots[side] = json.loads(row[f"{side}_root_ids"])
        counts[side] = json.loads(row[f"{side}_l2_counts"])
        if not all(isinstance(root, str) and root.isdecimal() for root in roots[side]):
            raise ValueError("Root IDs must be stored as decimal strings")
        if len(set(roots[side])) != len(roots[side]):
            raise ValueError("Duplicate roots within a side")
        if len(roots[side]) != len(counts[side]):
            raise ValueError("Root/count arrays do not align")
        if not all(type(count) is int and count > 0 for count in counts[side]):
            raise ValueError("L2 counts must be positive integers")
        if sum(counts[side]) != int(row[f"{side}_total_l2"]):
            raise ValueError("L2 total does not match segment counts")
    expected = (2, 1) if typ == "merge" else (1, 2)
    if (len(roots["before"]), len(roots["after"])) != expected:
        raise ValueError("Unexpected root topology")
    side = "before" if typ == "merge" else "after"
    if row["filter_side"] != side:
        raise ValueError("Incorrect filtering side")
    minimum = min(counts[side])
    if minimum < threshold or minimum != int(row["min_l2_count"]):
        raise ValueError("Incorrect filtering minimum or threshold failure")
    if int(row["delta_l2"]) != sum(counts["after"]) - sum(counts["before"]):
        raise ValueError("Incorrect L2 delta")


def build_viewer_state(row, detail, info, segmentation_resolution):
    """Return a FlyWire state and CSV metadata for the separated segment pair."""
    op, typ = row["operation_id"], row["operation_type"]
    side = "before" if typ == "merge" else "after"
    roots = json.loads(row[f"{side}_root_ids"])
    if len(roots) != 2:
        raise ValueError(f"Operation {op}: expected two separated segments")
    if set(map(int, json.loads(row["after_root_ids"]))) != set(detail["roots"]):
        raise ValueError(f"Operation {op}: output roots changed or do not match")
    if datetime.fromisoformat(detail["timestamp"]) != datetime.fromisoformat(row["timestamp_utc"]):
        raise ValueError(f"Operation {op}: timestamp does not match")
    sources, sinks = detail["source_coords"], detail["sink_coords"]
    if not sources or not sinks or any(len(p) != 3 for p in sources + sinks):
        raise ValueError(f"Operation {op}: missing or invalid edit coordinates")
    viewer_resolution = [info[f"viewer_resolution_{axis}"] for axis in "xyz"]

    def convert(point):
        return [point[i] * segmentation_resolution[i] / viewer_resolution[i] for i in range(3)]

    def mean(points):
        return [sum(p[i] for p in points) / len(points) for i in range(3)]

    points = [convert(p) for p in sources + sinks]
    center = mean(points)
    center_nm = [n * resolution for n, resolution in zip(center, viewer_resolution)]
    timestamp = datetime.fromisoformat(detail["timestamp"]) + timedelta(
        milliseconds=-1 if side == "before" else 1
    )
    label = f"{typ.upper()} operation {op}"
    annotations = [{"id": f"{op}-center", "type": "point", "point": center,
                    "description": f"{label} | edit center"}]
    for index, point in enumerate(points):
        endpoint = "source" if index < len(sources) else "sink"
        annotations.append({"id": f"{op}-endpoint-{index}", "type": "point", "point": point,
                            "description": f"{label} | {endpoint} {index + 1}"})
    annotations.append({"id": f"{op}-connection", "type": "line",
                        "pointA": mean([convert(p) for p in sources]),
                        "pointB": mean([convert(p) for p in sinks]),
                        "description": f"{label} | source-to-sink locator"})
    state = {
        "title": f"{label} | separated pair",
        "layers": [
            {"type": "image", "name": "FAFB EM", "source":
             "precomputed://https://bossdb-open-data.s3.amazonaws.com/flywire/fafbv14"},
            {"type": "segmentation_with_graph", "name": f"Separated segments ({side} {typ})",
             "source": info["segmentation_source"], "segments": roots,
             "segmentColors": {roots[0]: "#00bfff", roots[1]: "#ff8c00"},
             "selectedAlpha": 0.6, "notSelectedAlpha": 0, "objectAlpha": 1,
             "timestamp": f"{timestamp.timestamp():.6f}",
             "graphOperationMarker": [{"annotations": [], "tags": []}, {"annotations": [], "tags": []}],
             "skeletonRendering": {"mode2d": "lines_and_points", "mode3d": "lines"}},
            {"type": "annotation", "name": f"{label} | edit location",
             "annotationColor": "#ffff00", "annotations": annotations, "visible": True},
        ],
        "navigation": {"pose": {"position": {"voxelSize": viewer_resolution,
                                                 "voxelCoordinates": center}}, "zoomFactor": 4},
        "perspectiveZoom": 2000, "showSlices": True, "showDefaultAnnotations": False,
        "selectedLayer": {"layer": f"{label} | edit location", "visible": True}, "layout": "xy-3d",
    }
    metadata = {"shown_side": side, "edit_center_voxels": json.dumps(center),
                "edit_center_nm": json.dumps(center_nm), "viewer_timestamp_utc": timestamp.isoformat()}
    return state, metadata
