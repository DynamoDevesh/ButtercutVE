# backend (FastAPI + ffmpeg)

1. Install deps:
   pip install -r requirements.txt

   Ensure ffmpeg is installed on system. On Ubuntu:
   sudo apt-get install ffmpeg

2. Run:
   uvicorn main:app --reload --host 0.0.0.0 --port 8000

3. Endpoints:
   POST /upload (multipart/form-data)
     - file: the video file
     - overlays_json: JSON string with overlays array
   GET /status/{job_id}
   GET /result/{job_id}

4. Example cURL:
curl -v -X POST "http://localhost:8000/upload" \
  -F "file=@/path/to/video.mp4;type=video/mp4" \
  -F 'overlays_json=[{"id":"ov1","type":"text","content":"Hello world","x":50,"y":50,"start_time":0,"end_time":4}]'

5. Notes:
 - Image/video overlays referenced by "content" must be server-accessible; otherwise extend backend to pull remote URIs.
 - For containers, build Dockerfile and run with ffmpeg preinstalled (Dockerfile does this).
