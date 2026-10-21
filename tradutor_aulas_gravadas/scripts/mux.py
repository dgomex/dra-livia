"""Add the Portuguese SRT to the video. Default: soft track, video/audio stream-copied (no quality loss).
--burn: hard-code subtitles into the picture (re-encodes video, audio copied)."""
import argparse
import shutil
from pathlib import Path

from common import ffmpeg_exe, job_dir, run

STYLE = ("FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
         "BorderStyle=1,Outline=2,Shadow=0,MarginV=28")


def mux(video: Path, srt: Path, burn=False, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or video.parent
    ext = video.suffix.lower()
    if burn:
        out = out_dir / f"{video.stem}.pt.burned{ext if ext in ('.mp4', '.mkv', '.mov') else '.mp4'}"
        d = job_dir(video)
        shutil.copyfile(srt, d / "burn.srt")   # simple name: avoids filter-path escaping on Windows
        run([ffmpeg_exe(), "-y", "-i", str(video.resolve()),
             "-vf", f"subtitles=burn.srt:force_style='{STYLE}'",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "copy", str(out.resolve())],
            cwd=d)
        return out
    if ext in (".mp4", ".m4v", ".mov"):
        out, codec = out_dir / f"{video.stem}.pt{ext}", "mov_text"
    else:
        out, codec = out_dir / f"{video.stem}.pt.mkv", "srt"
    run([ffmpeg_exe(), "-y", "-i", str(video), "-i", str(srt),
         "-map", "0:v", "-map", "0:a?", "-map", "1:0", "-c", "copy", "-c:s", codec,
         "-metadata:s:s:0", "language=por", "-metadata:s:s:0", "title=Português",
         "-disposition:s:0", "default", str(out)])
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("srt")
    ap.add_argument("--burn", action="store_true")
    a = ap.parse_args()
    print(mux(Path(a.video), Path(a.srt), a.burn))
