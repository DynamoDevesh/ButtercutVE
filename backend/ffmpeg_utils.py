import subprocess
import shlex
import re
from pathlib import Path

def ffprobe_duration(path):
    """Return float duration in seconds using ffprobe"""
    cmd = f"ffprobe -v error -select_streams v:0 -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {shlex.quote(str(path))}"
    p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    out = p.stdout.strip()
    try:
        return float(out)
    except:
        return None

_time_re = re.compile(r"time=(\d+):(\d+):(\d+(\.\d+)?)")
def parse_time_from_ffmpeg_line(line):
    m = _time_re.search(line)
    if not m:
        return None
    h = int(m.group(1)); mm = int(m.group(2)); ss = float(m.group(3))
    return h*3600 + mm*60 + ss
