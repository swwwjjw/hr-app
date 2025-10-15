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
    )
    from .analytics import salary_stats, top_skills
except Exception:  # ModuleNotFoundError when running with --app-dir backend
    from hh_parser_ver2 import (
        fetch_vacancies,
        parse_vacancies,
        enrich_with_descriptions,
        normalize_salary,
        fetch_resume_detail_api,
        enrich_resumes_with_details,
        parse_resumes,
    )
    from analytics import salary_stats, top_skills

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
async def fetch(query: str = Query(..., description="Search query, e.g. 'data scientist'"), area: Optional[int] = Query(None), pages: Optional[int] = Query(None), per_page: int = Query(100, ge=1, le=100), simplified: bool = Query(False), employer_mark: bool = Query(False), include_description: bool = Query(False)):
    # Generate cache key
    cache_key = get_cache_key(query, area, pages, per_page, simplified=simplified, employer_mark=employer_mark, include_description=include_description)
    
    # Check cache first
    cached_result = get_from_cache(cache_key)
    if cached_result is not None:
        return cached_result
    
    # Fetch data if not in cache
    items = await fetch_vacancies(query=query, area=area, pages=pages, per_page=per_page)
    if include_description:
        await enrich_with_descriptions(items)
    if simplified:
        parsed = await parse_vacancies(items, with_employer_mark=employer_mark)
        result = {"count": len(parsed), "items": parsed}
    else:
        result = {"count": len(items), "items": items}
    
    # Store in cache
    set_cache(cache_key, result)
    return result


@app.get("/analyze")
async def analyze(query: str = Query(...), area: Optional[int] = Query(None), pages: Optional[int] = Query(None), per_page: int = Query(100, ge=1, le=100)):
    # Generate cache key for analyze endpoint
    cache_key = get_cache_key(query, area, pages, per_page, endpoint="analyze")
    
    # Check cache first
    cached_result = get_from_cache(cache_key)
    if cached_result is not None:
        return cached_result
    
    # Fetch and analyze data if not in cache
    items = await fetch_vacancies(query=query, area=area, pages=pages, per_page=per_page)
    # Use parsed vacancies so per-shift monthly estimates are considered
    parsed_for_stats = await parse_vacancies(items, with_employer_mark=False)
    salaries = salary_stats(parsed_for_stats)
    skills = top_skills(items, top_n=20)
    result = {"query": query, "area": area, "count": len(items), "salaries": salaries, "skills": skills}
    
    # Store in cache
    set_cache(cache_key, result)
    return result


# Removed resume-by-ID stats endpoint. Use vacancy-driven analytics and UI charts instead.


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Simple HTML dashboard that fetches /analyze and renders charts.
    Query params are read from the browser URL: query, area, pages, per_page.
    """
    with open('template.html', 'r', encoding='utf-8') as file:
      html = file.read()
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
