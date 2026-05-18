@echo off
cd /d "%~dp0"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8008 > server.out.log 2> server.err.log
