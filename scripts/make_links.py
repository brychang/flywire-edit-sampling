"""Add saved Neuroglancer states; write only operations_with_links.csv."""

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.dont_write_bytecode = True
from _common import FIELDS, LINK_FIELDS, LINKS, OPERATIONS, build_viewer_state, check_row, read_rows, write_rows


def reusable(row, previous):
    """Reuse a link only for an unchanged operation and all required metadata."""
    return (previous is not None
            and all(str(previous.get(key)) == str(row[key]) for key in FIELDS)
            and all(previous.get(key) for key in LINK_FIELDS)
            and previous["neuroglancer_url"].startswith("https://ngl.flywire.ai/?json_url="))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=OPERATIONS)
    parser.add_argument("--output", type=Path, default=LINKS)
    parser.add_argument("--datastack", default="flywire_fafb_public")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--refresh", action="store_true", help="Upload new states instead of reusing matching links")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("input and output must be different files")
    if args.workers <= 0:
        parser.error("workers must be positive")
    rows = read_rows(args.input)
    if len({row['operation_id'] for row in rows}) != len(rows):
        parser.error("input contains duplicate operation IDs")
    for row in rows:
        check_row(row, threshold=1)  # Respect the sampling threshold used to create the input.
    previous = {row["operation_id"]: row for row in read_rows(args.output)} if args.output.exists() else {}
    output, pending = {}, []
    for row in rows:
        old = previous.get(row["operation_id"])
        if not args.refresh and reusable(row, old):
            output[row["operation_id"]] = {key: old[key] for key in FIELDS + LINK_FIELDS}
        else:
            pending.append(row)
    if pending:
        from caveclient import CAVEclient
        client = CAVEclient(args.datastack)
        info = client.info.get_datastack_info()
        resolution = client.chunkedgraph.segmentation_info["scales"][0]["resolution"]
        details = {}
        for start in range(0, len(pending), 40):
            details.update(client.chunkedgraph.get_operation_details(
                [int(row["operation_id"]) for row in pending[start:start + 40]]))
        local = threading.local()

        def upload(row):
            op = row["operation_id"]
            if op not in details:
                raise ValueError(f"Operation {op} is not available; no CSV replaced")
            state, metadata = build_viewer_state(row, details[op], info, resolution)
            if not hasattr(local, "state"):
                local.state = CAVEclient(args.datastack).state
            state_id = local.state.upload_state_json(state)
            metadata["neuroglancer_url"] = local.state.build_neuroglancer_url(
                state_id, ngl_url="https://ngl.flywire.ai/", target_site="seunglab")
            print(f"Created {row['operation_type']} link for {op}", file=sys.stderr, flush=True)
            return {**{key: row[key] for key in FIELDS}, **metadata}

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for result in pool.map(upload, pending):
                output[result["operation_id"]] = result
    result = [output[row["operation_id"]] for row in rows]
    write_rows(args.output, result, FIELDS + LINK_FIELDS)
    print(json.dumps({"operations": len(rows), "reused_links": len(rows) - len(pending),
                      "uploaded_states": len(pending), "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
