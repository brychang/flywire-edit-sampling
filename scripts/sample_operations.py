"""Sample random CAVE operation IDs; write only operations.csv."""

import argparse
import json
import random
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import lru_cache

sys.dont_write_bytecode = True
from _common import FIELDS, OPERATIONS, check_row, write_rows


def operation_type(detail):
    added, removed = detail.get("added_edges", []), detail.get("removed_edges", [])
    return "merge" if added and not removed else "split" if removed and not added else None


def unique_ids(seed, minimum, maximum):
    rng, seen = random.Random(seed), set()
    while len(seen) < maximum - minimum + 1:
        op = rng.randrange(minimum, maximum + 1)
        if op not in seen:
            seen.add(op)
            yield op


class Evaluator:
    def __init__(self, datastack, threshold):
        self.datastack, self.threshold = datastack, threshold
        self.local = threading.local()

    def graph(self):
        if not hasattr(self.local, "graph"):
            from caveclient import CAVEclient
            self.local.graph = CAVEclient(self.datastack).chunkedgraph
        return self.local.graph

    @lru_cache(maxsize=2048)
    def count(self, root):
        ids = self.graph().get_leaves(root, stop_layer=2)
        count = len(set(map(int, ids)))
        if count == 0:
            raise ValueError(f"No L2 nodes returned for root {root}; sampling stopped")
        return count

    def evaluate(self, item):
        op, detail = item
        typ = operation_type(detail)
        if typ is None or not detail.get("roots"):
            return "invalid operation details", None
        graph = self.graph()
        timestamp = datetime.fromisoformat(detail["timestamp"])
        edges = detail.get("added_edges") or detail.get("removed_edges")
        supervoxels = sorted({int(sv) for edge in edges for sv in edge})
        before = sorted(set(map(int, graph.get_roots(
            supervoxels, timestamp=timestamp - timedelta(milliseconds=1)))))
        after = sorted(set(map(int, graph.get_roots(
            supervoxels, timestamp=timestamp + timedelta(milliseconds=1)))))
        expected = (2, 1) if typ == "merge" else (1, 2)
        if ((len(before), len(after)) != expected or 0 in before + after
                or after != sorted(map(int, detail["roots"]))):
            return "ineligible topology or output root mismatch", None
        side = "before" if typ == "merge" else "after"
        counts = [self.count(root) for root in (before if side == "before" else after)]
        if min(counts) < self.threshold:
            return "below threshold", None
        return "passes threshold", {
            "operation_id": op, "operation_type": typ, "timestamp_utc": detail["timestamp"],
            "filter_side": side, "min_l2_count": min(counts),
            "before_root_ids": json.dumps([str(root) for root in before]),
            "after_root_ids": json.dumps([str(root) for root in after]),
            f"{side}_l2_counts": json.dumps(counts),
        }

    def complete(self, row):
        for side in ("before", "after"):
            key = f"{side}_l2_counts"
            if key not in row:
                row[key] = json.dumps([self.count(int(root)) for root in json.loads(row[f"{side}_root_ids"])])
            row[f"{side}_total_l2"] = sum(json.loads(row[key]))
        row["delta_l2"] = row["after_total_l2"] - row["before_total_l2"]
        check_row(row, self.threshold)
        return row


def sample(graph, evaluator, candidates, k, workers=8, batch_size=32, max_candidates=100000):
    """Concurrent reads; acceptance and quota handling always follow draw order."""
    selected, retained, outcomes, tested, rejected = [], Counter(), Counter(), Counter(), Counter()
    considered = queried = 0
    candidates = iter(candidates)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while retained["merge"] < k or retained["split"] < k:
            batch = []
            for _ in range(min(batch_size, max_candidates - considered)):
                try:
                    batch.append(next(candidates))
                except StopIteration:
                    break
            if not batch:
                raise RuntimeError(f"Candidate limit exhausted; retained {dict(retained)}. No CSV replaced.")
            details = graph.get_operation_details(batch)
            queried += len(batch)
            pending = [(op, details[str(op)]) for op in batch if str(op) in details
                       and retained[operation_type(details[str(op)])] < k]
            results = dict(zip((op for op, _ in pending), pool.map(evaluator.evaluate, pending)))
            for op in batch:
                if retained["merge"] == k and retained["split"] == k:
                    break
                considered += 1
                detail = details.get(str(op))
                typ = operation_type(detail) if detail else None
                if not detail:
                    outcome = "no operation returned"
                elif typ is not None and retained[typ] >= k:
                    outcome = "type quota already full"
                else:
                    outcome, row = results[op]
                    if outcome in ("passes threshold", "below threshold"):
                        tested[typ] += 1
                    if outcome == "below threshold":
                        rejected[typ] += 1
                    if outcome == "passes threshold":
                        selected.append(evaluator.complete(row))
                        retained[typ] += 1
                        outcome = "selected"
                outcomes[outcome] += 1
            print(f"Considered {considered:,}: merges {retained['merge']}/{k}, splits {retained['split']}/{k}",
                  file=sys.stderr, flush=True)
    summary = {"considered_operation_ids": considered, "queried_operation_ids": queried,
               "outcomes": dict(outcomes), "by_operation_type": {
                   typ: {"threshold_evaluated": tested[typ], "below_threshold": rejected[typ],
                         "retained": retained[typ]} for typ in ("merge", "split")}}
    return selected, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=100, help="Retained operations per type (default: 100)")
    parser.add_argument("--l2-count-threshold", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-operation-id", type=int, default=1)
    parser.add_argument("--max-operation-id", type=int, default=3000000)
    parser.add_argument("--max-candidates", type=int, default=100000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--datastack", default="flywire_fafb_public")
    parser.add_argument("--output", type=type(OPERATIONS), default=OPERATIONS)
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing operations CSV after completion")
    args = parser.parse_args()
    if min(args.k, args.l2_count_threshold, args.workers, args.max_candidates, args.min_operation_id) <= 0:
        parser.error("k, threshold, workers, candidate limit, and minimum ID must be positive")
    if args.max_operation_id < args.min_operation_id:
        parser.error("maximum operation ID must be >= minimum operation ID")
    if args.output.exists() and not args.overwrite:
        parser.error(f"{args.output} exists; use --overwrite to resample")
    evaluator = Evaluator(args.datastack, args.l2_count_threshold)
    rows, summary = sample(evaluator.graph(), evaluator,
                           unique_ids(args.seed, args.min_operation_id, args.max_operation_id),
                           args.k, args.workers, max_candidates=args.max_candidates)
    write_rows(args.output, rows, FIELDS)
    print(json.dumps({"sampling": vars(args), "summary": summary}, indent=2, default=str))


if __name__ == "__main__":
    main()
