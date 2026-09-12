# Analysis and selector boundary

Stephen owns the diagnostic method, baselines, uncertainty, abstention semantics,
and held-out evaluation. Begin with development evidence; do not inspect hidden
reference results during selection.

`selector_boundary.py` is the NI4 enforcement shell. It does not implement or
claim a scientific selection method. `SelectorBoundary.run_selector(...)`
supplies a `RestrictedSelectorAPI` containing only eligible candidate IDs,
budget status, a profiling query capability, and recommendation/abstention seal
methods. Hidden reference outcomes are not loaded into the boundary until a
decision is sealed. Each session also freezes an allowlist of profiling feature
names; undeclared fields are withheld from the selector and recorded as a
failed, cost-bearing query.

Every attempted profile is persisted in SQLite with status, duration, energy
or an explicit unavailability reason, features, and failure reason. Query-count
limits are checked before execution. Duration and energy limits stop subsequent
queries when observed cumulative cost reaches or exceeds the cap; the query
that crosses an observed-cost threshold is retained rather than erased.
Unavailable energy blocks further queries when an energy budget is active.

A sealed recommendation or abstention is immutable and content-hashed.
Reference loading/export is a separate post-seal operation. Live evaluation is
accepted only for the exact sealed recommendation; abstention has no live
setting. Selection exports never contain reference outcomes, including after
the separate reference store has been opened.

This is a Python capability boundary, not an operating-system sandbox for
untrusted selector code. The final frozen process/storage isolation and
scientific policy remain Stephen's decisions. Fixture tests are not held-out,
model, energy, Grace, or campaign evidence.

Implementation pending. See the [study index](../README.md) and root instructions.
