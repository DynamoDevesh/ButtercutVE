🎥 Buttercut.ai — Backend (FastAPI + FFmpeg)

This is the backend for the Buttercut.ai Video Editing App, responsible for:

✔️ Receiving base video + overlay files
✔️ Processing overlays using FFmpeg
✔️ Handling text/image/video overlays
✔️ Rendering the final output video
✔️ Reporting real-time rendering progress
✔️ Providing a downloadable rendered file

🚀 1. Installation
Install Python dependencies
cd backend
pip install -r requirements.txt

Install FFmpeg (Required)

Ubuntu/Debian:

sudo apt-get install ffmpeg


macOS (Homebrew):

brew install ffmpeg


Windows:
Download from: https://ffmpeg.org/download.html

Add FFmpeg to system PATH.

▶️ 2. Start Backend Server

Run FastAPI with LAN access enabled (needed for mobile testing):

uvicorn main:app --reload --host 0.0.0.0 --port 8000


Your backend will now be accessible at:

http://<your-lan-ip>:8000


Example:

http://192.168.1.30:8000


You can check your LAN IP via:

ifconfig | grep "inet "

🌐 3. API Endpoints
POST /upload

Uploads:

Base video file

Overlay image/video files

overlays_json (metadata including timing, position, type, etc.)

Multipart Form Fields:
Key	Description
files	Multiple file inputs (video + overlays)
overlays_json	JSON string describing overlays
Response:
{
  "job_id": "xxx-xxx-xxx-xxx"
}


Server begins rendering immediately in background.

GET /status/{job_id}

Returns:

{
  "status": "queued / processing / done / error",
  "progress": 0-100,
  "video": "path/to/base/video",
  "out": "path/to/rendered/video",
  "msg": "rendering..."
}


Use this for polling from frontend.

GET /result/{job_id}

Downloads the final rendered video:

http://<lan-ip>:8000/result/<job_id>


Example:

curl -o output.mp4 http://192.168.1.30:8000/result/<job_id>

🧪 4. Example cURL Test
Upload + Overlays
curl -X POST "http://192.168.1.30:8000/upload" \
  -F "files=@/path/base_video.mp4" \
  -F "files=@/path/overlay.png" \
  -F 'overlays_json=[
      {
        "id":"ov1",
        "type":"image",
        "content":"overlay.png",
        "x":50,
        "y":50,
        "width":120,
        "height":120,
        "start_time":1,
        "end_time":4
      }
    ]'

Check status:
curl http://192.168.1.30:8000/status/<job_id>

Download output:
curl -o rendered.mp4 http://192.168.1.30:8000/result/<job_id>

📁 5. Job Folder Structure

Every render job stores its files here:

backend/jobs/<job_id>/
    ├── base_video.mp4
    ├── overlay_xxx.png / overlay_xxx.mp4
    ├── overlays.json
    ├── ffmpeg_background.log
    └── rendered.mp4


Jobs are also tracked in:

backend/jobs.json


This allows jobs to resume after server restart.

⚙️ 6. Backend Features

✔️ Accepts multiple files in one request
✔️ Supports text, image, and video overlays
✔️ Drag/drop positions passed from frontend
✔️ Start/End timing for each overlay
✔️ Real-time progress extraction from FFmpeg logs
✔️ Background rendering via threads
✔️ Download link for final MP4
✔️ Mobile-friendly and Expo-friendly CORS enabled
✔️ Uses enable=between(t,start,end) for precise timing

📱 7. Testing With Expo Frontend

Ensure backend is running on LAN

http://192.168.x.x:8000


Update BACKEND_URL in frontend:

const BACKEND_URL = "http://192.168.1.30:8000";


Start Expo:

npx expo start


Scan QR code in Expo Go

Upload video → add overlays → submit

Real-time progress modal appears

Press Open result → downloads final video