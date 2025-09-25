"""Track splitting module for exporting individual songs from long recordings.

Takes detected song spans and creates separate FLAC files with proper tagging.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional, Dict

from pydub import AudioSegment
from mutagen.flac import FLAC
from mutagen.id3 import ID3NoHeaderError

logger = logging.getLogger(__name__)


def ms_to_hms(ms: int) -> str:
    """Return mm:ss (or hh:mm:ss) string for milliseconds.
    
    Examples:
        65000 -> "1:05"
        3661000 -> "1:01:01"
    """
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes}:{seconds:02d}"


def split_tracks(
    audio_path: Path,
    song_spans: List[Tuple[int, int]],
    out_dir: Path,
    keep_head_ms: int = 1000,
    keep_tail_ms: int = 1500,
    fade_ms: int = 30,
    title_prefix: Optional[str] = None,
    band: Optional[str] = None,
    venue: Optional[str] = None,
    show_date_iso: Optional[str] = None,  # "YYYY-MM-DD"
    start_index: int = 1,
) -> List[Path]:
    """Split a long recording into separate FLAC files using given spans.
    
    Args:
        audio_path: input WAV/AIFF/FLAC file
        song_spans: list of (start_ms, end_ms) tuples
        out_dir: output folder (created if missing)
        keep_head_ms: padding before each segment within bounds
        keep_tail_ms: padding after each segment within bounds
        fade_ms: short fade in/out to avoid clicks; 0 disables
        title_prefix: e.g., "2025-09-18 Club Set" (prepended to 'Track NN')
        band: artist/band name for tags
        venue: venue name for tags
        show_date_iso: show date in YYYY-MM-DD format
        start_index: first track number (default 1)
        
    Returns:
        List of output file paths (in order)
    """
    logger.info(f"Splitting {len(song_spans)} tracks from {audio_path.name}")
    logger.info(f"Output directory: {out_dir}")
    
    # Create output directory
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Load the full audio file
    logger.info("Loading audio file...")
    try:
        audio = AudioSegment.from_file(str(audio_path))
        total_duration_ms = len(audio)
        logger.info(f"Loaded {total_duration_ms/1000:.1f}s of audio")
    except Exception as e:
        logger.error(f"Failed to load audio file: {e}")
        raise
    
    output_files = []
    
    for i, (start_ms, end_ms) in enumerate(song_spans, start_index):
        try:
            # Calculate padded boundaries
            padded_start = max(0, start_ms - keep_head_ms)
            padded_end = min(total_duration_ms, end_ms + keep_tail_ms)
            
            # Extract the segment
            segment = audio[padded_start:padded_end]
            segment_duration_ms = len(segment)
            
            logger.info(f"Track {i}: {ms_to_hms(start_ms)} - {ms_to_hms(end_ms)} "
                       f"({ms_to_hms(segment_duration_ms)})")
            
            # Apply fades if requested
            if fade_ms > 0 and segment_duration_ms > fade_ms * 2:
                segment = segment.fade_in(fade_ms).fade_out(fade_ms)
                logger.debug(f"Applied {fade_ms}ms fade in/out")
            
            # Generate output filename
            track_num = f"{i:02d}"
            output_filename = f"track_{track_num}.flac"
            output_path = out_dir / output_filename
            
            # Export using ffmpeg for high quality FLAC
            _export_segment_to_flac(segment, output_path)
            
            # Add metadata tags
            _add_flac_tags(
                output_path,
                track_num=i,
                title_prefix=title_prefix,
                band=band,
                venue=venue,
                show_date_iso=show_date_iso,
                duration_ms=segment_duration_ms
            )
            
            output_files.append(output_path)
            logger.info(f"✅ Created: {output_path.name}")
            
        except Exception as e:
            logger.error(f"❌ Failed to process track {i}: {e}")
            continue
    
    logger.info(f"Successfully created {len(output_files)} tracks")
    return output_files


def _export_segment_to_flac(segment: AudioSegment, output_path: Path) -> None:
    """Export an AudioSegment to FLAC using ffmpeg for best quality."""
    # Create temporary WAV file for ffmpeg input
    temp_wav = output_path.with_suffix('.tmp.wav')
    
    try:
        # Export segment to temporary WAV
        segment.export(str(temp_wav), format="wav")
        
        # Convert to FLAC using ffmpeg
        cmd = [
            "ffmpeg", "-y",
            "-i", str(temp_wav),
            "-c:a", "flac",
            "-compression_level", "5",  # Good balance of size/speed
            str(output_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
    finally:
        # Clean up temporary file
        if temp_wav.exists():
            temp_wav.unlink()


def _add_flac_tags(
    flac_path: Path,
    track_num: int,
    title_prefix: Optional[str] = None,
    band: Optional[str] = None,
    venue: Optional[str] = None,
    show_date_iso: Optional[str] = None,
    duration_ms: int = 0,
) -> None:
    """Add metadata tags to a FLAC file using mutagen."""
    try:
        flac_file = FLAC(str(flac_path))
        
        # Track number and title
        flac_file["TRACKNUMBER"] = str(track_num)
        
        title = f"Track {track_num:02d}"
        if title_prefix:
            title = f"{title_prefix} - {title}"
        flac_file["TITLE"] = title
        
        # Artist/Band
        if band:
            flac_file["ARTIST"] = band
            flac_file["ALBUMARTIST"] = band
        
        # Album (venue + date)
        album_parts = []
        if venue:
            album_parts.append(venue)
        if show_date_iso:
            album_parts.append(show_date_iso)
        if album_parts:
            flac_file["ALBUM"] = " - ".join(album_parts)
        
        # Date
        if show_date_iso:
            flac_file["DATE"] = show_date_iso
        
        # Duration (in seconds)
        if duration_ms > 0:
            flac_file["LENGTH"] = str(duration_ms // 1000)
        
        # Genre
        flac_file["GENRE"] = "Live Recording"
        
        # Save tags
        flac_file.save()
        logger.debug(f"Added tags to {flac_path.name}")
        
    except Exception as e:
        logger.warning(f"Failed to add tags to {flac_path.name}: {e}")
