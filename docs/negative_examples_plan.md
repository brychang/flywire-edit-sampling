# Plan: negative merge and split proposals

Status: exploration only, on `explore/negative-examples`. No examples have been
generated and no segmentation edits will be applied. Preserve the two-output
contract: `outputs/operations.csv` and `outputs/operations_with_links.csv`.

## Objective and terminology

Generate **k false merge proposals** and **k false split proposals**, with
`l2_count_threshold=100` by default. “False” describes an action that should be
rejected, not an error that needs correcting:

- False merge: propose joining two segments that should remain separate.
- False split: propose separating a connected structure that should remain joined.

Both separated pieces must meet the threshold. For a false merge, test both input
segments. For a false split, test both intended output partitions. Filtering only
the intact parent of a false split would not satisfy this requirement.

Record `proposal_type`, `should_apply=false`, and `generation_method` explicitly;
do not overload an actual human operation's `operation_type`. A synthetic proposal
has an `example_id` and an `anchor_operation_id`, not a fabricated operation ID.

## Recommended baseline: invert observed human corrections

This route supplies a real edit location and observed, size-filtered separated
segments for both negative types. It avoids treating random proximity or graph
connectivity as biological ground truth.

### False merge from a human split

1. Sample an operation ID with a verified human split, one parent P -> A and B.
2. Reconstruct A and B at the split timestamp +1 ms. Keep the original root IDs;
   do not update them to current roots.
3. Require `min(L2(A), L2(B)) >= threshold` using the existing count definition.
4. Propose merging A and B at the recorded split site. This reverses the human's
   separation and is a candidate negative for a merge decision.
5. Verify partition coverage and historical root membership using supervoxels,
   rather than relying on potentially inconsistent historical L2 traversal alone.

### False split from a human merge

1. Sample an operation ID with a verified human merge A + B -> P.
2. Treat the **exact inverse of its added edges** as the proposed false split.
   An arbitrary min-cut between the same seed points may produce a different split.
3. Use the actual pre-merge A and B supervoxel memberships as the intended
   counterfactual partitions. Require both observed pre-merge L2 counts >= threshold.
4. Verify the two memberships are disjoint and their union is the immediate
   post-merge parent. Check membership at the corresponding timestamps.
5. Show P at merge timestamp +1 ms and mark the proposed cut at the known join.

The L2 count basis for this false split is the **observed pre-merge partition**,
not newly allocated L2 IDs from an executed synthetic cut. No synthetic roots
exist. Do not calculate “post-split L2 count” by mapping both partitions onto the
uncut parent's L2 IDs: a single parent L2 node can straddle the proposed cut.
Store `l2_count_basis=observed_inverse_partition`. If the task requires counts of
newly rebuilt L2 components for another cut, that requires an additional local
component reconstruction method and a separately labeled count basis.

The current sample provides up to 100 anchors for each route before label and
membership checks. If k examples survive, no additional operation-ID draws are
needed. Otherwise continue the same seeded ID stream, accounting for all rejects.

## Label checks: human edits are evidence, not infallible ground truth

An accepted human edit can itself be wrong. Retain the original correction as
label provenance, then assess the proposed decision against a fixed reference
release/timestamp and any available proofreading annotations.

- Use supervoxel membership to follow the relevant local pieces, not just a
  “latest root” selected by largest overlap.
- Prefer false merges whose two local pieces remain in distinct reference cells,
  and false splits whose local pieces remain in the same independently proofread
  reference cell. Reference-root equality/inequality is supporting evidence,
  not proof by itself.
- Flag direct reversals, ambiguous lineage, incomplete proofreading, and local
  reference discrepancies for review; do not silently label them as negatives.
- Review EM continuity at the proposed join/cut. The k target should count accepted
  negatives, not an unreviewed pool of geometrically plausible candidates.
- Record evidence status: `human_edit_only`, `reference_supported`,
  `review_confirmed`, or `ambiguous`. Keep the review requirement explicit when
  reporting the number of validated examples.

Reference identity is a labeling check. It must not replace the historical roots
used for historical geometry and size measurements. Log this selection filter:
it changes the distribution relative to unrestricted random edits.

## Paper-aligned extension: nearby false merge partners

Use a verified correct merge A + B -> P as the anchor and search for a wrong
partner C. This generates a negative A + C matched to the positive A + B.

1. Fetch historical meshes of A and B in the same coordinate frame and mesh LOD.
   Use the recorded edit site to select a bounded local mesh region. Whole-object
   nearest points could identify an unrelated contact elsewhere on large neurons.
2. Compute nearest cross-mesh vertex distances with a spatial index such as
   `scipy.spatial.cKDTree`, avoiding a full pairwise distance matrix. Find the
   minimum distance d_min; select near-minimum vertex pairs and average their
   midpoints to obtain the interface coordinate. Deduplicate pairs so sampling
   direction does not inadvertently double their weight.
3. Expose the near-minimum tolerance in nm as a parameter. The quoted method
   does not specify its numerical threshold. Calibrate it against mesh LOD and
   inspect a small pilot; record the selected tolerance instead of claiming exact
   reproduction. Keep the recorded-site center as an explicitly labeled fallback.
4. Search supervoxel cutouts around the interface, then map supervoxels to roots
   at the **pre-merge timestamp**. Do not use a cutout helper's default current-root
   mapping for a historical example.
5. Initial geometric interpretation: `abs(dx) <= 128 nm`, `abs(dy) <= 128 nm`,
   and `120 <= abs(dz) <= 880 nm`, i.e. two vertical slabs. The quotation does not
   resolve square-versus-radial lateral distance; expose the convention and state
   this square-window choice. Account for actual voxel resolution and slab rounding.
