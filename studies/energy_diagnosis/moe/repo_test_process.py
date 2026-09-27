"""Restricted pytest feedback process; its exit status is not a correctness oracle.

The candidate can read its public repository and installed Python dependencies,
and write an empty disposable scratch directory. It cannot read adjacent task
assets. The independent graph oracle makes the final correctness comparison.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from functools import lru_cache

from .sandbox import LANDLOCK

CHILD = r'''
import json, os, sys, sysconfig
job = json.loads(sys.stdin.read())
# -I -S avoids candidate startup hooks and site .pth execution.
libraries = job['libraries']
sys.path.extend(p for p in libraries if p not in sys.path)
import pytest
''' + LANDLOCK + r'''
if not sys.platform.startswith('linux') and job['require_landlock']:
    sys.stderr.write('ALEMS_SANDBOX_UNAVAILABLE\n'); sys.exit(86)
if sys.platform.startswith('linux'):
    abi = _landlock([job['root'], '/dev/null', *[p for p in libraries if os.path.isdir(p)]], [job['scratch']])
    if job['require_landlock'] and abi < 4:
        sys.stderr.write('ALEMS_SANDBOX_UNAVAILABLE\n'); sys.exit(86)
import resource
resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
sys.path.insert(0, job['root'])
os.chdir(job['root'])
sys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', '--tb=short', '-rf', '--color=no',
    '--log-file', job['scratch'] + '/pytest.log',
    '--confcutdir', job['root'], '--rootdir', job['root'], '--basetemp', job['scratch'] + '/pytest',
    *job['targets']]))
'''


@lru_cache(maxsize=8)
def interpreter_paths(python):
    # Python <3.14 loses the venv prefix with -S. Resolve installed dependencies
    # using the trusted interpreter before starting the isolated candidate process.
    code = """import json,sysconfig,os,sys
paths={sysconfig.get_path(k) for k in ('stdlib','platstdlib','purelib','platlib')}
if sys.platform.startswith('linux'):
    multiarch=sysconfig.get_config_var('MULTIARCH')
    if multiarch: paths.update(os.path.realpath(p) for p in (f'/lib/{multiarch}',f'/usr/lib/{multiarch}'))
    paths.add(os.path.realpath('/lib64'))
print(json.dumps(sorted(p for p in paths if os.path.isdir(p))))
"""
    result = subprocess.run([python, '-I', '-c', code], cwd='/', capture_output=True, text=True, check=True, timeout=15)
    paths = json.loads(result.stdout)
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) or not Path(p).is_absolute() for p in paths):
        raise RuntimeError('invalid trusted Python library paths')
    return paths


def run(python, root, targets, *, timeout, limits=None, require_landlock=True):
    root = Path(root).resolve()
    if any(p.is_symlink() for p in root.rglob('*')):
        raise ValueError('repository test tree contains symlinks')
    # Targets are passed to pytest as data, never as options or arbitrary paths.
    for target in targets:
        if not isinstance(target, str) or target.startswith('-'):
            raise ValueError('invalid pytest target')
        path = (root / target.split('::', 1)[0]).resolve()
        if path != root and root not in path.parents:
            raise ValueError('pytest target outside repository')
    with tempfile.TemporaryDirectory(prefix='alems-repo-tests-') as scratch:
        job = dict(root=str(root), scratch=scratch, targets=list(targets), require_landlock=require_landlock,
                   libraries=interpreter_paths(python))
        env = dict(PATH='/usr/bin:/bin', HOME=scratch, TMPDIR=scratch, LANG='C.UTF-8',
                   PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
                   OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
        result = subprocess.run([python, '-I', '-S', '-B', '-c', CHILD], input=json.dumps(job),
                                cwd='/', env=env, text=True, capture_output=True, timeout=timeout,
                                preexec_fn=limits if os.name == 'posix' else None)
    if result.returncode == 86 and 'ALEMS_SANDBOX_UNAVAILABLE' in result.stderr:
        raise RuntimeError('repository test sandbox unavailable; Linux Landlock ABI 4 is required')
    return result
