"""Silence detection module for finding musical "song" regions in long recordings.

Uses pydub's silence utilities with auto-threshold estimation and intelligent merging.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

from pydub import AudioSegment
from pydub.silence import detect_nonsilent

logger = logging.getLogger(__name__)


def estimate_silence_threshold(
    audio_path: Path,
    analysis_sample_sec: int = 60,
    analysis_seg_ms: int = 50,
    bottom_percentile: float = 0.25,
    floor_headroom_db: float = 3.5,
) -> float:
    """Return an estimated silence threshold (dBFS) from the audio.
    
    Analyzes a sample of the audio to find the noise floor, then adds headroom.
    
    Args:
        audio_path: Path to audio file
        analysis_sample_sec: How many seconds from start to analyze (default: 60)
        analysis_seg_ms: Segment size for analysis in milliseconds (default: 50)
        bottom_percentile: Percentile of quietest segments to use as noise floor (default: 0.30)
        floor_headroom_db: Extra dB above noise floor for threshold (default: 2.0)
        
    Returns:
        Estimated silence threshold in dBFS (negative value)
    """
    logger.info(f"Estimating silence threshold for {audio_path.name}")
    
    # Load audio and take analysis sample
    audio = AudioSegment.from_file(str(audio_path))
    sample_duration_ms = min(analysis_sample_sec * 1000, len(audio))
    sample = audio[:sample_duration_ms]
    
    logger.info(f"Analyzing {sample_duration_ms/1000:.1f}s sample with {analysis_seg_ms}ms segments")
    
    # Split into segments and measure dBFS
    segment_dbs = []
    for i in range(0, len(sample), analysis_seg_ms):
        segment = sample[i:i + analysis_seg_ms]
        if len(segment) > 0:
            db = segment.dBFS
            if db != float('-inf'):  # Skip completely silent segments
                segment_dbs.append(db)
    
    if not segment_dbs:
        logger.warning("No valid audio segments found, using conservative threshold")
        return -40.0
    
    # Sort and find noise floor
    segment_dbs.sort()
    floor_index = int(len(segment_dbs) * bottom_percentile)
    noise_floor_db = segment_dbs[floor_index]
    
    # Add headroom to get threshold
    threshold_db = noise_floor_db + floor_headroom_db
    
    logger.info(f"Found {len(segment_dbs)} segments, noise floor: {noise_floor_db:.1f} dBFS")
    logger.info(f"Estimated threshold: {threshold_db:.1f} dBFS (floor + {floor_headroom_db} dB)")
    
    return threshold_db


def detect_song_spans(
    audio_path: Path,
    silence_thresh_db: float | None = None,
    min_silence_len_ms: int = 2000,
    keep_silence_ms: int = 900,
    target_song_min_ms: int = 120_000,  # 2 min
    target_song_max_ms: int = 600_000,  # 10 min
    merge_adjacent_gap_ms: int = 1000,
) -> List[Tuple[int, int]]:
    """Detect "song" spans as (start_ms, end_ms) from audio file.
    
    Uses pydub's silence detection with intelligent merging to find song-sized segments.
    
    Args:
        audio_path: Path to audio file
        silence_thresh_db: Silence threshold in dBFS. If None, auto-estimates.
        min_silence_len_ms: Minimum silence length to split on (default: 1500ms)
        keep_silence_ms: Silence to keep at start/end of segments (default: 200ms)
        target_song_min_ms: Minimum target song length (default: 180000ms = 3min)
        target_song_max_ms: Maximum target song length (default: 420000ms = 7min)
        merge_adjacent_gap_ms: Merge segments within this gap (default: 10ms)
        
    Returns:
        List of (start_ms, end_ms) tuples representing song segments
    """
    logger.info(f"Detecting song spans in {audio_path.name}")
    
    # Auto-estimate threshold if not provided
    if silence_thresh_db is None:
        silence_thresh_db = estimate_silence_threshold(audio_path)
        logger.info(f"Using auto-estimated threshold: {silence_thresh_db:.1f} dBFS")
    else:
        logger.info(f"Using provided threshold: {silence_thresh_db:.1f} dBFS")
    
    # Load audio
    audio = AudioSegment.from_file(str(audio_path))
    total_duration_ms = len(audio)
    logger.info(f"Audio duration: {total_duration_ms/1000:.1f}s")
    
    # Detect non-silent regions
    nonsilent_ranges = detect_nonsilent(
        audio,
        min_silence_len=min_silence_len_ms,
        silence_thresh=silence_thresh_db
    )
    
    # Apply keep_silence padding to the detected ranges
    if keep_silence_ms > 0:
        padded_ranges = []
        for start, end in nonsilent_ranges:
            new_start = max(0, start - keep_silence_ms)
            new_end = min(len(audio), end + keep_silence_ms)
            padded_ranges.append((new_start, new_end))
        nonsilent_ranges = padded_ranges
    
    logger.info(f"Found {len(nonsilent_ranges)} non-silent regions")
    
    if not nonsilent_ranges:
        logger.warning("No non-silent regions found")
        return []
    
    # Merge adjacent segments with small gaps
    merged_ranges = _merge_adjacent_ranges(nonsilent_ranges, merge_adjacent_gap_ms)
    logger.info(f"After merging small gaps: {len(merged_ranges)} segments")
    
    # Filter and merge to target song lengths
    song_spans = _merge_to_target_lengths(
        merged_ranges, 
        target_song_min_ms, 
        target_song_max_ms
    )

    # Drop very short fragments (< 45s) per spec
    min_fragment_ms = 45_000
    pre_filter_count = len(song_spans)
    song_spans = [
        (s, e) for (s, e) in song_spans
        if (e - s) >= min_fragment_ms
    ]
    dropped = pre_filter_count - len(song_spans)
    if dropped:
        logger.info(f"Dropped {dropped} short fragment(s) < {min_fragment_ms}ms")
    
    logger.info(f"Final song spans: {len(song_spans)} segments")
    for i, (start, end) in enumerate(song_spans, 1):
        duration_s = (end - start) / 1000
        logger.info(f"  Song {i}: {start/1000:.1f}s - {end/1000:.1f}s ({duration_s:.1f}s)")
    
    return song_spans


def _merge_adjacent_ranges(ranges: List[Tuple[int, int]], gap_ms: int) -> List[Tuple[int, int]]:
    """Merge adjacent ranges with gaps smaller than gap_ms."""
    if not ranges:
        return []
    
    merged = [ranges[0]]
    
    for current_start, current_end in ranges[1:]:
        last_start, last_end = merged[-1]
        
        # If gap is small enough, merge
        if current_start - last_end <= gap_ms:
            merged[-1] = (last_start, current_end)
        else:
            merged.append((current_start, current_end))
    
    return merged


def _merge_to_target_lengths(
    ranges: List[Tuple[int, int]], 
    min_length_ms: int, 
    max_length_ms: int
) -> List[Tuple[int, int]]:
    """Merge ranges to achieve target song lengths."""
    if not ranges:
        return []
    
    result = []
    current_start, current_end = ranges[0]
    
    for next_start, next_end in ranges[1:]:
        current_length = current_end - current_start
        next_length = next_end - next_start
        combined_length = next_end - current_start
        
        # If current segment is too short, try to merge with next
        if current_length < min_length_ms:
            # If combining would exceed max length, start new segment
            if combined_length > max_length_ms:
                result.append((current_start, current_end))
                current_start, current_end = next_start, next_end
            else:
                # Merge with next segment
                current_end = next_end
        else:
            # Current segment is long enough, start new one
            result.append((current_start, current_end))
            current_start, current_end = next_start, next_end
    
    # Add the last segment
    result.append((current_start, current_end))
    
    return result
