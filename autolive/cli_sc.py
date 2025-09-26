"""SoundCloud CLI for testing authentication, uploads, and playlists.

Provides command-line interface for incremental testing of SoundCloud integration.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import List

import toml

from .sc_oauth import ensure_access_token
from .sc_uploader import upload_track, upload_many, create_playlist

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    """Load configuration from config.toml."""
    config_path = Path("config.toml")
    if not config_path.exists():
        logger.error("config.toml not found. Please create it with your SoundCloud credentials.")
        sys.exit(1)
    
    try:
        return toml.load(config_path)
    except Exception as e:
        logger.error(f"Failed to load config.toml: {e}")
        sys.exit(1)


def cmd_auth(args) -> int:
    """Test authentication flow."""
    logger.info("Testing SoundCloud authentication...")
    
    config = load_config()
    sc_config = config.get('soundcloud', {})
    
    if not all(key in sc_config for key in ['client_id', 'client_secret', 'redirect_uri']):
        logger.error("Missing SoundCloud credentials in config.toml")
        return 1
    
    try:
        access_token = ensure_access_token(sc_config)
        logger.info(f"Authentication successful! Token: {access_token[:10]}...")
        return 0
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        return 1


def cmd_upload(args) -> int:
    """Upload a single track."""
    if not args.file.exists():
        logger.error(f"File not found: {args.file}")
        return 1
    
    config = load_config()
    sc_config = config.get('soundcloud', {})
    
    try:
        access_token = ensure_access_token(sc_config)
        sharing = sc_config.get('sharing', 'private')
        
        track_id = upload_track(args.file, args.title, access_token, sharing)
        print(f"UPLOAD OK id={track_id} file={args.file.name}")
        return 0
        
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        return 1


def cmd_upload_dir(args) -> int:
    """Upload all FLAC files from a directory."""
    if not args.dir.exists():
        logger.error(f"Directory not found: {args.dir}")
        return 1
    
    # Find all FLAC files
    flac_files = list(args.dir.glob("*.flac"))
    if not flac_files:
        logger.error(f"No FLAC files found in {args.dir}")
        return 1
    
    config = load_config()
    sc_config = config.get('soundcloud', {})
    
    try:
        access_token = ensure_access_token(sc_config)
        sharing = sc_config.get('sharing', 'private')
        
        result = upload_many(flac_files, access_token, sharing, args.title_prefix)
        
        print(f"Uploaded {len(result['uploaded'])} tracks:")
        for file_path, track_id in result['uploaded']:
            print(f"  {track_id}: {file_path.name}")
        
        if result['failed']:
            print(f"Failed {len(result['failed'])} tracks:")
            for file_path in result['failed']:
                print(f"  {file_path.name}")
        
        return 1 if result['failed'] else 0
        
    except Exception as e:
        logger.error(f"Batch upload failed: {e}")
        return 1


def cmd_playlist(args) -> int:
    """Create a playlist with given track IDs."""
    config = load_config()
    sc_config = config.get('soundcloud', {})
    
    try:
        access_token = ensure_access_token(sc_config)
        sharing = sc_config.get('sharing', 'private')
        
        playlist_id = create_playlist(args.title, args.track_ids, access_token, sharing)
        print(f"PLAYLIST OK id={playlist_id} title=\"{args.title}\"")
        return 0
        
    except Exception as e:
        logger.error(f"Playlist creation failed: {e}")
        return 1




def cmd_poc(args) -> int:
    """Proof-of-concept: upload directory and create playlist."""
    if not args.dir.exists():
        logger.error(f"Directory not found: {args.dir}")
        return 1
    
    # Find all FLAC files
    flac_files = list(args.dir.glob("*.flac"))
    if not flac_files:
        logger.error(f"No FLAC files found in {args.dir}")
        return 1
    
    config = load_config()
    sc_config = config.get('soundcloud', {})
    
    start_time = time.time()
    
    try:
        # Step 1: Ensure access token
        logger.info("Step 1: Authenticating...")
        access_token = ensure_access_token(sc_config)
        
        # Step 2: Upload all tracks
        logger.info(f"Step 2: Uploading {len(flac_files)} tracks...")
        sharing = args.sharing or sc_config.get('sharing', 'private')
        result = upload_many(flac_files, access_token, sharing, args.title_prefix)
        
        if not result['uploaded']:
            logger.error("No tracks uploaded successfully")
            return 1
        
        # Step 3: Create playlist
        logger.info("Step 3: Creating playlist...")
        track_ids = [track_id for _, track_id in result['uploaded']]
        playlist_id = create_playlist(args.title, track_ids, access_token, sharing)
        
        # Summary
        elapsed = time.time() - start_time
        print(f"\nSUMMARY uploaded={len(result['uploaded'])} failed={len(result['failed'])} elapsed={elapsed:.0f}s")
        print(f"Playlist: https://soundcloud.com/playlists/{playlist_id}")
        
        return 1 if result['failed'] else 0
        
    except Exception as e:
        logger.error(f"POC failed: {e}")
        return 1


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="SoundCloud integration CLI")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Auth command
    auth_parser = subparsers.add_parser('auth', help='Test authentication')
    
    # Upload command
    upload_parser = subparsers.add_parser('upload', help='Upload single track')
    upload_parser.add_argument('--file', type=Path, required=True, help='FLAC file to upload')
    upload_parser.add_argument('--title', required=True, help='Track title')
    
    # Upload directory command
    upload_dir_parser = subparsers.add_parser('upload-dir', help='Upload all FLAC files from directory')
    upload_dir_parser.add_argument('--dir', type=Path, required=True, help='Directory containing FLAC files')
    upload_dir_parser.add_argument('--title-prefix', help='Prefix for track titles')
    
    # Playlist command
    playlist_parser = subparsers.add_parser('playlist', help='Create playlist')
    playlist_parser.add_argument('--title', required=True, help='Playlist title')
    playlist_parser.add_argument('--track-ids', type=int, nargs='+', required=True, help='Track IDs to include')
    
    # POC command
    poc_parser = subparsers.add_parser('poc', help='Proof-of-concept: upload dir and create playlist')
    poc_parser.add_argument('--dir', type=Path, required=True, help='Directory containing FLAC files')
    poc_parser.add_argument('--title', required=True, help='Playlist title')
    poc_parser.add_argument('--sharing', choices=['private', 'public'], help='Upload visibility')
    poc_parser.add_argument('--title-prefix', help='Prefix for track titles')

    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Route to appropriate command
    commands = {
        'auth': cmd_auth,
        'upload': cmd_upload,
        'upload-dir': cmd_upload_dir,
        'playlist': cmd_playlist,
        'poc': cmd_poc
    }
    
    return commands[args.command](args)


if __name__ == '__main__':
    sys.exit(main())
