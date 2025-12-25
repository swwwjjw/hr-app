import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI


HH_VACANCIES_URL = "https://api.hh.ru/vacancies"


def _utc_timestamp() -> str:
    # Example: 20251225T195515Z
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_output_dir() -> Path:
    # Persisted on host because docker-compose mounts ./backend -> /app
    # (container path /app/final_folder == host path backend/final_folder)
    return Path(__file__).resolve().parent / "final_folder"


def _load_hh_params() -> Dict[str, Any]:
    """
    Optional query params passed to HH API.

    Provide as JSON via env var HH_VACANCIES_PARAMS, e.g.:
      {"per_page": 50, "page": 0, "area": 2, "text": "python"}
    """
    raw = os.getenv("HH_VACANCIES_PARAMS", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError("HH_VACANCIES_PARAMS must be valid JSON") from e
    if not isinstance(parsed, dict):
        raise ValueError("HH_VACANCIES_PARAMS must be a JSON object")
    return parsed


def _interval_seconds() -> int:
    # User request says "once a day (12 hours)" -> default to 12h.
    hours_raw = os.getenv("HH_SNAPSHOT_INTERVAL_HOURS", "12").strip()
    try:
        hours = float(hours_raw)
    except ValueError as e:
        raise ValueError("HH_SNAPSHOT_INTERVAL_HOURS must be a number") from e
    if hours <= 0:
        raise ValueError("HH_SNAPSHOT_INTERVAL_HOURS must be > 0")
    return int(hours * 3600)


def _output_dir() -> Path:
    # Allow overriding location (absolute or relative).
    raw = os.getenv("FINAL_FOLDER", "").strip()
    if not raw:
        return _default_output_dir()
    return Path(raw)


async def fetch_hh_vacancies_json(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    headers = {
        # HH API can be sensitive; a UA reduces chances of being blocked.
        "User-Agent": "fastapi-hh-snapshot/1.0",
        "Accept": "application/json",
    }
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(HH_VACANCIES_URL, params=params or {})
        resp.raise_for_status()
        return resp.json()


def save_snapshot_txt(payload: Dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"hh_vacancies_{_utc_timestamp()}.txt"
    final_path = out_dir / filename
    tmp_path = out_dir / f".{filename}.tmp"

    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp_path.replace(final_path)
    return final_path


@dataclass
class HHSchedulerState:
    running: bool = False
    last_run_utc: Optional[str] = None
    last_success_utc: Optional[str] = None
    last_saved_path: Optional[str] = None
    last_error: Optional[str] = None
    interval_seconds: int = field(default_factory=_interval_seconds)
    params: Dict[str, Any] = field(default_factory=_load_hh_params)
    out_dir: Path = field(default_factory=_output_dir)
    _task: Optional[asyncio.Task] = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)

    async def run_once(self) -> Path:
        now = _utc_timestamp()
        self.last_run_utc = now
        self.last_error = None

        payload = await fetch_hh_vacancies_json(self.params)
        saved = save_snapshot_txt(payload, self.out_dir)

        self.last_success_utc = now
        self.last_saved_path = str(saved)
        return saved

    async def _loop(self) -> None:
        self.running = True
        try:
            # Run immediately on startup, then sleep.
            while not self._stop.is_set():
                try:
                    await self.run_once()
                except Exception as e:  # keep scheduler alive
                    self.last_error = f"{type(e).__name__}: {e}"
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
                except asyncio.TimeoutError:
                    continue
        finally:
            self.running = False

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)


def install_hh_snapshot_scheduler(app: FastAPI) -> HHSchedulerState:
    """
    Installs:
      - background scheduler that fetches HH vacancies every N hours
      - GET  /hh-snapshot/status
      - POST /hh-snapshot/run
    """
    state = HHSchedulerState()

    @app.on_event("startup")
    async def _hh_snapshot_startup() -> None:
        state.start()

    @app.on_event("shutdown")
    async def _hh_snapshot_shutdown() -> None:
        await state.stop()

    @app.get("/hh-snapshot/status")
    async def hh_snapshot_status() -> Dict[str, Any]:
        return {
            "running": state.running,
            "interval_seconds": state.interval_seconds,
            "params": state.params,
            "final_folder": str(state.out_dir),
            "last_run_utc": state.last_run_utc,
            "last_success_utc": state.last_success_utc,
            "last_saved_path": state.last_saved_path,
            "last_error": state.last_error,
        }

    @app.post("/hh-snapshot/run")
    async def hh_snapshot_run() -> Dict[str, Any]:
        saved = await state.run_once()
        return {"saved_to": str(saved)}

    return state

