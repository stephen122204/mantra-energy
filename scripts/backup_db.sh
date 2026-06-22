#!/bin/bash
# backup_db.sh — Triple-layer database backup
# Layer 1: NVMe internal (/home/dpani/alems-backups) — always available
# Layer 2: ALEMS-BKP sda8 exfat (/mnt/alems-bkp) — separate physical disk
# Keeps only 2 most recent per layer — no bloat

set -e
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_SRC=/mnt/alems-data/gn100-2b96/experiments.db

if [ ! -f "$DB_SRC" ]; then
    echo "❌ Source DB not found: $DB_SRC (GM7000 SSD disconnected?)"
    exit 1
fi

# Layer 1: NVMe internal (survives GM7000 disconnection)
NVME_BACKUP_DIR=/home/dpani/alems-backups
mkdir -p "$NVME_BACKUP_DIR"
cp "$DB_SRC" "$NVME_BACKUP_DIR/experiments_${TIMESTAMP}.db"
echo "✅ Layer 1 (NVMe): experiments_${TIMESTAMP}.db"
ls -t "$NVME_BACKUP_DIR"/experiments_*.db | tail -n +3 | xargs -r rm -f

# Layer 2: ALEMS-BKP sda8 (separate physical disk from GM7000)
ALEMS_BKP=/mnt/alems-bkp
if mountpoint -q "$ALEMS_BKP"; then
    mkdir -p "$ALEMS_BKP/gn100-db-backup"
    cp "$DB_SRC" "$ALEMS_BKP/gn100-db-backup/experiments_${TIMESTAMP}.db"
    echo "✅ Layer 2 (ALEMS-BKP sda8): experiments_${TIMESTAMP}.db"
    ls -t "$ALEMS_BKP/gn100-db-backup"/experiments_*.db | tail -n +3 | xargs -r rm -f
else
    echo "⚠️  Layer 2 (ALEMS-BKP): skipped, /mnt/alems-bkp not mounted"
fi

# Integrity check on NVMe copy
sqlite3 "$NVME_BACKUP_DIR/experiments_${TIMESTAMP}.db" "PRAGMA integrity_check;" | grep -q "ok" \
    && echo "✅ Integrity: ok" \
    || echo "❌ Integrity: FAILED — check immediately"

echo "Done: $TIMESTAMP"
