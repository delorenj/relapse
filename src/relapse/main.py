#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time


@dataclass
class Batch:
    paths: list[Path]
    max_ts: float
    min_ts: float


@dataclass(frozen=True)
class SelectedFile:
    absolute: Path
    relative: Path


@dataclass(frozen=True)
class FileRecord:
    absolute: Path
    relative: Path
    mtime: float


@dataclass(frozen=True)
class Selection:
    batch: Batch
    files: list[SelectedFile]


def parse_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Datetime must be ISO 8601 (e.g. 2025-01-20, 2025-01-20T12:34:56, "
            "2025-01-20T12:34:56Z, 2025-01-20T12:34:56-05:00)"
        ) from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def collect_files(root: Path) -> list[tuple[Path, float]]:
    files: list[tuple[Path, float]] = []
    for path in root.rglob("*"):
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except (FileNotFoundError, PermissionError):
            continue
        files.append((path.resolve(), stat.st_mtime))
    return files


def build_batches(files: list[tuple[Path, float]], max_gap: float) -> list[Batch]:
    files.sort(key=lambda item: item[1], reverse=True)
    batches: list[Batch] = []
    for path, mtime in files:
        if not batches:
            batches.append(Batch(paths=[path], max_ts=mtime, min_ts=mtime))
            continue
        current = batches[-1]
        gap = current.min_ts - mtime
        if gap > max_gap:
            batches.append(Batch(paths=[path], max_ts=mtime, min_ts=mtime))
        else:
            current.paths.append(path)
            current.min_ts = mtime
    return batches


def choose_batch_by_datetime(batches: list[Batch], dt: datetime) -> Batch | None:
    if not batches:
        return None
    dt_ts = dt.timestamp()
    for batch in batches:
        if batch.min_ts <= dt_ts <= batch.max_ts:
            return batch
    if dt_ts >= batches[0].max_ts:
        return batches[0]
    for batch in batches:
        if batch.max_ts <= dt_ts:
            return batch
    return batches[-1]


def add_root_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Root directory to scan (default: current directory).",
    )
    parser.add_argument(
        "--filter",
        choices=["all", "docs", "code"],
        default="all",
        help="Filter selected files to docs or code (default: all).",
    )


def add_batch_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "batch",
        nargs="?",
        help=(
            "Batch index (0=latest, 1=previous, ...) or ISO datetime. "
            "Digits-only values are treated as an index; use --datetime to force datetime."
        ),
    )
    parser.add_argument(
        "--datetime",
        dest="datetime_value",
        type=str,
        help="ISO 8601 datetime to select the batch at or before that time.",
    )
    parser.add_argument(
        "--index",
        dest="index",
        type=int,
        help="Explicit batch index (0=latest, 1=previous, ...).",
    )
    parser.add_argument(
        "--max-gap-seconds",
        type=float,
        default=120.0,
        help="Maximum seconds between file mtimes to treat as the same batch.",
    )


def add_common_options(parser: argparse.ArgumentParser) -> None:
    add_batch_options(parser)
    add_root_options(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Work with file batches based on modification-time gaps. "
            "Use 'print', 'zip', 'code2prompt', or 'copy' commands."
        )
    )
    subparsers = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    add_common_options(common)

    timeline_common = argparse.ArgumentParser(add_help=False)
    add_root_options(timeline_common)

    print_parser = subparsers.add_parser(
        "print",
        parents=[common],
        help="Print selected file paths.",
    )
    print_parser.add_argument(
        "--format",
        choices=["relative", "absolute", "name"],
        default="relative",
        help="Output format for paths (default: relative).",
    )
    print_parser.add_argument(
        "--pretty",
        action="store_true",
        help="Add a batch header with the time window.",
    )
    print_parser.set_defaults(func=cmd_print)

    zip_parser = subparsers.add_parser(
        "zip",
        parents=[common],
        help="Create a .tar.gz archive of selected files.",
    )
    zip_parser.add_argument(
        "--output",
        "-o",
        default="batch.tar.gz",
        help="Output tar.gz path, or '-' for stdout (default: batch.tar.gz).",
    )
    zip_parser.set_defaults(func=cmd_zip)

    code2prompt_parser = subparsers.add_parser(
        "code2prompt",
        parents=[common],
        help="Run code2prompt on selected files and print its output.",
    )
    code2prompt_parser.set_defaults(func=cmd_code2prompt)

    ccc_parser = subparsers.add_parser(
        "ccc",
        parents=[common],
        help="Alias for code2prompt.",
    )
    ccc_parser.set_defaults(func=cmd_code2prompt)

    copy_parser = subparsers.add_parser(
        "copy",
        parents=[common],
        help="Copy selected files to a destination, preserving tree structure.",
    )
    copy_parser.add_argument(
        "dest",
        type=Path,
        help="Destination directory to copy files into.",
    )
    copy_parser.set_defaults(func=cmd_copy)

    timeline_parser = subparsers.add_parser(
        "timeline",
        parents=[timeline_common],
        help="Plot file modification times on a normalized timeline.",
    )
    timeline_parser.add_argument(
        "--bins",
        type=int,
        default=60,
        help="Number of histogram bins for the timeline.",
    )
    timeline_parser.add_argument(
        "--width",
        type=int,
        default=100,
        help="Plot width in characters (plotext only).",
    )
    timeline_parser.add_argument(
        "--height",
        type=int,
        default=20,
        help="Plot height in characters (plotext only).",
    )
    timeline_parser.set_defaults(func=cmd_timeline)

    return parser


