"""One-time setup: venv + deps. Usage: python scripts/setup.py [--check]"""
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def check() -> bool:
    if not PY.exists():
        print("MISSING venv")
        return False
    r = subprocess.run([str(PY), "-c",
                        "import faster_whisper, imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                       capture_output=True, text=True)
    print(("OK ffmpeg=" + r.stdout.strip()) if r.returncode == 0 else "MISSING deps\n" + r.stderr[-400:])
    return r.returncode == 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
    if not PY.exists():
        venv.create(VENV, with_pip=True)
    subprocess.check_call([str(PY), "-m", "pip", "install", "-q", "-U", "pip"])
    subprocess.check_call([str(PY), "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")])
    sys.exit(0 if check() else 1)
