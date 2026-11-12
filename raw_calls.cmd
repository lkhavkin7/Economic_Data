@echo off
rem Replays four raw MCP requests with curl. Run from the project root while the
rem server is running and Wireshark is capturing.
set URL=http://127.0.0.1:8765/mcp
echo ===== 1. server/discover =====
curl -s -i -X POST %URL% -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: server/discover" -d @requests\discover.json
echo.
pause
echo ===== 2. tools/list =====
curl -s -i -X POST %URL% -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: tools/list" -d @requests\list_tools.json
echo.
pause
echo ===== 3. resources/read (GDP) =====
curl -s -i -X POST %URL% -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: resources/read" -H "Mcp-Name: fred://series/GDP" -d @requests\read_gdp.json
echo.
pause
echo ===== 4. resources/read (missing, expect an error) =====
curl -s -i -X POST %URL% -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: resources/read" -H "Mcp-Name: fred://series/NOPE" -d @requests\read_missing.json
echo.
pause
