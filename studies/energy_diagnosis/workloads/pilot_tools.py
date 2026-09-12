"""Actual local computations over the immutable pilot assets."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import csv
import threading

from .bounded_executor import ToolResultEnvelope
from .pilot_tasks import asset_files


@dataclass
class PilotAssetTool:
    asset_path: str
    family: str

    def execute(self, workers=1):
        path = Path(self.asset_path)
        seen, lock = set(), threading.Lock()
        if self.family == "data":
            with path.open(newline="", encoding="utf-8") as handle:
                items = list(csv.DictReader(handle))

            def work(row):
                with lock:
                    seen.add(threading.get_ident())
                units = Decimal(row["units"])
                return units, units * Decimal(row["unit_price"])

            with ThreadPoolExecutor(max_workers=workers) as pool:
                values = list(pool.map(work, items))
            output = dict(
                total_units=str(sum(v[0] for v in values)),
                total_revenue=str(sum(v[1] for v in values)),
            )
        else:
            files = sorted(p.relative_to(path).as_posix() for p in asset_files(path))
            output = dict(file_count=len(files), checks=files)
            seen.add(threading.get_ident())
        return ToolResultEnvelope(True, output, workers_observed=len(seen))
