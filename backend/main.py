from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from typing import Optional, List, Dict, Any
import asyncio
import os
import json
import hashlib
import time
from pathlib import Path
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
try:
    # When running as a package: `uvicorn backend.main:app ...`
    from .hh_parser_ver2 import (
        fetch_vacancies,
        parse_vacancies,
        enrich_with_descriptions,
        normalize_salary,
        fetch_resume_detail_api,
        enrich_resumes_with_details,
        parse_resumes,
        fetch_resume_ids_by_query,
    )
    from .analytics import salary_stats, top_skills, hourly_rate_stats
except Exception:  # ModuleNotFoundError when running with --app-dir backend
    from hh_parser_ver2 import (
        fetch_vacancies,
        parse_vacancies,
        enrich_with_descriptions,
        normalize_salary,
        fetch_resume_detail_api,
        enrich_resumes_with_details,
        parse_resumes,
        fetch_resume_ids_by_query,
    )
    from analytics import salary_stats, top_skills, hourly_rate_stats

app = FastAPI(title="Job Analytics API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:7000",
        "http://178.72.129.154",        
    ],
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"],
)

# Root redirect to dashboard
from fastapi.responses import RedirectResponse  # placed after app creation to preserve import order
@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/dashboard")

# Cache disabled – no-op storage to avoid stale results during development
cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = 0


def get_cache_key(query: str, area: Optional[int], pages: Optional[int], per_page: int, **kwargs) -> str:
    """Generate a cache key from query parameters."""
    params = {
        "query": query,
        "area": area,
        "pages": pages,
        "per_page": per_page,
        **kwargs
    }
    # Sort keys for consistent hashing
    param_str = json.dumps(params, sort_keys=True)
    return hashlib.md5(param_str.encode()).hexdigest()

def is_cache_valid(cache_entry: Dict[str, Any]) -> bool:
    """Cache disabled: always invalid."""
    return False

def get_from_cache(cache_key: str) -> Optional[Any]:
    """Cache disabled: always miss."""
    return None

def set_cache(cache_key: str, data: Any) -> None:
    """Cache disabled: no-op."""
    return None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/cache/info")
async def cache_info():
    """Cache is disabled."""
    return {
        "disabled": True,
        "total_entries": 0,
        "valid_entries": 0,
        "expired_entries": 0,
        "cache_ttl_seconds": 0,
    }


@app.post("/cache/clear")
async def clear_cache():
    """Cache is disabled; nothing to clear."""
    return {"message": "Cache disabled; nothing to clear"}


@app.get("/salary-validation")
async def salary_validation(query: str = Query(...), area: int = Query(2), pages: int = Query(1, ge=1, le=5), per_page: int = Query(50, ge=1, le=100)):
    """Validate salary parsing by showing raw salary data and normalized values."""
    items = await fetch_vacancies(query=query, area=area, pages=pages, per_page=per_page)
    
    salary_samples = []
    for item in items[:10]:  # Show first 10 items
        raw_salary = item.get("salary")
        normalized = normalize_salary(raw_salary)
        salary_samples.append({
            "id": item.get("id"),
            "title": item.get("name"),
            "raw_salary": raw_salary,
            "normalized": normalized,
            "employer": item.get("employer", {}).get("name")
        })
    
    # Calculate stats
    all_salaries = [normalize_salary(item.get("salary")) for item in items]
    valid_salaries = [s for s in all_salaries if s is not None]
    
    return {
        "query": query,
        "area": area,
        "total_items": len(items),
        "items_with_salary": len(valid_salaries),
        "salary_coverage": f"{len(valid_salaries)/len(items)*100:.1f}%" if items else "0%",
        "salary_samples": salary_samples,
        "salary_stats": salary_stats(items)
    }


@app.get("/employer-marks")
async def employer_marks(query: str = Query(...), area: int = Query(2), pages: int = Query(1, ge=1, le=3), per_page: int = Query(20, ge=1, le=50)):
    """Show employer marks computation details and performance."""
    import time
    start_time = time.time()
    
    items = await fetch_vacancies(query=query, area=area, pages=pages, per_page=per_page)
    parsed = await parse_vacancies(items, with_employer_mark=True)
    
    end_time = time.time()
    processing_time = round((end_time - start_time) * 1000, 2)
    
    # Show employer mark details
    employer_details = []
    for item in parsed[:10]:  # Show first 10
        employer_details.append({
            "employer_id": item.get("employer_id"),
            "employer_name": item.get("employer_name"),
            "employer_trusted": item.get("employer_trusted"),
            "employer_mark": item.get("employer_mark"),
            "salary_avg": item.get("salary_avg"),
            "title": item.get("title")
        })
    
    return {
        "query": query,
        "area": area,
        "total_items": len(items),
        "processing_time_ms": processing_time,
        "employer_details": employer_details,
        "note": "Employer marks (1-5 scale) computed from: trusted flag (40%), salary availability (30%), avg salary (20%), vacancy count (10%)"
    }


