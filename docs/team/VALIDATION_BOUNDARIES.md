# Implementation scope and validation boundaries

This legacy path is retained so existing kickoff links continue to work. Research ideas, literature reviews and publication strategy are kept outside the shared repository.

Implement the complete assigned role using the shared contracts and named full-assignment checklist. Preserve the following engineering requirements:

- Record independently verified task completion, including failed, timed-out and interrupted attempts.
- Keep model, tool, verification and waiting spans attributable to the correct goal without double-counting overlapping energy domains.
- Record sensor coverage, clock domains and missing-data reasons; CPU-package plus GPU-board readings are not whole-machine energy.
- Retain raw readings, versioned task definitions, tested commits and reproducible artifacts.
- Keep held-out evaluation outcomes isolated from selection until the required seal.
- Distinguish fixture tests from live inference, hardware validation and completed campaigns.
- Coordinate shared interfaces and changes to frozen experiment definitions with Stephen. Existing session and hardware budgets still apply.

Passing software checks establishes only the behavior those checks exercise. Broader scientific decisions stay with Stephen; they do not belong in published agent notes. Follow the implementation-only publication boundary in the root AGENTS.md and shared README.
