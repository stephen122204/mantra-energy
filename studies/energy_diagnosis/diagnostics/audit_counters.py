"""Independently reconcile short, non-wrapping counter qualification records."""
import argparse
import json
import math
from pathlib import Path


def audit(root):
    rows = []
    paths = sorted(Path(root).glob('[01]-*.json'))
    if len(paths) != 8:
        raise ValueError('expected two repetitions of idle/cpu/gpu/combined')
    if {p.stem for p in paths} != {f'{i}-{k}' for i in range(2) for k in ('idle','cpu','gpu','combined')}:
        raise ValueError('unexpected qualification filenames')
    for path in paths:
        a = json.loads(path.read_text())
        seconds = (a['goal_end_ns'] - a['goal_start_ns']) / 1e9
        if seconds <= 0 or not a['measurements']:
            raise ValueError('missing measurements or invalid duration')
        for m in a['measurements']:
            domain = m['domain_id']
            samples = [s for s in a['samples'] if s['domain_id'] == domain and
                       any(tag in s['sample_id'] for tag in (':goal_start:', ':goal_sample_', ':goal_end:'))]
            if (len(samples) < 2 or ':goal_start:' not in samples[0]['sample_id'] or
                    ':goal_end:' not in samples[-1]['sample_id']):
                raise ValueError('missing ordered endpoint samples')
            if any(s['status'] != 'ok' or s['unit'] != 'microjoules' or
                   s['acquired_end_ns'] < s['acquired_start_ns'] for s in samples):
                raise ValueError('invalid counter sample')
            values = [s['value'] for s in samples]
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
                raise ValueError('invalid numeric counter')
            if any(v < u for u,v in zip(values,values[1:])):
                raise ValueError('counter decrease requires explicit wrap/reset inspection')
            expected = (values[-1] - values[0]) / 1e6
            if m['status'] != 'valid' or not math.isclose(expected,m['energy_j'],rel_tol=1e-12,abs_tol=1e-9):
                raise ValueError('derived energy does not match raw endpoint difference')
            rows.append(dict(file=path.name,domain=domain,joules=expected,seconds=seconds,
                             average_watts=expected/seconds,samples=len(samples),
                             max_read_bracket_ms=max(s['acquired_end_ns']-s['acquired_start_ns'] for s in samples)/1e6))
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    print(json.dumps(audit(parser.parse_args().directory),indent=2))
