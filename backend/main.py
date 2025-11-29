# backend/main.py
import uuid
import os
import json
import threading
import subprocess
import shlex
from pathlib import Path
from typing import Dict, Any, List
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# your ffmpeg utils (must implement ffprobe_duration and parse_time_from_ffmpeg_line)
from ffmpeg_utils import ffprobe_duration, parse_time_from_ffmpeg_line

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WORKDIR = Path("jobs")
WORKDIR.mkdir(exist_ok=True)

jobs: Dict[str, Dict[str, Any]] = {}
JOBS_JSON = Path("jobs.json")


def save_jobs():
    try:
        tmp = JOBS_JSON.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2)
        tmp.replace(JOBS_JSON)
    except Exception as e:
        print("save_jobs error", e)


def load_jobs():
    global jobs
    if JOBS_JSON.exists():
        try:
            with JOBS_JSON.open("r", encoding="utf-8") as f:
                jobs = json.load(f)
        except Exception as e:
            print("load_jobs error", e)


def resume_jobs():
    for job_id, meta in list(jobs.items()):
        status = meta.get("status")
        if status not in ("done", "error"):
            jobdir = Path(meta.get("video", "")).parent
            if jobdir.exists():
                print(f"Resuming job {job_id} (status={status})")
                t = threading.Thread(target=render_job, args=(job_id,), daemon=True)
                t.start()
            else:
                print(f"Job directory missing for {job_id}, marking error")
                meta["status"] = "error"
                meta["msg"] = "job folder missing on resume"
                save_jobs()


load_jobs()
resume_jobs()


@app.post("/upload")
async def upload(files: List[UploadFile] = File(...), overlays_json: str = Form(...)):
    job_id = str(uuid.uuid4())
    jobdir = WORKDIR / job_id
    jobdir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    base_video_path = None
    try:
        for up in files:
            fname = os.path.basename(up.filename)
            target = jobdir / fname
            with target.open("wb") as wf:
                content = await up.read()
                wf.write(content)
            saved_files.append(str(target))

            ctype = (up.content_type or "").lower()
            if base_video_path is None:
                if ctype.startswith("video") or fname.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".avi")):
                    base_video_path = str(target)

        if base_video_path is None and saved_files:
            base_video_path = saved_files[0]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "failed to save uploaded files", "detail": str(e)})

    if base_video_path is None:
        return JSONResponse(status_code=400, content={"error": "no video file uploaded"})

    try:
        overlays = json.loads(overlays_json)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": "invalid overlays_json", "detail": str(e)})

    (jobdir / "overlays.json").write_text(json.dumps(overlays))

    out_path = jobdir / "rendered.mp4"

    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "video": str(base_video_path),
        "out": str(out_path),
        "saved_files": saved_files,
        "msg": ""
    }
    save_jobs()

    t = threading.Thread(target=render_job, args=(job_id,), daemon=True)
    t.start()

    return {"job_id": job_id}


@app.get("/status/{job_id}")
def status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return job


@app.get("/result/{job_id}")
def result(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "not found"})
    if job["status"] != "done":
        return JSONResponse(status_code=400, content={"error": "not ready", "status": job["status"]})
    path = Path(job["out"])
    if not path.exists():
        return JSONResponse(status_code=500, content={"error": "output missing"})
    return FileResponse(path, media_type="video/mp4", filename="rendered.mp4")


