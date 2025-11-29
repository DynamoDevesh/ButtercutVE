# ffmpeg_utils.py
import re
import subprocess
from pathlib import Path

_time_re = re.compile(r'time=(\d+):(\d+):(\d+\.\d+)')  # matches time=HH:MM:SS.msec

def parse_time_from_ffmpeg_line(line: str):
    """
    Parse a ffmpeg stderr line and return elapsed seconds if present.
    """
    if not line:
        return None
    m = _time_re.search(line)
    if not m:
        # fallback for patterns like time=00:00:01.23
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    ss = float(m.group(3))
    return hh * 3600 + mm * 60 + ss


def ffprobe_duration(path):
    """
    Return duration in seconds using ffprobe; returns float or None.
    """
    import shlex
    cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {shlex.quote(str(path))}"
    try:
        p = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        out = p.stdout.strip()
        return float(out)
    except Exception:
        return None
