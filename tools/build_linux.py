"""Build Linux x64 / Raspberry Pi ARM64 one-file packages in target containers."""
import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('architectures', choices=('x64', 'arm64'), nargs='+')
    args = parser.parse_args()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    for arch in args.architectures:
        platform = 'linux/amd64' if arch == 'x64' else 'linux/arm64'
        tag = 'openkgstv-build:'+arch
        subprocess.run(['docker', 'buildx', 'build', '--platform', platform, '--load', '-t', tag,
                        '-f', 'packaging/Dockerfile', '.'], cwd=ROOT, check=True)
        output = ROOT/'dist'/('linux-'+arch)
        output.mkdir(parents=True, exist_ok=True)
        subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--platform', platform,
                        '--mount', f'type=bind,source={ROOT},target=/src,readonly',
                        '--mount', f'type=bind,source={output},target=/out',
                        '-e', 'OPENKGSTV_SOURCE_COMMIT='+commit,
                        '-e', 'OPENBLAS_NUM_THREADS=1', tag,
                        'python', 'tools/build_standalone.py', '--work-dir', '/tmp/openkgstv-build',
                        '--output', '/out', '--rigctld', '/usr/bin/rigctld'], check=True)


if __name__ == '__main__':
    main()