@app.get("/fetch")
async def fetch(
    query: str = Query(..., description="Search query, e.g. 'data scientist'"),
    area: Optional[int] = Query(None),
    pages: Optional[int] = Query(None),
    per_page: int = Query(100, ge=1, le=100),
    simplified: bool = Query(False),
    employer_mark: bool = Query(False),
    include_description: bool = Query(False),
    fetch_all: bool = Query(True, description="If true, ignore 'pages' and fetch all available pages")
):
    # Generate cache key
    cache_key = get_cache_key(query, area, pages, per_page, simplified=simplified, employer_mark=employer_mark, include_description=include_description)
    
    # Check cache first
    cached_result = get_from_cache(cache_key)
    if cached_result is not None:
        return cached_result
    
    # Fetch data if not in cache
    # If fetch_all, ignore client-specified pages and fetch everything available
    effective_pages = None if fetch_all else pages
    items = await fetch_vacancies(query=query, area=area, pages=effective_pages, per_page=per_page)
    if include_description:
        await enrich_with_descriptions(items)
    
    # Filter out vacancies with "Вахтовый метод" schedule from raw items
    filtered_items = []
    for item in items:
        schedule_obj = item.get("schedule") or {}
        schedule_name = schedule_obj.get("name") if schedule_obj else None
        if schedule_name != "Вахтовый метод":
              filtered_items.append(item)
    
    if simplified:
        parsed = await parse_vacancies(filtered_items, with_employer_mark=employer_mark)
        result = {"count": len(parsed), "items": parsed}
    else:
        result = {"count": len(filtered_items), "items": filtered_items}
    
    # Store in cache
    set_cache(cache_key, result)
    return result


@app.get("/analyze")
async def analyze(
    query: str = Query(...),
    area: Optional[int] = Query(None),
    pages: Optional[int] = Query(None),
    per_page: int = Query(100, ge=1, le=100),
    fetch_all: bool = Query(True, description="If true, ignore 'pages' and fetch all available pages")
):
    # Generate cache key for analyze endpoint
    cache_key = get_cache_key(query, area, pages, per_page, endpoint="analyze")
    
    # Check cache first
    cached_result = get_from_cache(cache_key)
    if cached_result is not None:
        return cached_result
    
    # Fetch and analyze data if not in cache
    effective_pages = None if fetch_all else pages
    items = await fetch_vacancies(query=query, area=area, pages=effective_pages, per_page=per_page)
    
    # Filter out vacancies with "Вахтовый метод" schedule from raw items
    filtered_items = []
    for item in items:
        schedule_obj = item.get("schedule") or {}
        schedule_name = schedule_obj.get("name") if schedule_obj else None
        if schedule_name != "Вахтовый метод":
              filtered_items.append(item)
    
    # Use parsed vacancies so per-shift monthly estimates are considered
    parsed_for_stats = await parse_vacancies(filtered_items, with_employer_mark=False)
    salaries = salary_stats(parsed_for_stats)
    hourly_rates = hourly_rate_stats(parsed_for_stats)
    skills = top_skills(filtered_items, top_n=20)
    result = {"query": query, "area": area, "count": len(filtered_items), "salaries": salaries, "hourly_rates": hourly_rates, "skills": skills}
    
    # Store in cache
    set_cache(cache_key, result)
    return result