6. Deduplicate candidate roots; exclude background, A, and B. Uniformly sample
   candidate roots in seeded order, not voxels, to avoid favoring large segments.
   Require both A and C to have L2 counts >= threshold at that timestamp.
7. Require support that C belongs to a different biological cell than A. Merely
   having C != B is insufficient: C could be another fragment of the same neuron.
8. Reject empty/ambiguous neighborhoods and continue to another anchor; do not
   silently expand the spatial window to fill k. Report the spatial rule's yield.

Use at most one retained negative per anchor initially. Reusing one plausible C
across many anchors can create correlated examples; deduplicate proposal pairs.

## Additional false splits: experimental, after baseline validation

Randomly cutting a large root is not sufficient: it may repair a genuine merge
error, produce tiny fragments, or fail to disconnect a graph with alternate paths.
First use known correct human joins, as above. For additional diversity, identify
an EM-supported continuous neurite in a proofread cell and evaluate a proposed
cut using a non-mutating preview or an offline graph partition.

`CAVEclient.chunkedgraph.preview_split` exists in the installed 8.2.1 client and
returns source/sink supervoxel components, success, and optional extra components.
However its signature has **no timestamp parameter**. Historical compatibility,
permissions, component scope, and behavior on stale roots must be established in
a small pilot before adopting it. Do not silently substitute current roots.

Require exactly two nonempty, disjoint, connected components covering the parent;
account for any additional components and ensure the split is global, not just a
cropped graph that disconnects outside the crop. Apply the size threshold to each
partition using an explicitly justified L2 count basis. Preview supervoxels alone
do not create real post-edit L2 nodes or independently establish a negative label.

No calls to `do_merge`, `do_split`, `undo_operation`, or mesh-remeshing endpoints
are required. If preview cannot support the pinned historical state, keep this
route experimental rather than changing the baseline definition.

## Sampling, evaluation, and outputs

- Parameters: `--k`, `--l2-count-threshold`, `--seed`, ID window, reference snapshot,
  generation method, interface tolerance, spatial-window convention, and bounded
  per-anchor candidate budget. Every default should be recorded in stdout.
- Sample anchors by unique operation ID, preserving random draw order across
  concurrent reads. Backfill after filtering until k of each proposal type or a
  declared candidate budget is exhausted. Report shortfalls rather than relaxing
  thresholds or labels.
- Print considered IDs, valid anchors, candidates tested, and mutually exclusive
  rejection totals: topology/membership, threshold, geometry/availability,
  ambiguous labels, duplicates, and quota skips. Separate label-review attrition
  from automated candidate-generation yield.
- Split train/test by anchor operation and involved reference cells, including
  their lineage groups. A positive and its inverse or matched spatial negative
  must stay in the same split. Match viewing scale, colors, and crop conventions
  across labels; avoid annotation text that reveals the expected answer.
- Keep the two CSV filenames. Extend the schema explicitly for proposal examples
  rather than mixing synthetic examples into the existing real-operation schema
  without updating validation and link generation. Fields should include example
  ID, anchor ID/type, proposal type, should-apply label, method, timestamp, component
  IDs/memberships or reproducible partition specification, per-piece L2 counts,
  count basis, location, reference snapshot, and label-evidence status.
- For false splits, a hypothetical partition has no root ID. Its reproducible
  specification can reference the anchor's exact added edges and observed pre-edit
  roots. Verify whether historical pre-edit meshes can be displayed alongside the
  intact post-edit parent; do not imply a standard root-selection link renders a
  newly computed arbitrary preview partition. Keep viewer labels neutral for
  evaluation, with SPLIT/MERGE identifying the proposal type only.
- Keep candidate meshes, previews, and audit state in memory; no additional saved
  output artifacts. Preserve current CSVs until the new run is complete.

## Implementation sequence and acceptance criteria

1. **Pilot:** inspect a handful of inverse edits of each type. Establish partition
   membership consistency, reference evidence availability, size semantics, and
   correct viewer presentation. Assess spatial-neighbor yield separately.
2. **Baseline generator:** implement inverse-edit proposals and deterministic
   backfilling, with explicit evidence statuses. Extend validators and the existing
   two-output pipeline. Check threshold equality, false-split partition coverage,
   topology, label provenance, ID uniqueness, and failed-run output preservation.
3. **Spatial extension:** add interface and wrong-partner selection, with tests for
   anisotropic units, timestamp mapping, candidate-root deduplication, and identity
   ambiguity. Compare its label-review pass rate with inverse edits.
4. **Scale:** generate k accepted false merges and k accepted false splits. Report
   screening totals and label-evidence status, plus size/distance distributions
   via stdout or an explicitly requested display, without extra saved outputs.

Before promising k validated negatives, the pilot must establish a usable label
standard. If reference support or expert review is unavailable, the achievable
deliverable is k **candidate** negatives with documented provenance, not verified
biological ground truth.

## Sources

- User-provided ConnectomeBench methods excerpt: nearby wrong-partner construction.
- [CAVEclient preview, contact, and graph API](https://www.caveconnecto.me/CAVEclient/api/chunkedgraph/).
- [FlyWire segmentation cutouts](https://fafbseg-py.readthedocs.io/en/latest/source/generated/fafbseg.flywire.get_segmentation_cutout.html).
- [FlyWire segmentation identities and timestamps](https://fafbseg-py.readthedocs.io/en/latest/source/tutorials/flywire_segments.html).

API signatures were also inspected in the locally installed CAVEclient 8.2.1.
No mesh retrieval, neighborhood-query, preview, or labeling pilot has yet run.
