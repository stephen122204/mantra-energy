# Release validation

This validates packaging and documented software interfaces; it does not reproduce
submitted experimental results. No GPU/model or measurement campaign ran.

- Both unchanged source tarballs were checked against their exact original Git
  trees, member names and every blob object ID: 2,468 Qwen files and 2,469 Devstral
  files. The processed-data tarball's 47 file members match original PR75 Git blobs.
- Both exact source commits recovered from the self-contained bundle; git bundle
  verify, full git fsck and ref comparisons passed.
- Eight CLI help checks passed (moe.run, campaign_plan, campaign_check, moe.prepare
  at each original revision). Two read-only schedule generations passed for the
  saved Qwen-R and Devstral plans; no scheduler or measurement launcher was started.
- Portable CLI checks used the existing Python3.14 study audit environment, not a
  recreated historical environment. Dependency resolution/builds, native Windows,
  backend numerical qualification and real hardware measurements were not rerun.
- Packaged source trees exclude studies/paper2 and October Paper2 cohort additions.
  Neither cleanup nor current Paper2 source was merged into these snapshots.
- No tracked temporary audit files were included. Pattern checks of all packaged
  file contents found no private-key blocks, AWS access IDs or recognized GitHub/
  OpenAI token patterns. This is a bounded scan, not a security certification.
- The publication repository was verified private; the tag/branch names were free.
  Official SIGMETRICS2027 anonymity guidance was reviewed. This private source
  release changes no repository visibility/settings and makes no public promotion.

Original source, archived processed values and prior failures remain unchanged.
Expected plan revisions are not independently verified execution identities.
Source preservation and available metadata are verifiable; the missing C2 raw
archives, environment/analysis artifacts and manuscript mappings prevent full
independent raw-to-submitted-result verification.
