"""Extract 16 kHz mono WAV from a video (local only)."""
import sys
from pathlib import Path

from common import ffmpeg_exe, job_dir, run


def extract(video: Path) -> Path:
    out = job_dir(video) / "audio.wav"
    if not out.exists():
        run([ffmpeg_exe(), "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", str(out)])
    return out


if __name__ == "__main__":
    print(extract(Path(sys.argv[1])))
