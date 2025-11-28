# main.py
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

from ffmpeg_utils import ffprobe_duration, parse_time_from_ffmpeg_line

app = FastAPI()

# CORS middleware (allow local dev origins; "*" ok for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "http://localhost:19006", "http://localhost:19000", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WORKDIR = Path("jobs")
WORKDIR.mkdir(exist_ok=True)

# in-memory jobs dict (persisted to jobs.json)
jobs: Dict[str, Dict[str, Any]] = {}  # job_id -> metadata dict

# persistence for jobs (so server can remember jobs across restarts)
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
    """
    Accept repeated 'file' entries (base video + overlay images).
    overlays_json should reference overlay filenames (we expect frontend to set overlay.content to the desired filename).
    """
    job_id = str(uuid.uuid4())
    jobdir = WORKDIR / job_id
    jobdir.mkdir(parents=True, exist_ok=True)

    # save uploaded files into jobdir
    saved_files = []
    base_video_path = None
    try:
        for up in files:
            # sanitize filename
            fname = os.path.basename(up.filename)
            target = jobdir / fname
            # write
            with target.open("wb") as wf:
                content = await up.read()
                wf.write(content)
            saved_files.append(str(target))

            # Heuristics to detect which file is base video (content_type or extension)
            ctype = (up.content_type or "").lower()
            if base_video_path is None:
                if ctype.startswith("video") or fname.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".avi")):
                    base_video_path = str(target)

        # Fallback: if we didn't detect video, but at least one file uploaded, take first as video
        if base_video_path is None and saved_files:
            base_video_path = saved_files[0]

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "failed to save uploaded files", "detail": str(e)})

    if base_video_path is None:
        return JSONResponse(status_code=400, content={"error": "no video file uploaded"})

    # Save metadata (overlays_json from client)
    try:
        overlays = json.loads(overlays_json)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": "invalid overlays_json", "detail": str(e)})

    # If overlay content values were server filenames (frontend set them), then they are already saved in jobdir.
    # Persist overlays.json
    (jobdir / "overlays.json").write_text(json.dumps(overlays))

    out_path = jobdir / "rendered.mp4"

    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "video": str(base_video_path),
        "out": str(out_path),
        "msg": ""
    }
    save_jobs()

    # start background worker
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


# ---- renderer (same logic as before) ----
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

    duration = ffprobe_duration(input_video) or 0.0

    # Build ffmpeg invocation
    cmd = ["ffmpeg", "-y", "-i", str(input_video)]
    extra_inputs = []

    for ov in overlays:
        if ov.get("type") in ("image", "video"):
            content = ov.get("content")
            # If content is a filename that exists in jobdir, use it
            candidate = jobdir / content
            if content and candidate.exists():
                cmd += ["-i", str(candidate)]
                extra_inputs.append(ov)

    filter_parts = []
    overlay_label = "[0:v]"
    input_idx = 1

    for ov in overlays:
        ttype = ov.get("type")
        if ttype == "text":
            text_raw = ov.get("content", "") or ""
            text = text_raw.replace("'", r"'\''").replace(":", r"\:")
            draw = (
                f"drawtext=text='{text}':"
                f"x={ov.get('x',50)}:y={ov.get('y',50)}:"
                f"fontsize={ov.get('fontsize',24)}:fontcolor={ov.get('fontcolor','white')}:"
                f"box=1:boxcolor=black@0.5:boxborderw=10:"
                f"enable='between(t,{ov.get('start_time',0)},{ov.get('end_time',5)})'"
            )
            filter_parts.append(draw)

        elif ttype == "image":
            w = ov.get("width", -1)
            h = ov.get("height", -1)
            filter_parts.append(f"[{input_idx}:v]scale={w}:{h}[ov{input_idx}];")
            filter_parts.append(
                f"{overlay_label}[ov{input_idx}]overlay="
                f"{ov.get('x',0)}:{ov.get('y',0)}:"
                f"enable='between(t,{ov.get('start_time',0)},{ov.get('end_time',5)})'"
                f"[tmp{input_idx}];"
            )
            overlay_label = f"[tmp{input_idx}]"
            input_idx += 1

        elif ttype == "video":
            filter_parts.append(
                f"[{input_idx}:v]setpts=PTS-STARTPTS,scale="
                f"{ov.get('width',-1)}:{ov.get('height',-1)}[ov{input_idx}];"
            )
            filter_parts.append(
                f"{overlay_label}[ov{input_idx}]overlay="
                f"{ov.get('x',0)}:{ov.get('y',0)}:"
                f"enable='between(t,{ov.get('start_time',0)},{ov.get('end_time',5)})'"
                f"[tmp{input_idx}];"
            )
            overlay_label = f"[tmp{input_idx}]"
            input_idx += 1

    final_map = overlay_label
    out_path = Path(job["out"])

    if filter_parts:
        if extra_inputs:
            filter_complex = "".join(filter_parts)
            cmd += [
                "-filter_complex", filter_complex,
                "-map", final_map,
                "-map", "0:a?",
                "-c:v", "libx264",
                "-preset", "fast",
                "-c:a", "copy",
                str(out_path),
            ]
        else:
            vf_str = ",".join(filter_parts)
            cmd += [
                "-vf", vf_str,
                "-c:v", "libx264",
                "-preset", "fast",
                "-c:a", "copy",
                str(out_path),
            ]
    else:
        cmd += ["-c", "copy", str(out_path)]

    ff_log = jobdir / "ffmpeg_background.log"
    job["status"] = "processing"
    job["progress"] = 0
    job["msg"] = f"running ffmpeg, output -> {out_path.name}"
    save_jobs()

    try:
        with ff_log.open("w", encoding="utf-8") as logf:
            logf.write("Running ffmpeg command:\n" + " ".join(shlex.quote(p) for p in cmd) + "\n\n")
            logf.flush()
            proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
            stdout, stderr = proc.communicate()
            logf.write("--- STDOUT ---\n")
            logf.write(stdout or "")
            logf.write("\n--- STDERR ---\n")
            logf.write(stderr or "")
            logf.flush()

        if proc.returncode == 0 and out_path.exists():
            job["status"] = "done"
            job["progress"] = 100
            job["msg"] = "render complete"
            save_jobs()
        else:
            job["status"] = "error"
            job["msg"] = f"ffmpeg returned {proc.returncode}; see {ff_log.name}"
            save_jobs()
    except Exception as e:
        job["status"] = "error"
        job["msg"] = f"exception: {e}"
        save_jobs()
        try:
            with ff_log.open("a", encoding="utf-8") as logf:
                logf.write(f"\nEXCEPTION: {e}\n")
        except Exception:
            pass

    return
