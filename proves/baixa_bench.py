"""Descarrega l'àudio (format original) de les cançons de work/bench/dataset.jsonl.

Ús: python proves/baixa_bench.py
Desa work/bench/audio/<id>.<ext>; salta les ja baixades; pausa entre descàrregues.
"""

import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

DIR = Path("work/bench/audio")
DIR.mkdir(parents=True, exist_ok=True)
YTDLP = Path(sys.executable).parent / "yt-dlp.exe"

for linia in Path("work/bench/dataset.jsonl").read_text(encoding="utf-8").splitlines():
    s = json.loads(linia)
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", s["youtube_url"])
    if not m:
        print(f"{s['id']}: URL sense id de vídeo: {s['youtube_url']}", flush=True)
        continue
    if list(DIR.glob(f"{s['id']}.*")):
        continue
    r = subprocess.run(
        [str(YTDLP), "-q", "--no-warnings", "--js-runtimes", "node", "-f", "bestaudio",
         "-o", str(DIR / f"{s['id']}.%(ext)s"), f"https://www.youtube.com/watch?v={m.group(1)}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    print(f"{s['id']}: {'ok' if r.returncode == 0 else 'ERROR ' + r.stderr.strip()[-200:]}", flush=True)
    time.sleep(random.uniform(4, 10))
print("FET_DESCARREGA", flush=True)