def parse_selection_args(args: argparse.Namespace) -> tuple[int | None, datetime | None]:
    if args.index is not None and args.datetime_value is not None:
        raise ValueError("Use only one of --index or --datetime.")

    batch_index: int | None = None
    batch_datetime: datetime | None = None

    if args.index is not None:
        batch_index = args.index
    elif args.datetime_value is not None:
        batch_datetime = parse_datetime(args.datetime_value)
    elif args.batch is not None:
        if args.batch.isdigit():
            batch_index = int(args.batch)
        else:
            batch_datetime = parse_datetime(args.batch)

    if batch_index is not None and batch_index < 0:
        raise ValueError("Batch index must be >= 0.")

    return batch_index, batch_datetime


def classify_path(root: Path, relative: Path) -> str:
    if root.name == "docs":
        return "docs"
    if relative.parts and relative.parts[0] == "docs":
        return "docs"
    return "code"


def collect_records(root: Path, filter_value: str) -> list[FileRecord]:
    files = collect_files(root)
    records: list[FileRecord] = []
    for path, mtime in files:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if filter_value != "all" and classify_path(root, relative) != filter_value:
            continue
        records.append(FileRecord(absolute=path, relative=relative, mtime=mtime))
    return records


def select_files(args: argparse.Namespace) -> Selection | None:
    batch_index, batch_datetime = parse_selection_args(args)

    root = args.root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Root does not exist: {root}")

    files = collect_files(root)
    if not files:
        return None

    batches = build_batches(files, args.max_gap_seconds)

    chosen: Batch | None
    if batch_datetime is not None:
        chosen = choose_batch_by_datetime(batches, batch_datetime)
    else:
        idx = batch_index or 0
        if idx >= len(batches):
            raise IndexError(
                f"Requested batch {idx}, but only {len(batches)} batch(es) found."
            )
        chosen = batches[idx]

    if chosen is None:
        return None

    selected: dict[str, SelectedFile] = {}
    for path in chosen.paths:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if args.filter != "all" and classify_path(root, relative) != args.filter:
            continue
        key = str(relative)
        selected[key] = SelectedFile(absolute=path, relative=relative)

    ordered = [selected[key] for key in sorted(selected)]
    return Selection(batch=chosen, files=ordered)


def format_path(selected: SelectedFile, fmt: str) -> str:
    if fmt == "absolute":
        return str(selected.absolute)
    if fmt == "name":
        return selected.absolute.name
    return str(selected.relative)


def fuzzy_delta(seconds: float) -> str:
    if seconds < 0:
        seconds = abs(seconds)
        direction = "from now"
    else:
        direction = "ago"
    if seconds < 60:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        return f"{round(minutes)}m {direction}"
    hours = minutes / 60
    if hours < 24:
        return f"{round(hours)}h {direction}"
    days = hours / 24
    if days < 30:
        return f"{round(days)}d {direction}"
    months = days / 30
    if months < 12:
        return f"{round(months)}mo {direction}"
    years = months / 12
    return f"{round(years)}y {direction}"


def format_human(dt: datetime) -> str:
    now = datetime.now()
    if dt.year != now.year:
        return dt.strftime("%b %d %Y %H:%M")
    return dt.strftime("%b %d %H:%M")


