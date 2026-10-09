#!/usr/bin/env python3
"""Build a safe software release using the shared source delivery allowlist.

The historical Web packager used a broad denylist and could copy customer files.
All Web releases now use build_source_delivery's templates and verification.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from build_source_delivery import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--destination', type=Path,
                        help='Legacy option: parent directory for the generated release')
    parser.add_argument('--baseline', type=Path,
                        help='Legacy compatibility only; no host provenance paths are packaged')
    parser.add_argument('--patch-base', type=Path,
                        help='Legacy compatibility only; current workspace is the source of truth')
    args = parser.parse_args()
    if args.output_dir is not None and args.destination is not None:
        parser.error('Use either --output-dir or --destination')
    output = args.output_dir
    if args.destination is not None:
        if args.destination.exists():
            parser.error('Legacy destination must not already exist')
        output = args.destination.expanduser().resolve().parent
    build(output or Path.home() / 'Downloads', scope='software')


if __name__ == '__main__':
    main()
