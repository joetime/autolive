"""SoundCloud track upload module.

Handles single and batch track uploads with retry logic and error handling.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List, Tuple, Dict, Any

import requests

logger = logging.getLogger(__name__)

# SoundCloud API endpoints
UPLOAD_URL = "https://api.soundcloud.com/tracks"
PLAYLIST_URL = "https://api.soundcloud.com/playlists"

# Upload limits
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # Exponential backoff delays


def _should_retry(status_code: int) -> bool:
    """Determine if a request should be retried based on status code."""
    return status_code in [429, 500, 502, 503, 504]


def _get_retry_delay(attempt: int) -> float:
    """Get delay for retry attempt (exponential backoff)."""
    if attempt >= len(RETRY_DELAYS):
        return RETRY_DELAYS[-1]
    return RETRY_DELAYS[attempt]


def upload_track(
    file_path: Path, 
    title: str, 
    access_token: str, 
    sharing: str = "private"
) -> int:
    """Upload a single track to SoundCloud.
    
    Args:
        file_path: Path to FLAC file to upload
        title: Track title
        access_token: Valid SoundCloud access token
        sharing: "private" or "public"
        
    Returns:
        SoundCloud track ID
        
    Raises:
        RuntimeError: If upload fails after all retries
        ValueError: If file is too large or doesn't exist
    """
    if not file_path.exists():
        raise ValueError(f"File not found: {file_path}")
    
    file_size = file_path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        raise ValueError(f"File too large: {file_size} bytes (max: {MAX_FILE_SIZE})")
    
    logger.info(f"Uploading {file_path.name} ({file_size / 1024 / 1024:.1f}MB)")
    
    # Prepare multipart form data
    files = {
        'track[asset_data]': (file_path.name, open(file_path, 'rb'), 'audio/flac')
    }
    
    data = {
        'track[title]': title,
        'track[sharing]': sharing
    }
    
    headers = {
        'Authorization': f'OAuth {access_token}'
    }
    
    last_error = None
    
    try:
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.post(
                    UPLOAD_URL,
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=300  # 5 minutes
                )
                
                if response.status_code == 201:
                    track_data = response.json()
                    track_id = track_data['id']
                    logger.info(f"UPLOAD OK id={track_id} file={file_path.name}")
                    return track_id
                
                elif _should_retry(response.status_code):
                    if attempt < MAX_RETRIES:
                        delay = _get_retry_delay(attempt)
                        logger.warning(f"UPLOAD ERR file={file_path.name} status={response.status_code} retrying in {delay}s")
                        time.sleep(delay)
                        continue
                    else:
                        logger.error(f"UPLOAD ERR file={file_path.name} status={response.status_code} max retries exceeded")
                        raise RuntimeError(f"Upload failed after {MAX_RETRIES} retries: {response.status_code}")
                
                else:
                    # Non-retryable error
                    logger.error(f"UPLOAD ERR file={file_path.name} status={response.status_code}")
                    raise RuntimeError(f"Upload failed: {response.status_code} - {response.text}")
                    
            except requests.RequestException as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    delay = _get_retry_delay(attempt)
                    logger.warning(f"UPLOAD ERR file={file_path.name} network error retrying in {delay}s: {e}")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"UPLOAD ERR file={file_path.name} network error max retries exceeded: {e}")
                    raise RuntimeError(f"Upload failed after {MAX_RETRIES} retries: {e}")
    
    finally:
        # Close file handle
        if 'track[asset_data]' in files:
            files['track[asset_data]'][1].close()
    
    # This should never be reached, but just in case
    raise RuntimeError(f"Upload failed: {last_error}")


def upload_many(
    files: List[Path], 
    access_token: str, 
    sharing: str = "private",
    title_prefix: str | None = None
) -> Dict[str, List]:
    """Upload multiple tracks to SoundCloud.
    
    Args:
        files: List of FLAC file paths to upload
        access_token: Valid SoundCloud access token
        sharing: "private" or "public"
        title_prefix: Optional prefix for track titles
        
    Returns:
        Dict with 'uploaded' and 'failed' lists
    """
    uploaded = []
    failed = []
    
    logger.info(f"Starting batch upload of {len(files)} files")
    start_time = time.time()
    
    for i, file_path in enumerate(files, 1):
        try:
            # Generate title
            title = file_path.stem
            if title_prefix:
                title = f"{title_prefix} - {title}"
            
            # Check file size
            if file_path.stat().st_size > MAX_FILE_SIZE:
                logger.warning(f"SKIP file={file_path.name} too large")
                failed.append(file_path)
                continue
            
            track_id = upload_track(file_path, title, access_token, sharing)
            uploaded.append((file_path, track_id))
            
            # Small delay between uploads to be nice to the API
            if i < len(files):
                time.sleep(1)
                
        except Exception as e:
            logger.error(f"UPLOAD FAILED file={file_path.name} error={e}")
            failed.append(file_path)
    
    elapsed = time.time() - start_time
    logger.info(f"BATCH SUMMARY uploaded={len(uploaded)} failed={len(failed)} elapsed={elapsed:.0f}s")
    
    return {
        'uploaded': uploaded,
        'failed': failed
    }


def create_playlist(
    title: str, 
    track_ids: List[int], 
    access_token: str, 
    sharing: str = "private"
) -> int:
    """Create a playlist on SoundCloud.
    
    Args:
        title: Playlist title
        track_ids: List of SoundCloud track IDs to include
        access_token: Valid SoundCloud access token
        sharing: "private" or "public"
        
    Returns:
        SoundCloud playlist ID
        
    Raises:
        RuntimeError: If playlist creation fails
    """
    logger.info(f"Creating playlist: {title} with {len(track_ids)} tracks")
    
    # Working approach: create playlist with tracks using form data and repeated keys
    form_headers = {
        'Authorization': f'OAuth {access_token}'
    }

    form: Dict[str, Any] = {
        'playlist[title]': title,
        'playlist[sharing]': sharing,
    }
    for tid in track_ids:
        form.setdefault('playlist[tracks][][id]', []).append(str(tid))

    try:
        response = requests.post(
            PLAYLIST_URL,
            data=form,
            headers=form_headers,
            timeout=60
        )

        if response.status_code != 201:
            logger.error(f"PLAYLIST CREATE ERR status={response.status_code} {response.text}")
            raise RuntimeError(f"Playlist creation failed: {response.status_code} - {response.text}")

        playlist_info = response.json()
        playlist_id = playlist_info['id']
        logger.info(f"PLAYLIST OK id={playlist_id} title=\"{title}\" tracks={len(track_ids)}")
        return playlist_id

    except requests.RequestException as e:
        logger.error(f"PLAYLIST ERR network error: {e}")
        raise RuntimeError(f"Playlist creation failed: {e}")


def _ensure_tracks_streamable(track_ids: List[int], access_token: str, timeout_s: int = 180) -> None:
    """Poll SoundCloud until all given track IDs report streamable or timeout.

    This helps avoid a race where freshly uploaded tracks are not yet attachable to playlists.
    """
    deadline = time.time() + timeout_s
    headers = {'Authorization': f'OAuth {access_token}'}
    pending = set(track_ids)

    while pending and time.time() < deadline:
        ready_now = []
        for track_id in list(pending):
            try:
                r = requests.get(f"https://api.soundcloud.com/tracks/{track_id}", headers=headers, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    # Consider a track ready if streamable flag is present and true
                    if bool(data.get('streamable', False)):
                        ready_now.append(track_id)
                # Non-200 responses: keep waiting unless it's a hard error
            except requests.RequestException:
                # transient; continue
                pass
        for tid in ready_now:
            pending.discard(tid)
        if pending:
            time.sleep(3)

    if pending:
        logger.warning(f"Some tracks may not be fully processed yet: {sorted(pending)}")


def _update_playlist_tracks_with_retries(playlist_id: int, track_ids: List[int], access_token: str, max_attempts: int = 5) -> bool:
    """Attempt to set playlist tracks, verifying by reading back track_count.

    Returns True if verification shows tracks present, else False.
    """
    form_headers = {'Authorization': f'OAuth {access_token}'}

    def put_tracks() -> requests.Response:
        form: Dict[str, Any] = {}
        for i, tid in enumerate(track_ids):
            form[f'playlist[tracks][{i}][id]'] = tid
        return requests.put(
            f"{PLAYLIST_URL}/{playlist_id}",
            data=form,
            headers=form_headers,
            timeout=30
        )

    def read_count() -> int | None:
        try:
            r = requests.get(f"{PLAYLIST_URL}/{playlist_id}", headers=form_headers, timeout=20)
            if r.status_code == 200:
                data = r.json()
                return int(data.get('track_count') or 0)
        except Exception:
            return None
        return None

    delay = 1
    for attempt in range(1, max_attempts + 1):
        try:
            resp = put_tracks()
            if resp.status_code not in (200, 201):
                logger.warning(f"PLAYLIST UPDATE attempt {attempt} status={resp.status_code}")
            # Give API time to reflect changes
            time.sleep(delay)
            count = read_count()
            if count is not None and count >= len(track_ids):
                return True
            delay = min(delay * 2, 10)
        except requests.RequestException as e:
            logger.warning(f"PLAYLIST UPDATE attempt {attempt} network error: {e}")
            time.sleep(delay)
            delay = min(delay * 2, 10)
    return False