def format_window(start_ts: float, end_ts: float) -> str:
    start_dt = datetime.fromtimestamp(start_ts)
    end_dt = datetime.fromtimestamp(end_ts)
    if start_dt.date() == end_dt.date():
        start_label = format_human(start_dt)
        end_label = end_dt.strftime("%H:%M")
    else:
        start_label = format_human(start_dt)
        end_label = format_human(end_dt)
    duration = abs(end_ts - start_ts)
    now = time.time()
    start_fuzzy = fuzzy_delta(now - start_ts)
    end_fuzzy = fuzzy_delta(now - end_ts)
    return f"{start_label}–{end_label} (≈{fuzzy_delta(duration)}; {start_fuzzy} to {end_fuzzy})"


def cmd_print(args: argparse.Namespace) -> int:
    selection = select_files(args)
    if selection is None:
        return 0
    if args.pretty:
        window = format_window(selection.batch.min_ts, selection.batch.max_ts)
        print(f"Batch: {window} ({len(selection.files)} files)")
    for item in selection.files:
        print(format_path(item, args.format))
    return 0


def cmd_zip(args: argparse.Namespace) -> int:
    selection = select_files(args)
    if selection is None or not selection.files:
        return 0

    output = args.output
    if output == "-":
        tar = tarfile.open(fileobj=sys.stdout.buffer, mode="w:gz")
        should_close = True
    else:
        output_path = Path(output)
        if output_path.parent:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        tar = tarfile.open(output, mode="w:gz")
        should_close = True

    try:
        for item in selection.files:
            tar.add(item.absolute, arcname=item.relative)
    finally:
        if should_close:
            tar.close()
    return 0


def cmd_code2prompt(args: argparse.Namespace) -> int:
    selection = select_files(args)
    if selection is None or not selection.files:
        return 0
    cmd = ["code2prompt", *[str(item.absolute) for item in selection.files]]
    return subprocess.call(cmd)


def cmd_copy(args: argparse.Namespace) -> int:
    selection = select_files(args)
    if selection is None or not selection.files:
        return 0

    dest = args.dest.resolve()
    for item in selection.files:
        target = dest / item.relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.absolute, target)
    return 0


def render_timeline_ascii(
    normalized: list[float], min_label: str, max_label: str, bins: int
) -> None:
    width = max(10, bins)
    counts = [0] * width
    for value in normalized:
        idx = int(round(value * (width - 1)))
        if idx < 0:
            idx = 0
        if idx >= width:
            idx = width - 1
        counts[idx] += 1
    max_count = max(counts) if counts else 0
    ramp = " .:-=+*#%@"
    if max_count == 0:
        line = " " * width
    else:
        line = "".join(
            ramp[int(count / max_count * (len(ramp) - 1))] for count in counts
        )
    print(f"{min_label} |{line}| {max_label}")


def cmd_timeline(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    if not root.exists():
        print(f"Root does not exist: {root}", file=sys.stderr)
        return 2
    if args.bins <= 0:
        print("Bins must be > 0.", file=sys.stderr)
        return 2
    if args.width <= 0 or args.height <= 0:
        print("Width and height must be > 0.", file=sys.stderr)
        return 2

    records = collect_records(root, args.filter)
    if not records:
        return 0

    times = [record.mtime for record in records]
    min_ts = min(times)
    max_ts = max(times)
    if max_ts == min_ts:
        normalized = [0.5 for _ in times]
    else:
        span = max_ts - min_ts
        normalized = [(value - min_ts) / span for value in times]

    min_label = datetime.fromtimestamp(min_ts).isoformat(timespec="seconds")
    max_label = datetime.fromtimestamp(max_ts).isoformat(timespec="seconds")

    try:
        import plotext as plt
    except ModuleNotFoundError:
        print(
            "plotext not installed; using ASCII fallback. "
            "Install with `pip install plotext` for a richer plot.",
            file=sys.stderr,
        )
        render_timeline_ascii(normalized, min_label, max_label, args.bins)
        return 0

    plt.hist(normalized, args.bins)
    plt.plotsize(args.width, args.height)
    plt.xlim(0, 1)
    plt.title(f"File mtime timeline ({len(records)} files)")
    plt.xlabel(f"oldest {min_label} -> newest {max_label}")
    plt.ylabel("files")
    plt.xticks([0, 0.25, 0.5, 0.75, 1], ["0.0", "0.25", "0.5", "0.75", "1.0"])
    plt.show()
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = build_parser()
    commands = {"print", "zip", "code2prompt", "ccc", "copy", "timeline"}
    if argv and argv[0] not in commands and not argv[0].startswith("-"):
        argv = ["print", *argv]
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv[1:])
    if not getattr(args, "command", None):
        build_parser().print_help()
        return 2
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, IndexError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
