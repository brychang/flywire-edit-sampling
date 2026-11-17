"""Validate the two CSV outputs offline; write no files."""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

sys.dont_write_bytecode = True
from _common import FIELDS, LINK_FIELDS, LINKS, OPERATIONS, check_row, read_rows


def validate(operations, links, threshold, k=None):
    seen = set()
    for row in operations:
        if row["operation_id"] in seen:
            raise ValueError("Duplicate operation ID")
        seen.add(row["operation_id"])
        check_row(row, threshold)
    counts = Counter(row["operation_type"] for row in operations)
    if k is not None and (counts["merge"] != k or counts["split"] != k):
        raise ValueError(f"Expected {k} operations per type, found {dict(counts)}")
    if len(operations) != len(links):
        raise ValueError("CSV row counts differ")
    for row, linked in zip(operations, links):
        if any(str(row[key]) != str(linked[key]) for key in FIELDS):
            raise ValueError("Linked CSV does not match operations CSV in the same order")
        if any(not linked.get(key) for key in LINK_FIELDS):
            raise ValueError("Incomplete link metadata")
        if linked["shown_side"] != row["filter_side"]:
            raise ValueError("Viewer must show the separated side")
        timestamp = datetime.fromisoformat(row["timestamp_utc"])
        offset = -1 if row["operation_type"] == "merge" else 1
        if datetime.fromisoformat(linked["viewer_timestamp_utc"]) != timestamp + timedelta(milliseconds=offset):
            raise ValueError("Incorrect viewer timestamp")
        for key in ("edit_center_voxels", "edit_center_nm"):
            point = json.loads(linked[key])
            if len(point) != 3 or not all(isinstance(n, (int, float)) for n in point):
                raise ValueError("Invalid edit center")
        url = urlparse(linked["neuroglancer_url"])
        if url.scheme != "https" or url.netloc != "ngl.flywire.ai" or not url.query.startswith("json_url=https://"):
            raise ValueError("Invalid Neuroglancer URL")
    return {"operations": len(operations), "merge": counts["merge"], "split": counts["split"],
            "l2_count_threshold": threshold, "links": len(links)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operations", type=Path, default=OPERATIONS)
    parser.add_argument("--links", type=Path, default=LINKS)
    parser.add_argument("--l2-count-threshold", type=int, default=100)
    parser.add_argument("--k", type=int, help="Optionally require this many operations per type")
    args = parser.parse_args()
    print(json.dumps(validate(read_rows(args.operations), read_rows(args.links),
                              args.l2_count_threshold, args.k), indent=2))


if __name__ == "__main__":
    main()
