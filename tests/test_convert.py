import subprocess
from pathlib import Path
from unittest import mock

from autolive.convert import convert_to_flac


def test_convert_invokes_ffmpeg(tmp_path: Path):
    src = tmp_path / "in.wav"
    dst = tmp_path / "out.flac"
    src.write_bytes(b"RIFF....WAVEdata")

    with mock.patch("shutil.which", return_value="/usr/local/bin/ffmpeg"):
        with mock.patch("subprocess.run") as mrun:
            mrun.return_value = subprocess.CompletedProcess(
                args=["ffmpeg"], returncode=0, stdout=b"", stderr=b""
            )
            convert_to_flac(src, dst)
            assert mrun.called
            # Ensure ffmpeg got '-c:a flac'
            called_args = mrun.call_args[0][0]
            assert "-c:a" in called_args and "flac" in called_args


