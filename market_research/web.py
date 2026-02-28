import asyncio
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from market_research.agent import run_research_agent
from market_research.pdf_renderer import render_pdf

app = FastAPI(title="Market Research Agent")

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "./output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Track active research sessions so they can be cancelled
_active_sessions: dict[str, asyncio.Task] = {}


@app.get("/", response_class=HTMLResponse)
async def index():
    html = (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/api/research/stream")
async def stream_research(topic: str, prompt: str = "", max_turns: int = 50):
    """SSE endpoint: streams progress events, then a final complete/error event."""
    # Clamp max_turns to a safe range
    max_turns = max(10, min(100, max_turns))
    session_id = str(uuid.uuid4())[:8]

    async def event_stream():
        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        started_at = asyncio.get_event_loop().time()

        def on_progress(message: str, msg_type: str) -> None:
            queue.put_nowait((message, msg_type))

        # Send session ID so the frontend can cancel this specific session
        yield _sse("session", {"session_id": session_id})
        yield _sse("status", {"message": f"Researching: {topic}"})
        yield _sse("log", {"message": f"Topic: {topic}", "type": "phase"})
        yield _sse("log", {"message": f"Max turns: {max_turns}", "type": "phase"})
        if prompt:
            yield _sse("log", {"message": f"Instructions: {prompt}", "type": "phase"})

        # Run agent in a task so we can drain the queue concurrently
        agent_task = asyncio.create_task(
            run_research_agent(
                topic=topic,
                additional_instructions=prompt,
                max_turns=max_turns,
                on_progress=on_progress,
            )
        )

        # Register so it can be cancelled via /api/research/cancel
        _active_sessions[session_id] = agent_task

        try:
            # Drain progress events while agent runs, send heartbeats to keep alive
            heartbeat_interval = 10  # seconds between heartbeat pings
            last_heartbeat = started_at
            while not agent_task.done():
                try:
                    message, msg_type = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield _sse("log", {"message": message, "type": msg_type})
                    yield _sse("status", {"message": message})
                    last_heartbeat = asyncio.get_event_loop().time()
                except asyncio.TimeoutError:
                    now = asyncio.get_event_loop().time()
                    if now - last_heartbeat >= heartbeat_interval:
                        elapsed = int(now - started_at)
                        mins, secs = divmod(elapsed, 60)
                        yield _sse("heartbeat", {"elapsed": elapsed, "message": f"Working... ({mins}m {secs}s)"})
                        last_heartbeat = now

            # Drain any remaining events
            while not queue.empty():
                message, msg_type = queue.get_nowait()
                yield _sse("log", {"message": message, "type": msg_type})

            # Check if the task was cancelled
            if agent_task.cancelled():
                yield _sse("cancelled", {"message": "Research stopped by user."})
                return

            # Get result or error
            try:
                markdown_report = agent_task.result()
            except asyncio.CancelledError:
                yield _sse("cancelled", {"message": "Research stopped by user."})
                return
            except Exception as e:
                yield _sse("error_event", {"message": str(e)})
                return

            # Generate PDF
            yield _sse("log", {"message": "Converting to PDF...", "type": "phase"})
            yield _sse("status", {"message": "Generating PDF report..."})

            try:
                pdf_path = render_pdf(
                    markdown_content=markdown_report,
                    topic=topic,
                    output_dir=OUTPUT_DIR,
                )
            except Exception as e:
                # Save markdown as fallback
                md_fallback = OUTPUT_DIR / f"{topic[:40].replace(' ', '_')}.md"
                md_fallback.write_text(markdown_report, encoding="utf-8")
                yield _sse(
                    "error_event",
                    {"message": f"PDF generation failed: {e}. Markdown saved."},
                )
                return

            # Count pages
            try:
                from market_research.pdf_renderer import count_pdf_pages

                pages = count_pdf_pages(pdf_path)
            except Exception:
                pages = "~"

            yield _sse("log", {"message": f"Report saved: {pdf_path.name}", "type": "done"})
            yield _sse(
                "complete",
                {
                    "filename": pdf_path.name,
                    "pages": pages,
                    "path": str(pdf_path),
                },
            )
        finally:
            # Always clean up the session tracking
            _active_sessions.pop(session_id, None)
            # If the task is still running (client disconnected), cancel it
            if not agent_task.done():
                agent_task.cancel()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/research/cancel")
async def cancel_research(request: Request):
    """Cancel an active research session by session_id."""
    body = await request.json()
    session_id = body.get("session_id", "")

    task = _active_sessions.pop(session_id, None)
    if task and not task.done():
        task.cancel()
        return JSONResponse({"status": "cancelled", "session_id": session_id})

    return JSONResponse({"status": "not_found", "session_id": session_id}, status_code=404)


@app.get("/api/reports")
async def list_reports():
    """List all generated PDF reports."""
    reports = []
    for f in sorted(OUTPUT_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = f.stat()
        reports.append(
            {
                "filename": f.name,
                "name": f.stem.replace("-", " ").replace("_", " ").title(),
                "date": datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %Y %I:%M %p"),
                "size": stat.st_size,
            }
        )
    return reports


@app.get("/api/reports/{filename}")
async def download_report(filename: str):
    """Download a specific report PDF."""
    pdf_path = OUTPUT_DIR / filename
    if not pdf_path.exists() or not pdf_path.is_file():
        return {"error": "Report not found"}, 404
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=filename,
    )


def _sse(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def start_server(host: str = "0.0.0.0", port: int = 8000):
    """Start the web server."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)
