## EEI-2 Violation: _insert_nic_samples
File: core/execution/experiment_runner.py line 64
Issue: Uses db.db.conn.executemany directly instead of repository layer.
Fix: Move to core/database/repositories/samples.py as insert_nic_samples()
     and call via db.insert_nic_samples() like insert_cpu_samples.
Priority: Before next major release. Not a paper blocker.
