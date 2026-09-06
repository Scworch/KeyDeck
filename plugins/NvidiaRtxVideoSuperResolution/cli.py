from __future__ import annotations

import argparse
import json
from pathlib import Path

from backup import create_backup
from discovery import detect
from messagebus import write_support_status
from vsr import read_vsr, set_vsr


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe local NVIDIA VSR diagnostics")
    parser.add_argument("--dry-run", action="store_true", help="Never perform a write")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("detect")
    subparsers.add_parser("read-vsr")
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--file", type=Path, default=Path("nvidia_backup.json"))
    set_parser = subparsers.add_parser("set-vsr")
    set_parser.add_argument("--quality", choices=("0", "1", "2", "3", "4", "5"), required=True)
    args = parser.parse_args()

    if args.command == "detect":
        result = detect()
    elif args.command == "read-vsr":
        result = read_vsr()
    elif args.command == "backup":
        if args.dry_run:
            result = {"dry_run": True, "would_write": str(args.file)}
        else:
            create_backup(args.file)
            result = {"backup": str(args.file)}
    else:
        if args.dry_run:
            result = {"dry_run": True, "would_set_quality": int(args.quality)}
        else:
            set_vsr(args.quality)
            result = {"written": False}

    result["messagebus"] = write_support_status()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
