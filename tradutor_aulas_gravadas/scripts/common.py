"""Shared helpers: paths, ffmpeg lookup, SRT time formatting, JSON IO."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"

# Windows consoles default to cp1252; subtitles contain characters outside it.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def ffmpeg_exe() -> str:
    """PATH ffmpeg first, then the binary bundled by imageio-ffmpeg."""
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("ffmpeg not found. Run: python scripts/setup.py")


def run(cmd, check=True, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if check and r.returncode != 0:
        sys.exit(f"command failed: {' '.join(map(str, cmd))}\n{r.stderr[-1500:]}")
    return r


def job_dir(video: Path) -> Path:
    d = WORK / video.stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def save(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def srt_time(t: float) -> str:
    ms = max(0, round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_translation(path) -> dict:
    """Read 'id|texto' lines; a literal backslash-n inside text = line break. Tolerates wrapped lines."""
    out, cur = {}, None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue                       # comments / context lines
        head, sep, rest = line.partition("|")
        if sep and head.strip().isdigit():
            cur = int(head)
            out[cur] = rest.strip()
        elif cur is not None and line.strip():
            out[cur] += " " + line.strip()
    return {k: v.replace("\\n", "\n").strip() for k, v in out.items()}