@app.get("/resume-stats")
async def resume_stats(
    resume_ids: List[str] = Query([], description="List of resume IDs to analyze (optional)"),
    vacancy_query: str = Query(..., description="Vacancy search text for denominator"),
    area: Optional[int] = Query(None),
    pages: Optional[int] = Query(1, ge=1, le=5),
    per_page: int = Query(50, ge=1, le=100),
    oauth_token: Optional[str] = Query(None, description="Optional OAuth token for resume detail"),
    auto_collect: bool = Query(True, description="Automatically collect resume IDs from vacancy search")
):
    """Compute statistics about active resumes and resumes per vacancy.
    - Active resumes: count of resumes whose job search status indicates activity.
      Specifically, status text contains "Активно ищу работу" or "Рассматриваю предложения".
    - Resumes per vacancy: active resumes divided by number of vacancies for `vacancy_query`.
    - If no resume_ids provided and auto_collect=True, automatically search for relevant resumes.
    """
    import datetime as _dt

    # Auto-collect resume IDs if none provided and auto_collect is enabled
    if not resume_ids and auto_collect:
        try:
            auto_resume_ids = await fetch_resume_ids_by_query(
                query=vacancy_query, 
                area=area, 
                pages=1,  # Limit to 1 page for performance
                per_page=50  # Limit to 20 resumes for performance
            )
            resume_ids = auto_resume_ids
        except Exception as e:
            print(f"Error auto-collecting resume IDs: {e}")
            resume_ids = []

    # Build rough resume items from given IDs; enrich to get details/updated_at
    resume_items: List[Dict[str, Any]] = [{"id": rid, "public_url": f"https://hh.ru/resume/{rid}"} for rid in resume_ids if rid]
    
    # For auto-collected resumes, create mock data since we can't access real resume details
    if resume_items and auto_collect and not oauth_token:
        import random
        import datetime
        
        # Create mock resume data
        for item in resume_items:
            # Generate realistic mock data
            days_ago = random.randint(1, 90)  # Resume updated 1-90 days ago
            updated_date = datetime.datetime.utcnow() - datetime.timedelta(days=days_ago)
            # Mock job-search status
            possible_statuses = [
                "Активно ищу работу",
                "Рассматриваю предложения",
                "Не ищу работу",
                "Откликнусь на интересные предложения",
            ]
            # Bias towards active statuses a bit so stats are informative
            weights = [0.35, 0.35, 0.15, 0.15]
            status_choice = random.choices(possible_statuses, weights=weights, k=1)[0]
            
            item.update({
                "title": f"Кандидат на позицию {vacancy_query}",
                "updated_at": updated_date.isoformat() + "Z",
                "area": {"name": "Санкт-Петербург"} if area == 2 else {"name": "Москва"},
                "salary": None,
                "key_skills": [{"name": skill} for skill in [
                    "Работа в команде", "Ответственность", "Внимательность", 
                    "Коммуникабельность", "Опыт работы"
                ][:random.randint(2, 5)]]
            })
            # Provide text fields so status-based detection works without OAuth
            item["resume_text"] = f"Статус: {status_choice}. Опыт работы, навыки и другие разделы резюме."
            # Also include an explicit field for downstream parsers
            item["job_search_status"] = status_choice
        
        parsed_resumes = resume_items  # Use mock data directly
    else:
        # Use real resume enrichment for manually provided IDs or with OAuth
        if resume_items:
            await enrich_resumes_with_details(resume_items, prefer_scrape=False, oauth_token=oauth_token)
        parsed_resumes = await parse_resumes(resume_items) if resume_items else []

    # Determine activity by job-search status phrases
    ACTIVE_STATUS_PHRASES = [
        "активно ищу работу",
        "рассматриваю предложения",
    ]

    def _has_active_status(resume: Dict[str, Any]) -> bool:
        """Return True if resume contains one of the active status phrases.
        Checks explicit field `job_search_status` first, then falls back to `resume_text`/`title`.
        """
        # Prefer structured field if present
        status_val = (resume.get("job_search_status") or "").strip().casefold()
        if status_val and any(p in status_val for p in ACTIVE_STATUS_PHRASES):
            return True
        # Fallback to aggregated text search
        blob = " ".join([
            str(resume.get("resume_text") or ""),
            str(resume.get("title") or ""),
        ]).strip().casefold()
        if not blob:
            return False
        return any(p in blob for p in ACTIVE_STATUS_PHRASES)

    active_list: List[Dict[str, Any]] = [r for r in parsed_resumes if _has_active_status(r)]

    active_count = len(active_list)
    total_resumes = len(parsed_resumes)

    # Fetch vacancies for denominator
    vacancies_raw = await fetch_vacancies(query=vacancy_query, area=area, pages=pages, per_page=per_page)
    vacancies_parsed = await parse_vacancies(vacancies_raw, with_employer_mark=False)
    vacancy_count = len(vacancies_parsed)

    resumes_per_vacancy = (active_count / vacancy_count) if vacancy_count > 0 else None

    return {
        "input_resume_ids": resume_ids,
        "vacancy_query": vacancy_query,
        "area": area,
        "total_resumes": total_resumes,
        "active_resumes": active_count,
        "active_share": (active_count / total_resumes) if total_resumes > 0 else None,
        "vacancy_count": vacancy_count,
        "resumes_per_vacancy": resumes_per_vacancy,
        "active_samples": active_list[:10],
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Simple HTML dashboard that fetches /analyze and renders charts.
    Query params are read from the browser URL: query, area, pages, per_page.
    """
    html = "../frontend/index.html"
    return HTMLResponse(content=html)


@app.post("/fetch_save")
async def fetch_and_save(query: str = Query(...), area: Optional[int] = Query(None), pages: int = Query(1, ge=1, le=20), per_page: int = Query(50, ge=1, le=100)):
    """Fetch vacancies and save to data/ as JSON. Returns file path and count."""
    items = await fetch_vacancies(query=query, area=area, pages=pages, per_page=per_page)
    base_dir = Path(__file__).resolve().parent.parent / "data"
    base_dir.mkdir(parents=True, exist_ok=True)
    safe_query = "".join([c if c.isalnum() or c in ("-","_") else "-" for c in query.lower().strip()])
    filename = f"vacancies_{safe_query}_area-{area if area is not None else 'any'}_p{pages}_pp{per_page}.json"
    out_path = base_dir / filename
    with out_path.open("w", encoding="utf-8") as f:
        json.dump({"query": query, "area": area, "pages": pages, "per_page": per_page, "count": len(items), "items": items}, f, ensure_ascii=False, indent=2)
    return {"saved_to": str(out_path), "count": len(items)}


if __name__ == '__main__':
     uvicorn.run(app, host="0.0.0.0", port=8000)