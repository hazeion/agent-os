@echo off
cd /d E:\code\agent-os
python agent_os_lifecycle.py preflight %* || exit /b 1
python server.py %*
