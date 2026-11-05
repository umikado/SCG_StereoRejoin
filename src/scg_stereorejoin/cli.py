"""Command-line interface for SCG_StereoRejoin."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scg_stereorejoin import __version__
from scg_stereorejoin.pairing import PatternError, default_patterns_text, load_patterns
from scg_stereorejoin.rejoin import RejoinError, format_report, process, report_json

EPILOG = """\
examples:
  scg-stereorejoin Dialogue.L.wav Dialogue.R.wav
  scg-stereorejoin -r -o ./stereo ./exports
  scg-stereorejoin -n -r ./exports
  scg-stereorejoin --pad Take.L.wav Take.R.wav
  scg-stereorejoin --pattern '.SL/.SR' ./recorder
  scg-stereorejoin --gui

Chinese documentation: README.zh-CN.md
"""


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="scg-stereorejoin",
        description=(
            "Re-join split dual-mono WAV files from Pro Tools, Cubase, and Nuendo "
            "into one bit-exact interleaved stereo WAV."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    parser.add_argument("paths", nargs="*", type=Path, help="WAV files and/or folders")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output directory (default: write next to each left file)",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="enter subfolders when a path is a directory",
    )
    parser.add_argument(
        "--pattern",
        action="append",
        default=[],
        metavar="LEFT/RIGHT",
        help="extra suffix pair, for example .SL/.SR (repeatable; spaces are significant)",
    )
    parser.add_argument(
        "--patterns-file",
        type=Path,
        help="text file with one LEFT/RIGHT pattern per line; # starts a comment",
    )
    parser.add_argument(
        "--no-default-patterns",
        action="store_true",
        help="do not use the built-in .L/.R, Left/Right, and .1/.2 patterns",
    )
    parser.add_argument(
        "--pad",
        action="store_true",
        help="if lengths differ, pad the shorter side with silence instead of refusing",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an output file that already exists",
    )
    parser.add_argument(
        "--delete-sources",
        action="store_true",
        help="delete the two mono files after a successful join",
    )
    parser.add_argument(
        "--bw64",
        action="store_true",
        help="use BW64 instead of RF64 when the output is larger than 4 GB",
    )
    parser.add_argument("-n", "--dry-run", action="store_true", help="report the plan and write nothing")
    parser.add_argument("--json", action="store_true", help="print a JSON report")
    parser.add_argument("-v", "--verbose", action="store_true", help="include format, timestamp, and chunk ids")
    parser.add_argument("-q", "--quiet", action="store_true", help="print warnings, refusals, and the summary")
    parser.add_argument("--gui", action="store_true", help="open the window instead of joining in the terminal")
    parser.add_argument("--version", action="version", version=f"SCG_StereoRejoin {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.gui:
        from scg_stereorejoin.gui import GuiPrefill, main as gui_main

        text = _pattern_text(args)
        return gui_main(
            GuiPrefill(
                paths=list(args.paths),
                output="" if args.output is None else str(args.output),
                recursive=args.recursive,
                pad=args.pad,
                overwrite=args.overwrite,
                delete_sources=args.delete_sources,
                bw64=args.bw64,
                dry_run=args.dry_run,
                patterns_text=text,
            )
        )
    if not args.paths:
        parser.print_help()
        return 2
    try:
        patterns = load_patterns(
            args.pattern,
            patterns_file=args.patterns_file,
            use_defaults=not args.no_default_patterns,
        )
    except PatternError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        report = process(
            args.paths,
            output_dir=args.output,
            recursive=args.recursive,
            patterns=patterns,
            pad=args.pad,
            overwrite=args.overwrite,
            delete_sources=args.delete_sources,
            dry_run=args.dry_run,
            large_container="bw64" if args.bw64 else "rf64",
        )
    except RejoinError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        json.dump(
            report_json(report, version=__version__),
            sys.stdout,
            indent=2,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
    else:
        verbose = args.verbose
        quiet = args.quiet and not args.verbose
        print(format_report(report, verbose=verbose, quiet=quiet))
    return 0 if report.ok else 1


def _pattern_text(args) -> str:
    if not args.pattern and not args.patterns_file and not args.no_default_patterns:
        return default_patterns_text()
    lines = list(args.pattern)
    if args.patterns_file and args.patterns_file.is_file():
        lines.extend(args.patterns_file.read_text(encoding="utf-8").splitlines())
    if not args.no_default_patterns:
        lines.extend(default_patterns_text().splitlines())
    return "\n".join(lines) + ("\n" if lines else "")


if __name__ == "__main__":
    raise SystemExit(main())
