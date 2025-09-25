## AutoLive - High-Level Specification (V1)

### Primary Goal
- Fully unattended pipeline: ingest long live recording → detect songs → export FLAC → deliver to SoundCloud.
- Reliability: ≥80% tracks have clean starts/ends without human edits.

### Platform & Stack
- Python 3.11+ on macOS; Homebrew `ffmpeg` available on PATH.
- Libraries: `pydub` (analysis/slicing), `mutagen` (tagging), `requests` (API, if used), `playwright` (web automation fallback).

### Modules & Interfaces
- Conversion
  - Function: `convert_to_flac(src: Path, dst: Path) -> None`
  - CLI: `python -m autolive.convert --in INPUT [--out OUT_DIR] [--no-overwrite]`

- Silence Detection
  - Function: `estimate_silence_threshold(Path) -> float` (noise-floor percentile + headroom)
  - Function: `detect_song_spans(Path, silence_thresh_db | None, min_silence_len_ms, keep_silence_ms, target_song_min_ms, target_song_max_ms, merge_adjacent_gap_ms) -> List[(start_ms, end_ms)]`

- Track Splitting & Tagging
  - Function: `split_tracks(audio_path: Path, song_spans: List[(start,end)], out_dir: Path, keep_head_ms, keep_tail_ms, fade_ms, title_prefix, band, venue, show_date_iso, start_index=1) -> List[Path]`
  - Tags: title, track number, date, optional band/venue.

- SoundCloud Delivery (pick available path)
  - OAuth REST API to upload tracks and create playlist.

### Conservative Defaults (to minimize cutoffs)
- Silence detection
  - `min_silence_len_ms ≈ 2000`
  - `keep_silence_ms ≈ 900`
  - `merge_adjacent_gap_ms ≈ 1000`
  - Auto-threshold: `bottom_percentile ≈ 0.25`, `headroom_db ≈ 3.5`
  - Targets: `target_song_min_ms ≈ 120_000` (2 min), `target_song_max_ms ≈ 600_000` (10 min)
  - Fragment control: drop spans `< 45_000 ms`
- Track export
  - Padding: `keep_head_ms ≈ 1000`, `keep_tail_ms ≈ 1500`
  - Edge fade: `fade_ms ≈ 30`

### Logging & Behavior
- Clear, one-line per file/track; show thresholds, counts, durations, sizes.
- Continue on error; summarize failures; non-zero exit if any failed.
- Idempotent file ops: skip/overwrite controls; auto-create directories.

### Config
- `config.toml` or env for:
  - Upload privacy default (private/public)
  - Optional band/venue/date defaults
  - Output directories
  - Delivery method (REST or Web Automation)
  - For REST (if possible): token storage/refresh
  - For Web Automation: persistent profile directory

### Acceptance Criteria
- Conversion CLI converts a folder of WAV/AIFF files to FLAC preserving sample rate/bit depth.
- Silence detection yields stable, merged song spans; splitting generates numbered, tagged FLACs.
- End-to-end run produces an upload (REST or web) and a date-named playlist with all successful tracks.
- Errors (missing ffmpeg, bad file, transient upload issues) are logged clearly; retries on transient cases.

### Testing
- Unit: mock `subprocess.run` for ffmpeg; basic span detection scenarios.
- Manual: run on provided long recordings; verify split boundaries and upload/playlist results.


