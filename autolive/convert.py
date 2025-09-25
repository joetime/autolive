"""WAV/AIFF to FLAC converter using ffmpeg.

Provides a function `convert_to_flac` and a CLI entry point.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

SUPPORTED_EXTS = {".wav", ".aif", ".aiff"}


def bytes_to_human(n: int) -> str:
    """Convert a byte count to a human-friendly string.

    Examples: 1024 -> "1.0 KiB", 1048576 -> "1.0 MiB".
    """
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(n)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024.0


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    """Run a subprocess command and return CompletedProcess.

    Raises subprocess.CalledProcessError on non-zero exit.
    """
    return subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _probe_duration(input_path: Path) -> str:
    """Return media duration as a short string via ffprobe, e.g., "3m12s" or "12.3s".

    If probing fails, returns "?s".
    """
    if shutil.which("ffprobe") is None:
        return "?s"
    try:
        # Extract duration in seconds with high precision
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(input_path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        out = proc.stdout.strip()
        seconds = float(out)
        if seconds >= 60:
            minutes = int(seconds // 60)
            rem = seconds - minutes * 60
            if rem < 9.95:
                # Keep one decimal for short remainder
                return f"{minutes}m{rem:.1f}s"
            return f"{minutes}m{int(round(rem))}s"
        return f"{seconds:.1f}s"
    except Exception:
        return "?s"


def convert_to_flac(src: Path, dst: Path) -> None:
    """Convert a single WAV/AIFF file at `src` to FLAC at `dst` using ffmpeg.

    Preserves sample rate and bit depth (no resampling), using ffmpeg's FLAC encoder.
    Overwrites `dst` if it exists.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH. Please install ffmpeg.")

    dst.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-c:a",
        "flac",
        str(dst),
    ]
    _run(cmd)


def _gather_inputs(root: Path) -> Iterable[Path]:
    """Yield supported audio files from `root`. Recurse if `root` is a directory."""
    if root.is_file():
        if root.suffix.lower() in SUPPORTED_EXTS:
            yield root
        return
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
            yield p


def _derive_output_path(in_file: Path, out_dir: Path) -> Path:
    return out_dir / (in_file.stem + ".flac")


def _convert_one(in_file: Path, out_file: Path, overwrite: bool) -> Tuple[bool, str]:
    """Convert one file and return (ok, message). Never raises.

    Logs concise per-file message including duration and output size on success.
    """
    duration = _probe_duration(in_file)
    try:
        if shutil.which("ffmpeg") is None:
            return False, "ffmpeg not found in PATH"

        out_file.parent.mkdir(parents=True, exist_ok=True)

        cmd = ["ffmpeg"]
        if overwrite:
            cmd.append("-y")
        cmd += ["-i", str(in_file), "-c:a", "flac", str(out_file)]

        if not overwrite and out_file.exists():
            return True, f"[SKIP] {in_file.name} exists"

        _run(cmd)

        size = out_file.stat().st_size if out_file.exists() else 0
        return True, f"[OK] {in_file.name} {duration} -> {bytes_to_human(size)}"
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("utf-8", errors="ignore") if isinstance(e.stderr, (bytes, bytearray)) else str(e)
        return False, f"[ERR] {in_file.name}: ffmpeg failed ({e.returncode})"
    except Exception as e:
        return False, f"[ERR] {in_file.name}: {e}"


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert WAV/AIFF to FLAC using ffmpeg")
    parser.add_argument("--in", dest="input_path", required=True, help="Input file or directory")
    parser.add_argument("--out", dest="out_dir", default="out", help="Output directory (default: ./out)")
    ow_group = parser.add_mutually_exclusive_group()
    ow_group.add_argument("--overwrite", dest="overwrite", action="store_true", help="Overwrite existing files (default)")
    ow_group.add_argument("--no-overwrite", dest="overwrite", action="store_false", help="Do not overwrite existing files")
    parser.set_defaults(overwrite=True)

    args = parser.parse_args(argv)

    input_path = Path(args.input_path).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()

    print(f"AutoLive convert: input={input_path} out={out_dir} overwrite={args.overwrite}")

    if shutil.which("ffmpeg") is None:
        print("[ERR] ffmpeg not found in PATH. Install via Homebrew: brew install ffmpeg", file=sys.stderr)
        return 2

    if not input_path.exists():
        print(f"[ERR] Input path does not exist: {input_path}", file=sys.stderr)
        return 2

    files = list(_gather_inputs(input_path))
    if not files:
        print("No input audio files found (.wav, .aif, .aiff).")
        return 0

    print(f"Found {len(files)} file(s). Starting conversion...")

    failures = 0
    for f in files:
        out_file = _derive_output_path(f, out_dir)
        ok, msg = _convert_one(f, out_file, overwrite=args.overwrite)
        print(msg)
        if not ok:
            failures += 1

    print(f"Done. {len(files) - failures} succeeded, {failures} failed.")
    return 1 if failures > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())


