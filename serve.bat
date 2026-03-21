@echo off
.venv\Scripts\python -m uvicorn web.app:app --reload --reload-include "*.json" --host 127.0.0.1 --port 8000
