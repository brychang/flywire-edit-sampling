# FlyWire edit sampling

Sample random CAVE operation IDs, filter by historical segment size, and generate
Neuroglancer links showing the separated segment pair and edit location.

The only saved outputs are:

- `outputs/operations.csv`: sampled IDs, historical roots, pre/post L2 counts,
  filter minima, totals, and changes.
- `outputs/operations_with_links.csv`: the same rows plus Neuroglancer links,
  edit-center coordinates, displayed side, and viewer timestamp.

The included outputs contain 100 merge operations and 100 split operations with
minimum paired L2 count >=100. Scripts are in `scripts/`.

## Setup

Use Python 3.10+ and an existing CAVE credential with access to
`flywire_fafb_public`. Credentials remain outside this repository. See the
[CAVE authentication instructions](https://www.caveconnecto.me/CAVEclient/tutorials/authentication/).

From the repository root:

```sh
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
```

Alternatively, use `python3 -m venv .venv` and
`.venv/bin/python -m pip install -r requirements.txt`.

## Run

### 1. Sample operations

The existing output is protected unless `--overwrite` is supplied. To generate a
fresh sample of 100 operations of each type:

```sh
.venv/bin/python scripts/sample_operations.py \
  --k 100 \
  --l2-count-threshold 100 \
  --seed 42 \
  --min-operation-id 1 \
  --max-operation-id 3000000 \
  --overwrite
```

This performs read-only CAVE queries and writes `outputs/operations.csv` only after
the sample is complete. Progress goes to stderr; sampling settings and filtering
totals print as JSON to stdout. No caches, checkpoints, logs, audit files, or plots
are saved. An interrupted or failed run leaves the previous CSV intact; a retry
starts the random sequence again. Increasing `--k` also starts from that same
seed, so it reconsiders IDs previously skipped when a type's quota was full.

The main options are `--k`, `--l2-count-threshold`, `--seed`, the two ID bounds,
`--workers` (default 8), `--max-candidates` (default 100000), `--datastack`, and
`--output`. Use `--help` for the full command reference. The links script is
configured for FlyWire imagery and its viewer; use the default FlyWire datastack
for this pipeline.

### 2. Generate links

```sh
.venv/bin/python scripts/make_links.py
```

Reads `outputs/operations.csv` and writes `outputs/operations_with_links.csv`.
Unchanged rows reuse existing links; new or changed rows create viewer states in
the CAVE state service. `--refresh` forces new states. No state JSON is saved in
the repository. Progress and upload/reuse totals print to the terminal. On failure,
the existing CSV stays intact, although states uploaded before failure may remain
in CAVE.

Each link selects the **pre-edit pair for a merge** or **post-edit pair for a
split**. The two segments are cyan and orange. Yellow point/line annotations
mark the edit, labeled SPLIT or MERGE with the operation ID. The center is the
mean of all recorded source/sink coordinates. Coordinates are converted using
CAVE segmentation resolution and the datastack's viewer resolution (currently
16x16x40 nm to 4x4x40 nm). The viewer timestamp is 1 ms before a merge or 1 ms
after a split. Open the links in a browser signed in to FlyWire.

Use `--input` and `--output` to choose other CSV paths; `--workers` defaults to 4.
Running this command after resampling removes obsolete rows from the linked CSV.

### 3. Validate the outputs

```sh
.venv/bin/python scripts/validate_outputs.py --k 100
```

This offline check verifies row counts, uniqueness, topology, threshold minima,
array alignment, totals, matching rows between both files, and viewer metadata.
It prints a summary and creates no files. For a different sample, pass the same
`--k` and `--l2-count-threshold` used when sampling. This does not re-query CAVE or
verify rendered meshes in a browser.

Offline regression checks:

```sh
.venv/bin/python -B -m unittest discover -s tests -v
```

## Sampling rules

- Draw unique integer operation IDs with successive
  `random.Random(seed).randrange(min_id, max_id + 1)` calls, ignoring duplicate
  draws. The default inclusive window is 1-3,000,000; it is not a statement about
  the latest operation or all FlyWire edits.
- Process candidates in draw order and retain the first `k` qualifying operations
  of each type. Concurrent reads do not change selection order. A batch may
  prefetch/evaluate additional IDs that are not considered after quotas fill;
  these are excluded from filtering totals.
- Require exactly **2->1 merges** or **1->2 splits**. Reconstruct historical roots
  from all edited-edge supervoxels at the operation timestamp +/-1 ms, and require
  post-edit roots to match the operation record. Exclude unavailable records,
  ambiguous edit types, and mismatched topologies separately from size failures.
- Count distinct `get_leaves(root_id, stop_layer=2)` IDs per historical root, with
  no spatial bounds or mapping to current roots. Both pre-edit merge segments or
  both post-edit split segments must have counts >= the threshold. Exactly 100
  passes when the threshold is 100. No overlap, cell-type, or mesh filter is used.
- L2 count is a size proxy, not physical skeleton length. L2 repartitioning may
  change totals. Operation labels identify edits, not independently validated
  biological errors: a merge can correct a split error and vice versa.

Root-ID arrays contain decimal strings to avoid 64-bit integer rounding. Count
arrays align with root arrays by position; preserve that order when reading CSVs.

## Included sample

The current sample considered **13,013 IDs**: 6,610 merges were threshold-tested
(6,510 failed), and 2,453 splits were threshold-tested (2,353 failed). Another
1,378 IDs were unavailable/ineligible; 2,572 merges were skipped after the merge
quota filled. There are 200 retained operations. The original run prefetched
13,024 candidate IDs; its final 11 prefetched IDs were not considered.

These are the recorded totals for the included sample, not a promise that future
CAVE responses will be identical. The original historical audit/cache artifacts
have been removed; fresh runs print their own settings and filtering summaries.
The original uploaded states were checked by API read-back for one edit per type;
visual browser verification was blocked by FlyWire sign-in.
