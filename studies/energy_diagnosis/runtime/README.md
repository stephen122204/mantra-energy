# Runtime and measurement boundary

`measurement.py` adapts existing A-LEMS energy readers to the ED-01 study
contracts. It records declared domain scope, access failures, monotonic
acquisition brackets, a separate wall-clock anchor, raw goal endpoints and
derived per-domain measurements. Goal end is captured before collector
teardown, so delayed cleanup changes the session span but not the measured
goal window.

This layer does not claim whole-machine coverage. Capability reports describe
only the domains declared and returned by the selected reader. Fixture reports
are not Grace hardware evidence.
