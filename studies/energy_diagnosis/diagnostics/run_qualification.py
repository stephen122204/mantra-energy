"""Run separate fixed-input captures and comparisons; stop at the first failure."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def steps(config,case,output,timeout):
    root = Path(output)
    prefix = 'studies.energy_diagnosis.diagnostics.'
    def capture(name,mode):
        return [sys.executable,'-m',prefix+'capture_fixed_forward','--config',str(config),
                '--case',str(case),'--output',str(root/name),'--mode',mode,'--timeout',str(timeout)]
    def compare(name,left,right):
        return [sys.executable,'-m',prefix+'compare_fixed_forward','--left',str(root/left),
                '--right',str(root/right),'--output',str(root/(name+'.json'))]
    return [
        ('demand-1',capture('demand-1','native-demand')),
        ('demand-2',capture('demand-2','native-demand')),
        ('repeatability',compare('repeatability','demand-1','demand-2')),
        ('preparation',capture('preparation','native-preparation')),
        ('preparation-comparison',compare('preparation-comparison','demand-1','preparation')),
        ('reference',capture('reference','reference')),
        ('reference-comparison',compare('reference-comparison','reference','demand-1')),
    ]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True)
    p.add_argument('--case',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--timeout',type=int,default=900,help='per-capture timeout; not an overall lease budget')
    a = p.parse_args()
    if not 1 <= a.timeout <= 1800:
        p.error('timeout must be 1..1800 seconds')
    root = Path(a.output).resolve()
    root.mkdir(parents=True,exist_ok=False)
    outcomes = []
    for name,command in steps(Path(a.config).resolve(),Path(a.case).resolve(),root,a.timeout):
        result = subprocess.run(command)
        outcomes.append(dict(stage=name,command=command,returncode=result.returncode))
        tmp = root/'stages.tmp'
        tmp.write_text(json.dumps(outcomes,indent=2)+'\n')
        tmp.replace(root/'stages.json')
        if result.returncode:
            return result.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
