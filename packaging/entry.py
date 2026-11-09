"""Double-click opens the GUI; explicit arguments retain the offline CLI."""
import multiprocessing
import os
import sys


def main():
    multiprocessing.freeze_support()
    # Windowed Windows applications have no console streams. Dependencies may
    # still write diagnostics; give them valid streams instead of None.
    for stream in ('stdin', 'stdout', 'stderr'):
        if getattr(sys, stream) is None:
            setattr(sys, stream, open(os.devnull, 'r' if stream == 'stdin' else 'w'))
    if len(sys.argv) > 1 and sys.argv[1] == '--self-test':
        from kgstv.selftest import main as selftest
        return selftest(sys.argv[2:])
    from kgstv.cli import main as cli
    return cli(sys.argv[1:] or ['gui'])


if __name__ == '__main__':
    raise SystemExit(main())
