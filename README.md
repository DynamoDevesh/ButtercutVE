# Buttercut.ai — Video Editor (Full-stack assignment)

## Overview
A small video editor built with React Native (Expo) frontend and FastAPI backend. Users can pick a base video, add text/image/video overlays, set position and timing in the frontend preview, and submit the project to the backend for final rendering using `ffmpeg`.

## Repo layout
- `/frontend-app` — Expo React Native app (open in Expo Go)
- `/backend` — FastAPI + ffmpeg backend

## Requirements
- Node 18+, npm
- Python 3.11+
- ffmpeg (backend) — installed automatically by Dockerfile or via package manager
- Expo Go (for mobile testing)

## Run locally (recommended)
### Backend
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