def render_job(job_id: str):
    if job_id not in jobs:
        print(f"render_job: job {job_id} missing from memory; aborting")
        return

    job = jobs[job_id]
    jobdir = Path(job["video"]).parent
    overlays_path = jobdir / "overlays.json"

    if not overlays_path.exists():
        job["status"] = "error"
        job["msg"] = "overlays.json missing"
        save_jobs()
        return

    try:
        overlays = json.loads(overlays_path.read_text())
    except Exception as e:
        job["status"] = "error"
        job["msg"] = f"invalid overlays.json: {e}"
        save_jobs()
        return

    input_video = Path(job["video"])
    if not input_video.exists():
        job["status"] = "error"
        job["msg"] = "input video missing"
        save_jobs()
        return

    # ------------------------------
    # BUILD FFMPEG COMMAND
    # ------------------------------

    cmd = ["ffmpeg", "-y", "-i", str(input_video)]
    extra_inputs = []
    image_indices = []

    # Collect image/video overlay inputs
    for ov in overlays:
        if ov.get("type") in ("image", "video"):
            filename = ov.get("content")
            candidate = jobdir / filename
            if candidate.exists():
                cmd += ["-i", str(candidate)]
                extra_inputs.append(ov)
                image_indices.append(len(extra_inputs))  # 1-based

    # Build filter_complex
    filter_parts = []
    current_label = "[0:v]"  # start with the base video
    input_offset = 1  # next FFmpeg input index after base video

    # First: text overlays (drawtext) → chain sequentially
    for ov in overlays:
        if ov.get("type") == "text":
            txt = (ov.get("content") or "").replace("'", r"'\''").replace(":", r"\:")
            draw = (
                f"{current_label}"
                f"drawtext=text='{txt}':"
                f"x={ov.get('x', 50)}:y={ov.get('y', 50)}:"
                f"fontsize={ov.get('fontsize', 24)}:fontcolor={ov.get('fontcolor', 'white')}:"
                f"box=1:boxcolor=black@0.5:boxborderw=10:"
                f"enable='between(t,{ov.get('start_time',0)},{ov.get('end_time',5)})'"
                f"[txt{ov['id']}]"
            )
            filter_parts.append(draw)
            current_label = f"[txt{ov['id']}]"

    # Next: image/video overlays → chain sequentially
    for ov in overlays:
        if ov.get("type") in ("image", "video"):
            idx = input_offset
            input_offset += 1

            w = ov.get("width", -1)
            h = ov.get("height", -1)

            # Scale overlay
            filter_parts.append(
                f"[{idx}:v]scale={w}:{h}[ov{idx}]"
            )

            # Overlay onto current chain
            overlay = (
                f"{current_label}[ov{idx}]overlay="
                f"{ov.get('x',0)}:{ov.get('y',0)}:"
                f"enable='between(t,{ov.get('start_time',0)},{ov.get('end_time',5)})'"
                f"[tmp{idx}]"
            )
            filter_parts.append(overlay)
            current_label = f"[tmp{idx}]"

    # Build full command
    out_path = Path(job["out"])
    ff_log = jobdir / "ffmpeg_background.log"

    if filter_parts:
        filter_complex = "; ".join(filter_parts)

        cmd += [
            "-filter_complex", filter_complex,
            "-map", current_label,
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "fast",
            "-c:a", "copy",
            str(out_path),
        ]
    else:
        cmd += ["-c", "copy", str(out_path)]

    # ------------------------------
    # RUN FFMPEG (stream stderr, update progress)
    # ------------------------------
    duration = ffprobe_duration(input_video) or 0.0
    job["status"] = "processing"
    job["progress"] = 0
    job["msg"] = "running ffmpeg"
    save_jobs()

    with ff_log.open("w", encoding="utf-8") as logf:
        logf.write("Running ffmpeg command:\n" + " ".join(shlex.quote(p) for p in cmd) + "\n\n")
        logf.flush()

        try:
            proc = subprocess.Popen(
                cmd,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1,
            )

            # read stderr line-by-line, update progress
            last_lines = []
            if proc.stderr:
                for raw in proc.stderr:
                    line = raw.rstrip("\n")
                    last_lines.append(line)
                    if len(last_lines) > 500:
                        last_lines = last_lines[-500:]
                    logf.write(line + "\n")
                    logf.flush()

                    # parse ffmpeg time=... and update job progress
                    try:
                        t_sec = parse_time_from_ffmpeg_line(line)
                        if t_sec is not None and duration and duration > 0:
                            pct = min(100, int((t_sec / duration) * 100))
                            job["progress"] = pct
                            save_jobs()
                    except Exception:
                        pass

            # ensure process finishes and capture any remaining output
            proc.wait()
            stdout, stderr = proc.communicate()
            logf.write("\n--- STDOUT ---\n")
            logf.write(stdout or "")
            logf.write("\n--- STDERR ---\n")
            logf.write(stderr or "")
            logf.flush()

            if proc.returncode == 0 and out_path.exists():
                job["status"] = "done"
                job["progress"] = 100
                job["msg"] = "render complete"
            else:
                job["status"] = "error"
                job["msg"] = f"ffmpeg returned {proc.returncode}; see ffmpeg_background.log"

            save_jobs()

        except Exception as e:
            job["status"] = "error"
            job["msg"] = f"exception: {e}"
            save_jobs()
            try:
                with ff_log.open("a", encoding="utf-8") as logf2:
                    logf2.write(f"\nEXCEPTION: {e}\n")
            except Exception:
                pass

    return
