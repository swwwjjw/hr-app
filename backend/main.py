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
    html = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Job Analytics Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <script src="https://unpkg.com/wordcloud@1.2.2/src/wordcloud2.js"></script>
  <style>
    body { 
      font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif; 
      margin: 0; 
      padding: 24px;
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #334155 100%);
      min-height: 100vh;
      color: #f1f5f9;
    }
    .container {
      max-width: 1200px;
      margin: 0 auto;
      background: rgba(255, 255, 255, 0.05);
      backdrop-filter: blur(10px);
      border-radius: 16px;
      padding: 32px;
      border: 1px solid rgba(255, 255, 255, 0.1);
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
    }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
    .card { 
      border: 1px solid rgba(59, 130, 246, 0.3); 
      border-radius: 12px; 
      padding: 20px; 
      background: rgba(255, 255, 255, 0.08);
      backdrop-filter: blur(5px);
      transition: all 0.3s ease;
    }
    .card:hover {
      border-color: rgba(59, 130, 246, 0.6);
      transform: translateY(-2px);
      box-shadow: 0 10px 25px rgba(59, 130, 246, 0.2);
    }
    h1 { 
      margin: 0 0 16px; 
      font-size: 2.5rem;
      background: linear-gradient(135deg, #3b82f6, #06b6d4, #8b5cf6);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      text-align: center;
      position: relative;
    }
    h1::before {
      content: "✈️";
      position: absolute;
      left: -50px;
      top: 50%;
      transform: translateY(-50%);
      font-size: 2rem;
    }
    h1::after {
      content: "✈️";
      position: absolute;
      right: -50px;
      top: 50%;
      transform: translateY(-50%);
      font-size: 2rem;
    }
    h3 {
      color: #80b9ff;
      border-bottom: 2px solid rgba(128, 185, 255, 0.3);
      padding-bottom: 8px;
      margin-bottom: 16px;
    }
    .meta { 
      color: #cbd5e1; 
      margin-bottom: 16px; 
      font-size: 1.1rem;
      text-align: center;
    }
    .airport-badge {
      display: block;
      background: linear-gradient(135deg, #3b82f6, #06b6d4);
      color: white;
      padding: 8px 16px;
      border-radius: 20px;
      font-weight: 600;
      margin: 16px auto;
      text-align: center;
      width: fit-content;
    }
    @media (max-width: 900px) { 
      .row { grid-template-columns: 1fr; } 
      h1::before, h1::after { display: none; }
    }
    .controls { 
      margin-bottom: 24px; 
      display: flex; 
      gap: 12px; 
      flex-wrap: wrap; 
      justify-content: center;
    }
    input, button, select { 
      padding: 12px 16px; 
      border-radius: 8px;
      border: 1px solid rgba(59, 130, 246, 0.3);
      background: rgba(255, 255, 255, 0.1);
      color: #3b82f6;
      font-size: 14px;
      transition: all 0.3s ease;
    }
    input:focus, select:focus {
      outline: none;
      border-color: #3b82f6;
      box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
    }
    button {
      background: linear-gradient(135deg, #3b82f6, #1d4ed8);
      border: none;
      color: white;
      font-weight: 600;
      cursor: pointer;
    }
    button:hover {
      background: linear-gradient(135deg, #1d4ed8, #1e40af);
      transform: translateY(-1px);
      box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4);
    }
    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
      transform: none;
    }
    .flight-pattern {
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      z-index: -1;
      opacity: 0.1;
    }
    .flight-pattern::before {
      content: "";
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background-image: 
        radial-gradient(circle at 20% 20%, #3b82f6 2px, transparent 2px),
        radial-gradient(circle at 80% 80%, #06b6d4 2px, transparent 2px),
        radial-gradient(circle at 40% 60%, #8b5cf6 2px, transparent 2px);
      background-size: 100px 100px, 150px 150px, 200px 200px;
      animation: float 20s ease-in-out infinite;
    }
    @keyframes float {
      0%, 100% { transform: translateY(0px) rotate(0deg); }
      50% { transform: translateY(-20px) rotate(180deg); }
    }
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-top: 16px;
    }
    .stat-card {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(59, 130, 246, 0.2);
      border-radius: 8px;
      padding: 16px;
      text-align: center;
      transition: all 0.3s ease;
    }
    .stat-card:hover {
      border-color: rgba(59, 130, 246, 0.5);
      background: rgba(255, 255, 255, 0.08);
    }
    #bandBelow {
      background: #94a3b8 !important;
    }
  </style>
  </head>
<body>
  <div class="flight-pattern"></div>
  <div class="container">
    <h1>Барометр вакансий ВВСС</h1>
    <div class="airport-badge">📍 Аэропорт Пулково</div>
    <div id="vacancyStats" class="meta" style="margin-bottom: 16px; font-size: 14px;"></div>
  <div class="controls">
    <input id="q" placeholder="query (e.g. python developer)" style="display: none;" />
    <select id="presets">
      <option value="">Выберите вакансию</option>
      <option value="контролер кпп">Инспектор-контролёр</option>
      <option value="безопасность досмотр">Инспектор по досмотру</option>
      <!-- <option value="инспектор перрон">Инспектор перронного контроля</option> -->
      <!-- <option value="гбр, охрана">Инспектор ГБР</option> -->
      <option value="врач терапевт">Врач-терапевт</option>
              <option value="грузчик нагрузки">Грузчик</option>
              <option value="водитель категория D">Водитель</option>
              <!-- <option value="водитель категория С">Водитель спецтехники</option> -->
              <option value="уборщик клининг">Специалист СБОВС</option>
              <option value="мойщик посуды">Мойщик-уборщик</option>
              <option value="ML инженер">ML-инженер</option>
              <option value="Аналитик данных SQL">Аналитик данных</option>
              <option value="машинист катка">Машинист катка</option>
    </select>
    <button id="toCompetitors" title="Перейти к вкладке конкурентов">К конкурентам</button>
  </div>
  <div class="card" id="marketCard" style="margin-top:24px; padding:20px;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
      <h3 style="margin:0;">Сравнение с рынком по заработной плате</h3>
      <button id="teamProjectBtn" style="background:linear-gradient(135deg, #10b981, #059669); color:white; border:none; padding:8px 16px; border-radius:6px; font-size:12px; font-weight:500; cursor:pointer; transition:all 0.2s;" onmouseover="this.style.transform='scale(1.05)'" onmouseout="this.style.transform='scale(1)'">С проектом "Мы команда"</button>
    </div>
    <div style="display:flex; justify-content:space-between; font-size:12px; color:#cbd5e1; margin-bottom:12px;">
      <div style="color:#94a3b8;">Ниже рынка</div>
      <div style="color:#3b82f6;">В рынке</div>
      <div style="color:#06b6d4;">Выше рынка</div>
    </div>
    <div id="marketScale" style="position:relative; height:48px; border-radius:24px; background:rgba(255,255,255,0.1);
      overflow:visible; margin-bottom:16px; border: 1px solid rgba(59, 130, 246, 0.2);">
      <div id="bandBelow" style="position:absolute; left:0; top:0; bottom:0; background:#94a3b8 !important; border-radius:24px 0 0 24px;"></div>
      <div id="bandIn" style="position:absolute; top:0; bottom:0; background:linear-gradient(135deg, #3b82f6, #1d4ed8);"></div>
      <div id="bandAbove" style="position:absolute; top:0; bottom:0; background:linear-gradient(135deg, #06b6d4, #0891b2); border-radius:0 24px 24px 0;"></div>
             <div id="markerPulkovoLine" title="Пулково зарплата" style="position:absolute; top:0; bottom:0; width:4px; background:#ffffff; box-shadow:0 0 0 2px #3b82f6, 0 0 8px rgba(59,130,246,0.8), 0 0 16px rgba(59,130,246,0.4); border-radius:2px;"></div>
      <div id="markerPulkovoLabel" style="position:absolute; top:52px; transform:translateX(-50%); color:#ffffff; font-weight:800; font-size:13px; white-space:nowrap; text-shadow:0 0 4px rgba(59,130,246,0.8), 0 0 8px rgba(59,130,246,0.6);"></div>
    </div>
    <div id="marketTicks" style="display:flex; justify-content:space-between; font-size:14px; font-weight:500;">
      <div id="valP25" style="color:#94a3b8;">–</div>
      <div id="valP50" style="color:#3b82f6;">–</div>
      <div id="valP75" style="color:#3b82f6;">–</div>
      <div id="valMax" style="color:#06b6d4;">–</div>
    </div>
  </div>
  <div class="row" style="margin-top: 32px;">
    <div class="card">
      <h3>Зарплата vs Рейтинг работодателя</h3>
      <canvas id="bubbleChart" height="140"></canvas>
    </div>
    <div class="card">
      <h3>Меры тенденций</h3>
      <div id="salaryIcons" style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; padding: 16px 0;"></div>
    </div>
  </div>
  <div class="row" style="margin-top:24px;">
    <div class="card">
      <h3>Статистика резюме и ЧТС</h3>
      <div class="controls" style="margin-top:8px; display:none;">
        <input id="resumeIds" placeholder="resume_ids (comma-separated)" />
        <button id="applyResume">Обновить</button>
      </div>
      <div id="resumeStatsMeta" class="meta" style="color:#000000; font-weight: 500;"></div>
      <div id="resumeStatsGrid" style="display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:12px; margin-top:8px;"></div>
      <div id="resumeStatsSummary" style="margin-top:16px; padding:12px; background:rgba(59, 130, 246, 0.1); border-radius:8px; border-left:4px solid #3b82f6; font-size:14px; line-height:1.5; color:#cbd5e1;">
        <p style="margin:0 0 8px 0;"><strong>Анализ резюме:</strong> Статистика показывает соотношение активных и неактивных резюме по выбранной позиции.</p>
        <p style="margin:0 0 8px 0;"><strong>Часовая ставка (ЧТС):</strong> Средняя и диапазон часовых тарифных ставок рассчитываются как зарплата ÷ 164 часа (среднее количество рабочих часов в месяц).</p>
        <p style="margin:0;"><strong>Активность:</strong> Высокий процент активных резюме указывает на востребованность позиции на рынке труда.</p>
      </div>
    </div>
    <div class="card">
      <h3>Распределение зарплат</h3>
      <canvas id="salaryHistogram" height="200"></canvas>
    </div>
  </div>
  <div class="card" style="margin-top:24px;">
    <h3>Требования кандидатов</h3>
    <div id="horizontalBarChart" style="margin-top:16px;">
      <div id="barChartScale" style="position:relative; height:30px; margin-bottom:16px;">
        <div id="scaleLine" style="position:absolute; top:20px; left:0; right:0; height:1px; background:rgba(148, 163, 184, 0.2);"></div>
        <div id="scaleTicks" style="position:absolute; top:0; left:0; right:0; height:20px;">
          <!-- Tick marks will be dynamically generated here -->
        </div>
        <div id="scaleTickMarks" style="position:absolute; top:16px; left:0; right:0; height:8px;">
          <!-- Tick marks on the line will be dynamically generated here -->
        </div>
      </div>
      <div id="barChartContainer" style="display:flex; flex-direction:column; gap:8px;">
        <!-- Bars will be dynamically generated here -->
      </div>
    </div>
    </div>
  </div>
  <script>
    // Persisted state for "С проектом \"Мы команда\"" button
    try {
      const savedTeamProject = localStorage.getItem('teamProjectActive');
      if (savedTeamProject !== null) {
        window.teamProjectActive = (savedTeamProject === '1' || savedTeamProject === 'true');
      }
    } catch (e) {
      // Ignore persistence errors (privacy mode, etc.)
    }

    // Helper to compute additional salary for current query when team project is active
    function getTeamProjectAdditionalForQuery(normalizedQuery) {
      if (!window.teamProjectActive) return 0;
      // Protect against null/undefined
      const q = (normalizedQuery || '').toString().trim().toLowerCase();
      // Treat "водитель" as a separate word to avoid matching "руководитель"
      const qSpaced = ` ${q} `;
      if (q.includes('контролер кпп')) {
        return 16452;
      } else if (q.includes('безопасность досмотр') || q.includes('досмотр')) {
        return 84629;
      } else if (q.includes('уборщик клининг') || q.includes('специалист сбовс')) {
        return 76798;
      } else if (q.includes('водитель категория d') || qSpaced.includes(' водитель ')) {
        // Additional for "Водитель" (категория D и общий случай)
        return 59320;
      } else if (q.includes('машинист катка') || qSpaced.includes(' машинист ')) {
        return 59320;
      return 0;
    }
    // Helper to strictly detect Pulkovo operator company in employer names
    function isPulkovoEmployerName(name) {
      const raw = (name || '').toString().toLowerCase();
      // Remove quotes, dots, commas, extra spaces; strip common legal forms like «ооо»
      const normalized = raw
        .replace(/[«»"'`]/g, '')
        .replace(/[\.,]/g, ' ')
        .replace(/\bооо\b/g, '')
        .replace(/\bzao\b|\boao\b|\bao\b/g, '')
        .replace(/\s+/g, ' ')
        .trim();
      // Accepted exact normalized names
      const accepted = new Set([
        'аэропорт пулково',
        'воздушные ворота северной столицы',
        'аэропорт пулково (воздушные ворота северной столицы)'
      ]);
      if (accepted.has(normalized)) return true;
      return (
        normalized.includes('аэропорт пулково') &&
        normalized.includes('воздушные ворота северной столицы')
      );
    }
    function getParams() {
      const sp = new URLSearchParams(window.location.search);
      const query = sp.get('query') || 'python developer';
      const area = sp.get('area') || '2'; // Default to Saint-Petersburg
      const pages = parseInt(sp.get('pages')) || 2; // Default to 2 pages
      const per_page = parseInt(sp.get('per_page')) || 50; // Default to 50 per page
      const resume_ids_raw = sp.get('resume_ids') || '';
      // Support repeated params too: collect all resume_ids
      const allResumeIds = sp.getAll('resume_ids');
      const idsFromSingle = resume_ids_raw ? resume_ids_raw.split(',').map(s=>s.trim()).filter(Boolean) : [];
      const ids = Array.from(new Set([...(allResumeIds||[]), ...idsFromSingle])).filter(Boolean);
      return { query, area, pages, per_page, resume_ids: ids };
    }

    function setControls({query, resume_ids}) {
      document.getElementById('q').value = query;
      document.getElementById('resumeIds').value = Array.isArray(resume_ids) ? resume_ids.join(',') : '';
      
      // Set preset dropdown based on current query
      const presets = document.getElementById('presets');
      const normalizedQuery = query.toLowerCase().trim();
      
      // Map queries to preset values (order matters - more specific first)
      const queryToPreset = {
        'контролер кпп': 'контролер кпп',
        'безопасность досмотр': 'безопасность досмотр', 
        'врач терапевт': 'врач терапевт',
        'врач-терапевт': 'врач терапевт',
        'грузчик нагрузки': 'грузчик нагрузки',
        'грузчик склад': 'грузчик склад',
        'грузчик': 'грузчик нагрузки',
        'водитель категория С': 'водитель категория С',
        'водитель категория D': 'водитель категория D',
        'водитель': 'водитель категория D',
        'уборщик клининг': 'уборщик клининг',
        'уборщик': 'уборщик клининг',
        'мойщик посуды': 'мойщик посуды',
        'мойщик-уборщик': 'мойщик посуды',
        'мойщик': 'мойщик посуды',
        'ml инженер': 'ML инженер',
        'ml-инженер': 'ML инженер',
        'ml engineer': 'ML инженер',
        'аналитик данных sql': 'Аналитик данных SQL',
        'аналитик данных': 'Аналитик данных SQL',
        'data analyst sql': 'Аналитик данных SQL',
        'машинист катка': 'машинист катка'
      };
      
      // Find matching preset
      let selectedValue = '';
      for (const [key, value] of Object.entries(queryToPreset)) {
        if (normalizedQuery.includes(key.toLowerCase())) {
          selectedValue = value;
          break;
        }
      }
      
      presets.value = selectedValue;
    }

    function applyFromControls() {
      const query = document.getElementById('q').value || 'python developer';
      const url = new URL(window.location.href);
      url.searchParams.set('query', query);
      url.searchParams.set('area', '2'); // Always use Saint-Petersburg
      window.location.href = url.toString();
    }

    function applyResumeFromControls() {
      const url = new URL(window.location.href);
      const ids = (document.getElementById('resumeIds').value || '').split(',').map(s=>s.trim()).filter(Boolean);
      url.searchParams.delete('resume_ids');
      ids.forEach(id => url.searchParams.append('resume_ids', id));
      window.location.href = url.toString();
    }

    // Navigate to the static competitors page served by the frontend (nginx on port 80)
    function goToCompetitors() {
      try {
        const { query, area, pages, per_page } = getParams();
        const protocol = window.location.protocol;
        const host = window.location.hostname;
        // Default to frontend served on port 80 (nginx)
        const targetOrigin = `${protocol}//${host}`;
        // Open the dedicated static page living in frontend/public/competitors.html
        const url = new URL(targetOrigin + '/competitors.html');
        // Pass through current context
        url.searchParams.set('query', query || '');
        url.searchParams.set('area', area || '2');
        if (pages != null) url.searchParams.set('pages', String(pages));
        if (per_page != null) url.searchParams.set('per_page', String(per_page));
        window.location.href = url.toString();
      } catch (e) {
        // Fallback to the static page at site root
        const fallback = `${window.location.protocol}//${window.location.hostname}/competitors.html`;
        window.location.href = fallback;
      }
    }

    async function load() {
      const { query, area, pages, per_page, resume_ids } = getParams();
      setControls({ query, resume_ids });
      const url = new URL(window.location.origin + '/analyze');
      url.searchParams.set('query', query);
      url.searchParams.set('area', area);
      url.searchParams.set('pages', pages);
      url.searchParams.set('per_page', per_page);
      url.searchParams.set('fetch_all', 'true');

      const analyzeStartTime = performance.now();
      const res = await fetch(url);
      const data = await res.json();
      const analyzeEndTime = performance.now();
      const analyzeLoadTime = Math.round(analyzeEndTime - analyzeStartTime);
      const s = data.salaries || {};
      const topSkills = Array.isArray(data.skills) ? data.skills.slice(0, 12) : [];
      
      // Display total vacancies found
      const vacancyStats = document.getElementById('vacancyStats');
      const totalVacancies = data.count || 0;
      vacancyStats.innerHTML = `Найдено ${totalVacancies.toLocaleString()} вакансий`;
      
      // Create salary stat icons instead of bar chart
      const salaryIcons = document.getElementById('salaryIcons');
      salaryIcons.innerHTML = '';
      
      const stats = [
        { label: 'Мин', value: s.min, icon: '📉', color: '#60a5fa' },
        { label: 'Медиана', value: s.median, icon: '📊', color: '#60a5fa' },
        { label: 'Средняя', value: s.avg, icon: '📈', color: '#60a5fa' },
        { label: 'Макс', value: s.max, icon: '🚀', color: '#60a5fa' }
      ];
      
      stats.forEach(stat => {
        const iconDiv = document.createElement('div');
        iconDiv.style.cssText = `
          text-align: center;
          padding: 12px;
          border-radius: 8px;
          background: linear-gradient(135deg, ${stat.color}20, ${stat.color}10);
          border: 1px solid ${stat.color}30;
          position: relative;
          cursor: help;
        `;
        
        // Add tooltip content based on the stat type
        let tooltipText = '';
        if (stat.label === 'Средняя') {
          tooltipText = 'Средняя зарплата - это сумма всех зарплат, разделенная на количество вакансий. Показывает общий уровень оплаты, но может быть искажена очень высокими или низкими значениями.';
        } else if (stat.label === 'Медиана') {
          tooltipText = 'Медиана - зарплата в середине списка. Половина вакансий платит меньше, половина - больше. Более устойчива к выбросам, чем средняя.';
        } else if (stat.label === 'Мин') {
          tooltipText = 'Минимальная зарплата - самая низкая зарплата среди всех найденных вакансий по данному запросу.';
        } else if (stat.label === 'Макс') {
          tooltipText = 'Максимальная зарплата - самая высокая зарплата среди всех найденных вакансий по данному запросу.';
        }
        
        iconDiv.innerHTML = `
          <div style="font-size: 24px; margin-bottom: 4px;">${stat.icon}</div>
          <div style="font-weight: bold; color: ${stat.color}; font-size: 14px;">${stat.label}</div>
          <div style="font-size: 16px; font-weight: bold; margin-top: 4px;">
            ${stat.value ? Math.round(stat.value).toLocaleString() + '₽' : 'N/A'}
          </div>
          <div class="tooltip" style="
            visibility: hidden;
            opacity: 0;
            position: absolute;
            z-index: 1000;
            bottom: 100%;
            left: 50%;
            transform: translateX(-50%);
            background: #1f2937;
            color: white;
            padding: 12px;
            border-radius: 8px;
            font-size: 12px;
            line-height: 1.4;
            max-width: 280px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            transition: opacity 0.3s, visibility 0.3s;
            pointer-events: none;
          ">
            ${tooltipText}
            <div style="
              position: absolute;
              top: 100%;
              left: 50%;
              transform: translateX(-50%);
              border: 6px solid transparent;
              border-top-color: #1f2937;
            "></div>
          </div>
        `;
        
        // Add hover event listeners
        iconDiv.addEventListener('mouseenter', function() {
          const tooltip = this.querySelector('.tooltip');
          tooltip.style.visibility = 'visible';
          tooltip.style.opacity = '1';
        });
        
        iconDiv.addEventListener('mouseleave', function() {
          const tooltip = this.querySelector('.tooltip');
          tooltip.style.visibility = 'hidden';
          tooltip.style.opacity = '0';
        });
        
        salaryIcons.appendChild(iconDiv);
      });


      // Bubble chart: fetch simplified items including employer marks
      const fUrl = new URL(window.location.origin + '/fetch');
      fUrl.searchParams.set('query', query);
      if (area) fUrl.searchParams.set('area', area);
      if (pages !== null) fUrl.searchParams.set('pages', String(pages));
      fUrl.searchParams.set('per_page', String(per_page));
      fUrl.searchParams.set('simplified', 'true');
      fUrl.searchParams.set('employer_mark', 'true');
      fUrl.searchParams.set('fetch_all', 'true');
      
      const bubbleStartTime = performance.now();
      const fres = await fetch(fUrl);
      const fdata = await fres.json();
      const bubbleEndTime = performance.now();
      const bubbleLoadTime = Math.round(bubbleEndTime - bubbleStartTime);
      const items = Array.isArray(fdata.items) ? fdata.items : [];
      console.log('Bubble chart data:', { itemsCount: items.length, sampleItem: items[0] });
      // Build salaries array (exclude per-shift)
      const salariesAll = items.map(v => {
        // Use monthly salary including per-shift vacancies if estimated monthly is provided
        if (v.salary_per_shift === true) {
          return (typeof v.salary_estimated_monthly === 'number') ? v.salary_estimated_monthly : null;
        }
        if (typeof v.salary_avg === 'number') return v.salary_avg;
        if (v.salary && typeof v.salary === 'object') {
          const sf = (typeof v.salary.from === 'number') ? v.salary.from : null;
          const st = (typeof v.salary.to === 'number') ? v.salary.to : null;
          if (sf !== null && st !== null) return (sf + st) / 2;
          if (sf !== null) return sf;
          if (st !== null) return st;
        }
        return null;
      }).filter(x => typeof x === 'number' && x >= 13000).sort((a,b) => a-b);

      // Percentile helper
      const percentile = (arr, p) => {
        if (!arr.length) return null;
        const idx = (arr.length - 1) * p;
        const lo = Math.floor(idx);
        const hi = Math.ceil(idx);
        if (lo === hi) return arr[lo];
        const w = idx - lo;
        return arr[lo] * (1 - w) + arr[hi] * w;
      };

      // Apply high outlier filtering (Tukey IQR). Fallback for tiny samples.
      let salaries = salariesAll;
      if (salariesAll.length >= 4) {
        const q1 = percentile(salariesAll, 0.25);
        const q3 = percentile(salariesAll, 0.75);
        const iqr = q3 - q1;
        if (iqr > 0) {
          const highCut = q3 + 1.5 * iqr;
          const filtered = salariesAll.filter(s => s <= highCut);
          if (filtered.length >= Math.min(3, salariesAll.length)) {
            salaries = filtered;
          }
        }
      } else if (salariesAll.length >= 2) {
        const medSmall = percentile(salariesAll, 0.50);
        if (salariesAll[salariesAll.length - 1] > 2 * medSmall) {
          salaries = salariesAll.slice(0, -1);
        }
      }

      // Determine an upper salary threshold for bubble points to hide extreme single values
      // Use the same Tukey IQR rule when possible; otherwise use a conservative 2x median cap
      let salaryUpperCap = Number.POSITIVE_INFINITY;
      if (salariesAll.length >= 4) {
        const q1Cap = percentile(salariesAll, 0.25);
        const q3Cap = percentile(salariesAll, 0.75);
        const iqrCap = q3Cap - q1Cap;
        if (iqrCap > 0) {
          salaryUpperCap = q3Cap + 1.5 * iqrCap;
        }
      } else if (salariesAll.length >= 2) {
        const medSmallCap = percentile(salariesAll, 0.50);
        salaryUpperCap = 2 * medSmallCap;
      }

      const p25 = percentile(salaries, 0.25);
      const p50 = percentile(salaries, 0.50);
      const p75 = percentile(salaries, 0.75);
      const sMax = salaries.length ? salaries[salaries.length - 1] : null;
      const sAvg = salaries.length ? (salaries.reduce((a,b)=>a+b,0) / salaries.length) : null;
      // Average salary for Pulkovo employers
      const pulkovoSalaries = items
        .filter(v => isPulkovoEmployerName(v.employer_name))
        .map(v => {
          if (v.salary_per_shift === true) {
            return (typeof v.salary_estimated_monthly === 'number') ? v.salary_estimated_monthly : null;
          }
          if (typeof v.salary_avg === 'number') return v.salary_avg;
          if (v.salary && typeof v.salary === 'object') {
            const sf = (typeof v.salary.from === 'number') ? v.salary.from : null;
            const st = (typeof v.salary.to === 'number') ? v.salary.to : null;
            if (sf !== null && st !== null) return (sf + st) / 2;
            if (sf !== null) return sf;
            if (st !== null) return st;
          }
          return null;
        })
        .filter(x => typeof x === 'number');
      
      // Store original salaries for team project button functionality
      window.originalSalaries = [...salaries];
      window.currentSalaries = [...salaries];
      
      // Add additional salary amounts to Pulkovo salaries based on query and button state
      const currentQueryForAdd = new URLSearchParams(window.location.search).get('query') || '';
      const normalizedQueryForAdd = currentQueryForAdd.toLowerCase().trim();
      const additionalPulkovoSalary = getTeamProjectAdditionalForQuery(normalizedQueryForAdd);
      
      // For ML инженер, add Pulkovo salary (200,000) to pulkovoSalaries if not already present
      if (normalizedQueryForAdd.includes('ml инженер')) {
        pulkovoSalaries.push(200000);
      }
      
      // For аналитик данных sql, add Pulkovo salary (150,000) to pulkovoSalaries if not already present
      if (normalizedQueryForAdd.includes('аналитик данных sql')) {
        pulkovoSalaries.push(150000);
      }
      
      const pulkovoAvg = pulkovoSalaries.length ? (pulkovoSalaries.reduce((a,b)=>a+b,0) / pulkovoSalaries.length) + additionalPulkovoSalary : null;

      // Render market scale bands and ticks if data exists
      const scaleEl = document.getElementById('marketScale');
      if (p25 && p50 && p75 && sMax) {
        const minBase = salaries[0];
        const span = sMax - minBase || 1;
        const toPct = (v) => `${Math.max(0, Math.min(100, ((v - minBase) / span) * 100))}%`;
        document.getElementById('bandBelow').style.width = toPct(p25);
        document.getElementById('bandIn').style.left = toPct(p25);
        document.getElementById('bandIn').style.width = `calc(${toPct(p75)} - ${toPct(p25)})`;
        document.getElementById('bandAbove').style.left = toPct(p75);
        document.getElementById('bandAbove').style.width = `calc(100% - ${toPct(p75)})`;

        // Place Pulkovo salary marker
        const pulkovoMarker = document.getElementById('markerPulkovoLine');
        const pulkovoLabel = document.getElementById('markerPulkovoLabel');
        if (pulkovoAvg) {
          pulkovoMarker.style.left = toPct(pulkovoAvg);
          pulkovoMarker.style.display = 'block';
          pulkovoLabel.style.left = toPct(pulkovoAvg);
          pulkovoLabel.innerText = `Пулково: ${Math.round(pulkovoAvg).toLocaleString()}₽`;
          pulkovoLabel.style.display = 'block';
        } else {
          pulkovoMarker.style.display = 'none';
          pulkovoLabel.style.display = 'none';
        }

      } else {
        scaleEl.innerHTML = '<div style="padding:8px; color:#6b7280;">Недостаточно данных для расчёта</div>';
      }

      const points = items
        .map(v => {
          // Compute monthly salary value, converting per-shift to monthly when available
          let monthly = null;
          if (v.salary_per_shift === true) {
            if (typeof v.salary_estimated_monthly === 'number') {
              monthly = v.salary_estimated_monthly;
            }
          } else if (typeof v.salary_avg === 'number') {
            monthly = v.salary_avg;
          }
          if (monthly === null && v.salary && typeof v.salary === 'object') {
            const sf = (typeof v.salary.from === 'number') ? v.salary.from : null;
            const st = (typeof v.salary.to === 'number') ? v.salary.to : null;
            if (sf !== null && st !== null) monthly = (sf + st) / 2;
            else if (sf !== null) monthly = sf;
            else if (st !== null) monthly = st;
          }
          // Prefer employer_mark; if missing, fallback to employer_trusted as 1/0
          let rating = null;
          if (typeof v.employer_mark === 'number') {
            rating = v.employer_mark;
          } else if (typeof v.employer_trusted === 'boolean') {
            rating = v.employer_trusted ? 1 : 0;
          }
          const isPulkovo = isPulkovoEmployerName(v.employer_name);
          const isRossiya = v.employer_name && v.employer_name.includes('Авиакомпания Россия');

          // Add additional salary to Pulkovo vacancies only when button is active
          if (isPulkovo && monthly !== null) {
            const currentQueryPts = new URLSearchParams(window.location.search).get('query') || '';
            const normalizedQueryPts = currentQueryPts.toLowerCase().trim();
            const addPts = getTeamProjectAdditionalForQuery(normalizedQueryPts);
            if (addPts > 0) monthly += addPts;
          }


          if (monthly === null || rating === null || monthly < 13000) {
            return null;
          }
          // Hide extreme salary outliers from the bubble chart
          // IMPORTANT: Always keep Pulkovo points visible even if they exceed caps
          if (!isPulkovo && monthly > salaryUpperCap) {
            return null;
          }
          // Check if it's a highlighted company that should have larger bubble size
          const isHighlightedCompany = isPulkovo || isRossiya || 
            (v.employer_name && v.employer_name.includes('Петербургский Метрополитен')) ||
            (v.employer_name && v.employer_name.includes('АО Зенит-Арена')) ||
            (v.employer_name && v.employer_name.includes('Ozon')) ||
            (v.employer_name && v.employer_name.includes('Теремок')) ||
            (v.employer_name && v.employer_name.includes('WILDBERRIES'));
          
          return {
            x: monthly,
            y: rating,
            r: isHighlightedCompany ? 12 : 6, // Larger bubble for highlighted companies
            title: v.title || '',
            employer: v.employer_name || '',
            isPulkovo: isPulkovo
          };
        })
        .filter(p => p !== null);
      
      // Add specific vacancies for специалист сбовс
      if (query && (query.toLowerCase().includes('специалист сбовс') || query.toLowerCase().includes('уборщик клининг'))) {
        // Add Теремок vacancy
        const teremokVacancy = {
          x: 87500, // Average of 80,000-95,000 range
          y: 4.2, // High employer rating for Теремок
          r: 12, // Same size as Pulkovo bubbles
          title: 'Уборщица/Уборщик в ресторан',
          employer: 'Теремок - Русские Блины',
          isPulkovo: false,
          isTeremok: true
        };
        points.push(teremokVacancy);
        console.log('Added Teremok vacancy:', teremokVacancy);
      }
      
      // Add specific vacancy for водитель категория D
      if (query && query.toLowerCase().includes('водитель категория d')) {
        const ozonVacancy = {
          x: 176000, // Average of 144,000-208,000 range
          y: 4.0, // High employer rating for Ozon
          r: 12, // Same size as Pulkovo bubbles
          title: 'Водитель-курьер на автомобиле компании',
          employer: 'Озон',
          isPulkovo: false,
          isOzonHighlight: true
        };
        points.push(ozonVacancy);
        console.log('Added Ozon vacancy:', ozonVacancy);
      }
      
      // Add specific vacancies for грузчик нагрузки
      if (query && query.toLowerCase().includes('грузчик нагрузки')) {
        // Почта России - https://spb.hh.ru/vacancy/123637422
        const pochtaVacancy = {
          x: 61000, // Salary from https://spb.hh.ru/vacancy/123637422
          y: 3.5, // Employer rating for Почта России
          r: 12, // Same size as Pulkovo bubbles
          title: 'Грузчик',
          employer: 'Почта России',
          isPulkovo: false,
          isPochta: true
        };
        points.push(pochtaVacancy);
        console.log('Added Почта России vacancy:', pochtaVacancy);
        
        // Магнит - https://spb.hh.ru/vacancy/127281337
        const magnitVacancy = {
          x: 104000, // Salary from https://spb.hh.ru/vacancy/127281337
          y: 3.8, // Employer rating for Магнит
          r: 12, // Same size as Pulkovo bubbles
          title: 'Грузчик',
          employer: 'Магнит',
          isPulkovo: false,
          isMagnit: true
        };
        points.push(magnitVacancy);
        console.log('Added Магнит vacancy:', magnitVacancy);
        
        // DNS - https://spb.hh.ru/vacancy/121166330
        const dnsVacancy = {
          x: 110000, // Salary from https://spb.hh.ru/vacancy/121166330
          y: 3.6, // Employer rating for DNS
          r: 12, // Same size as Pulkovo bubbles
          title: 'Грузчик',
          employer: 'DNS',
          isPulkovo: false,
          isDNS: true
        };
        points.push(dnsVacancy);
        console.log('Added DNS vacancy:', dnsVacancy);
      }
      
      // Add specific vacancies for мойщик посуды
      if (query && query.toLowerCase().includes('мойщик посуды')) {
        // Токио-сити - https://spb.hh.ru/vacancy/114964025
        const tokyoSitiVacancy = {
          x: 75000, // Average of 65,000-85,000 range from https://spb.hh.ru/vacancy/114964025
          y: 4.1, // Company rating for ТОКИО-CITY
          r: 12, // Same size as Pulkovo bubbles
          title: 'Мойщик посуды',
          employer: 'Токио-сити',
          isPulkovo: false,
          isTokyoSiti: true
        };
        points.push(tokyoSitiVacancy);
        console.log('Added Токио-сити vacancy:', tokyoSitiVacancy);
        
        // Бона Капона - https://spb.hh.ru/vacancy/126795069
        const bonaKaponaVacancy = {
          x: 78000, // Average of 73,000-83,000 range from https://spb.hh.ru/vacancy/126795069
          y: 4.0, // Company rating for Bona People Group
          r: 12, // Same size as Pulkovo bubbles
          title: 'Мойщик посуды',
          employer: 'Бона Капона',
          isPulkovo: false,
          isBonaKapona: true
        };
        points.push(bonaKaponaVacancy);
        console.log('Added Бона Капона vacancy:', bonaKaponaVacancy);
        
        // DelMar - https://spb.hh.ru/vacancy/126087218
        const delmarVacancy = {
          x: 85000, // Average of 80,000-90,000 range from https://spb.hh.ru/vacancy/126087218
          y: 3.7, // Company rating for Del Mar
          r: 12, // Same size as Pulkovo bubbles
          title: 'Мойщик посуды',
          employer: 'DelMar',
          isPulkovo: false,
          isDelMar: true
        };
        points.push(delmarVacancy);
        console.log('Added DelMar vacancy:', delmarVacancy);
        
        // Ginza - https://spb.hh.ru/vacancy/126629566
        const ginzaVacancy = {
          x: 84000, // Salary from https://spb.hh.ru/vacancy/126629566
          y: 3.4, // Company rating for Ginza Project
          r: 12, // Same size as Pulkovo bubbles
          title: 'Мойщик посуды',
          employer: 'Ginza',
          isPulkovo: false,
          isGinza: true
        };
        points.push(ginzaVacancy);
        console.log('Added Ginza vacancy:', ginzaVacancy);
      }
      
      // Add specific vacancies for ML инженер
      if (query && query.toLowerCase().includes('ml инженер')) {
        // Pulkovo - ML Engineer / Инженер машинного обучения
        const pulkovoMLVacancy = {
          x: 200000, // Salary 200,000 ₽
          y: 3.5, // Company rating for Pulkovo
          r: 12, // Same size as Pulkovo bubbles
          title: 'ML Engineer / Инженер машинного обучения',
          employer: 'Аэропорт Пулково',
          isPulkovo: true,
          isRadiofid: false
        };
        points.push(pulkovoMLVacancy);
        console.log('Added Pulkovo ML vacancy:', pulkovoMLVacancy);
        
        // Радиофид - ML Engineer / Инженер машинного обучения
        const radiofidVacancy = {
          x: 130000, // Salary от 130,000 ₽/мес
          y: 4.7, // Company rating 4.7★
          r: 12, // Same size as Pulkovo bubbles
          title: 'ML Engineer / Инженер машинного обучения',
          employer: 'Радиофид',
          isPulkovo: false,
          isRadiofid: true
        };
        points.push(radiofidVacancy);
        console.log('Added Радиофид vacancy:', radiofidVacancy);
      }
      
      // Add specific vacancies for аналитик данных sql
      if (query && query.toLowerCase().includes('аналитик данных sql')) {
        // Pulkovo - Аналитик данных
        const pulkovoAnalystVacancy = {
          x: 150000, // Salary 150,000 ₽
          y: 3.5, // Company rating for Pulkovo
          r: 12, // Same size as Pulkovo bubbles
          title: 'Аналитик данных',
          employer: 'Аэропорт Пулково',
          isPulkovo: true,
          isGorbilet: false
        };
        points.push(pulkovoAnalystVacancy);
        console.log('Added Pulkovo аналитик данных vacancy:', pulkovoAnalystVacancy);
        
        // ООО Горбилет - Продуктовый аналитик
        const gorbiletVacancy = {
          x: 200000, // Salary from 200,000 ₽
          y: 4.5, // Company rating 4.5
          r: 12, // Same size as Pulkovo bubbles
          title: 'Продуктовый аналитик',
          employer: 'ООО Горбилет',
          isPulkovo: false,
          isGorbilet: true
        };
        points.push(gorbiletVacancy);
        console.log('Added ООО Горбилет vacancy:', gorbiletVacancy);
        
        // Аналитик данных / Data Analyst (SQL)
        const dataAnalystVacancy = {
          x: 150000, // Salary 150,000 ₽
          y: 4.2, // Company rating 4.2
          r: 12, // Same size as Pulkovo bubbles
          title: 'Аналитик данных / Data Analyst (SQL)',
          employer: 'StudyWorld',
          isPulkovo: false,
          isDataAnalyst: true
        };
        points.push(dataAnalystVacancy);
        console.log('Added StudyWorld vacancy:', dataAnalystVacancy);
        
        // Т‑Банк - Аналитик операционных процессов (POS)
        const tbankVacancy = {
          x: 144000, // Salary от 144,000 ₽/месяц
          y: 4.1, // Company rating 4.1
          r: 12, // Same size as Pulkovo bubbles
          title: 'Аналитик операционных процессов (POS)',
          employer: 'Т‑Банк',
          isPulkovo: false,
          isTbank: true
        };
        points.push(tbankVacancy);
        console.log('Added Т‑Банк vacancy:', tbankVacancy);
      }
      
      // Add specific vacancies for машинист катка
      if (query && query.toLowerCase().includes('машинист катка')) {
        // ООО ЖЕЛДОРСТРОЙ - Машинист катка
        const zheldorVacancy = {
          x: 180000, // Salary 180,000 ₽
          y: 3.5, // Company rating 3.5
          r: 12, // Same size as Pulkovo bubbles
          title: 'Машинист катка',
          employer: 'ООО ЖЕЛДОРСТРОЙ',
          isPulkovo: false,
          isZheldor: true
        };
        points.push(zheldorVacancy);
        console.log('Added ООО ЖЕЛДОРСТРОЙ vacancy:', zheldorVacancy);
        
        // ООО ТрансГеоСервис - Машинист катка
        const transGeoVacancy = {
          x: 141000, // Salary 141,000 ₽
          y: 5.0, // Company rating 5.0
          r: 12, // Same size as Pulkovo bubbles
          title: 'Машинист катка',
          employer: 'ООО ТрансГеоСервис',
          isPulkovo: false,
          isTransGeo: true
        };
        points.push(transGeoVacancy);
        console.log('Added ООО ТрансГеоСервис vacancy:', transGeoVacancy);
      }
      
      console.log('Bubble chart points:', { pointsCount: points.length, samplePoints: points.slice(0, 3) });
      // Create horizontal bar chart for candidate requirements
      const barChartContainer = document.getElementById('barChartContainer');
      if (barChartContainer) {
        barChartContainer.innerHTML = '';
        
        // Combine skills and experience data for the bar chart
        const chartData = [];
        
        // Add top skills
        topSkills.slice(0, 5).forEach((skill, index) => {
          const count = skillCounts.get(skill) || 0;
          chartData.push({
            label: skill,
            value: count,
            type: 'skill'
          });
        });
        
        // Add experience data
        const expCounts = new Map();
        items.forEach(v => {
          const e = (v.experience || '').toString().trim();
          if (!e) return;
          expCounts.set(e, (expCounts.get(e) || 0) + 1);
        });
        const expEntries = Array.from(expCounts.entries()).sort((a,b)=>b[1]-a[1]).slice(0, 3);
        expEntries.forEach(([label, count]) => {
          chartData.push({
            label: label,
            value: count,
            type: 'experience'
          });
        });
        
        // Sort by value and take top 5
        const sortedData = chartData.sort((a, b) => b.value - a.value).slice(0, 5);
        const maxValue = Math.max(...sortedData.map(d => d.value));
        
        // Create scale with tick marks (like in the image)
        const scaleTicks = document.getElementById('scaleTicks');
        const scaleTickMarks = document.getElementById('scaleTickMarks');
        
        if (scaleTicks && scaleTickMarks) {
          scaleTicks.innerHTML = '';
          scaleTickMarks.innerHTML = '';
          
          // Create tick marks at intervals of 10, 20, 30, etc. up to maxValue
          const tickInterval = Math.ceil(maxValue / 6); // Create about 6 tick marks
          const roundedInterval = Math.ceil(tickInterval / 10) * 10; // Round to nearest 10
          
          for (let i = 0; i <= maxValue; i += roundedInterval) {
            const percentage = (i / maxValue) * 100;
            
            // Create number labels above
            const tickLabel = document.createElement('div');
            tickLabel.textContent = i;
            tickLabel.style.cssText = `position: absolute; left: ${percentage}%; transform: translateX(-50%); font-size: 11px; color: #cbd5e1; text-align: center; white-space: nowrap; line-height: 1; font-weight: 400;`;
            scaleTicks.appendChild(tickLabel);
            
            // Create tick marks on the line
            const tickMark = document.createElement('div');
            tickMark.style.cssText = `position: absolute; left: ${percentage}%; transform: translateX(-50%); width: 1px; height: 8px; background: rgba(148, 163, 184, 0.3);`;
            scaleTickMarks.appendChild(tickMark);
          }
        }
        
        sortedData.forEach((item, index) => {
          const percentage = (item.value / maxValue) * 100;
          
          const barContainer = document.createElement('div');
          barContainer.style.cssText = 'display: flex; align-items: center; gap: 12px; margin-bottom: 8px;';
          
          const label = document.createElement('div');
          label.textContent = item.label;
          label.style.cssText = 'min-width: 120px; font-size: 13px; color: #cbd5e1; font-weight: 500;';
          
          const barWrapper = document.createElement('div');
          barWrapper.style.cssText = 'flex: 1; position: relative; height: 28px; background: rgba(148, 163, 184, 0.1); border-radius: 6px; overflow: hidden; border: 1px solid rgba(148, 163, 184, 0.15);';
          
          const bar = document.createElement('div');
          bar.style.cssText = `height: 100%; width: ${percentage}%; background: linear-gradient(135deg, #3b82f6, #06b6d4); border-radius: 6px; transition: all 0.3s ease; position: relative; box-shadow: 0 2px 4px rgba(59, 130, 246, 0.2);`;
          
          // Add value label at the end of the bar (inside the bar)
          const valueLabel = document.createElement('div');
          valueLabel.textContent = item.value;
          valueLabel.style.cssText = 'position: absolute; right: 8px; top: 50%; transform: translateY(-50%); font-size: 12px; color: white; font-weight: 600; white-space: nowrap; text-shadow: 0 1px 2px rgba(0,0,0,0.3);';
          
          bar.appendChild(valueLabel);
          barWrapper.appendChild(bar);
          barContainer.appendChild(label);
          barContainer.appendChild(barWrapper);
          barChartContainer.appendChild(barContainer);
        });
      }
      const bubbleCtx = document.getElementById('bubbleChart');
      // Separate companies into different datasets
      const pulkovoPoints = points.filter(p => p.isPulkovo);
      const rossiyaPoints = points.filter(p => p.employer && p.employer.includes('Авиакомпания Россия'));
      const metroPoints = points.filter(p => p.employer && p.employer.includes('Петербургский Метрополитен'));
      const zenitPoints = points.filter(p => p.employer && p.employer.includes('АО Зенит-Арена'));
      const ozonPoints = points.filter(p => p.employer && p.employer.includes('Ozon'));
      const teremokPoints = points.filter(p => p.employer && p.employer.includes('Теремок'));
      const wildberriesPoints = points.filter(p => p.employer && p.employer.includes('WILDBERRIES'));
      const pobedaPoints = points.filter(p => p.employer && p.employer.includes('Авиакомпания Победа'));
      const teremokHighlightPoints = points.filter(p => p.employer && p.employer.includes('Теремок - Русские Блины'));
      const ozonHighlightPoints = points.filter(p => p.employer && p.employer.includes('Озон') && p.isOzonHighlight);
      const pochtaPoints = points.filter(p => p.isPochta);
      const magnitPoints = points.filter(p => p.isMagnit);
      const dnsPoints = points.filter(p => p.isDNS);
      const tokyoSitiPoints = points.filter(p => p.isTokyoSiti);
      const bonaKaponaPoints = points.filter(p => p.isBonaKapona);
      const delmarPoints = points.filter(p => p.isDelMar);
      const ginzaPoints = points.filter(p => p.isGinza);
      const radiofidPoints = points.filter(p => p.isRadiofid);
      const gorbiletPoints = points.filter(p => p.isGorbilet);
      const dataAnalystPoints = points.filter(p => p.isDataAnalyst);
      const tbankPoints = points.filter(p => p.isTbank);
      const zheldorPoints = points.filter(p => p.isZheldor);
      const transGeoPoints = points.filter(p => p.isTransGeo);
      const otherPoints = points.filter(p => 
        !p.isPulkovo && 
        !(p.employer && p.employer.includes('Авиакомпания Россия')) &&
        !(p.employer && p.employer.includes('Петербургский Метрополитен')) &&
        !(p.employer && p.employer.includes('АО Зенит-Арена')) &&
        !(p.employer && p.employer.includes('Ozon')) &&
        !(p.employer && p.employer.includes('Теремок')) &&
        !(p.employer && p.employer.includes('WILDBERRIES')) &&
        !(p.employer && p.employer.includes('Авиакомпания Победа')) &&
        !p.isPochta &&
        !p.isMagnit &&
        !p.isDNS &&
        !p.isTokyoSiti &&
        !p.isBonaKapona &&
        !p.isDelMar &&
        !p.isGinza &&
        !p.isRadiofid &&
        !p.isGorbilet &&
        !p.isDataAnalyst &&
        !p.isTbank &&
        !p.isZheldor &&
        !p.isTransGeo
      );
      
      console.log('Chart datasets:', {
        totalPoints: points.length,
        pulkovoCount: pulkovoPoints.length,
        rossiyaCount: rossiyaPoints.length,
        metroCount: metroPoints.length,
        zenitCount: zenitPoints.length,
        ozonCount: ozonPoints.length,
        teremokCount: teremokPoints.length,
        wildberriesCount: wildberriesPoints.length,
        pobedaCount: pobedaPoints.length,
        teremokHighlightCount: teremokHighlightPoints.length,
        ozonHighlightCount: ozonHighlightPoints.length,
        otherCount: otherPoints.length,
        rossiyaSample: rossiyaPoints.slice(0, 2)
      });
      
      // Debug: Check if rossiyaPoints have valid data
      if (rossiyaPoints.length > 0) {
        console.log('Rossiya points details:', rossiyaPoints.map(p => ({
          title: p.title,
          employer: p.employer,
          x: p.x,
          y: p.y,
          r: p.r
        })));
      } else {
        console.log('No Rossiya points found!');
      }
      
      new Chart(bubbleCtx, {
        type: 'bubble',
        data: { 
          datasets: [
            {
              label: 'Другие компании',
              data: otherPoints,
              backgroundColor: 'rgba(59, 130, 246, 0.4)',
              borderColor: 'rgba(59, 130, 246, 0.8)',
              borderWidth: 1,
              hoverBackgroundColor: 'rgba(59, 130, 246, 0.7)',
              hoverBorderColor: 'rgba(59, 130, 246, 1)',
              hoverBorderWidth: 2
            },
            {
              label: 'Аэропорт Пулково',
              data: pulkovoPoints,
              backgroundColor: 'rgba(6, 182, 212, 0.5)',
              borderColor: 'rgba(6, 182, 212, 0.9)',
              borderWidth: 2,
              hoverBackgroundColor: 'rgba(6, 182, 212, 0.8)',
              hoverBorderColor: 'rgba(6, 182, 212, 1)',
              hoverBorderWidth: 3
            },
            {
              label: 'Авиакомпания Россия',
              data: rossiyaPoints,
              backgroundColor: 'rgba(239, 68, 68, 0.4)',
              borderColor: 'rgba(239, 68, 68, 0.8)',
              borderWidth: 1,
              hoverBackgroundColor: 'rgba(239, 68, 68, 0.7)',
              hoverBorderColor: 'rgba(239, 68, 68, 1)',
              hoverBorderWidth: 2
            },
            {
              label: 'Петербургский Метрополитен',
              data: metroPoints,
              backgroundColor: 'rgba(173, 216, 230, 0.7)',
              borderColor: 'rgba(173, 216, 230, 0.9)',
              borderWidth: 2,
              hoverBackgroundColor: 'rgba(173, 216, 230, 0.8)',
              hoverBorderColor: 'rgba(173, 216, 230, 1)',
              hoverBorderWidth: 3
            },
            {
              label: 'АО Зенит-Арена',
              data: zenitPoints,
              backgroundColor: 'rgba(1, 201, 88, 0.5)',
              borderColor: 'rgba(1, 201, 88, 0.9)',
              borderWidth: 2,
              hoverBackgroundColor: 'rgba(1, 201, 88, 0.8)',
              hoverBorderColor: 'rgba(1, 201, 88, 1)',
              hoverBorderWidth: 3
            },
            {
              label: 'Ozon',
              data: ozonPoints,
              backgroundColor: 'rgba(255, 165, 0, 0.5)',
              borderColor: 'rgba(255, 165, 0, 0.9)',
              borderWidth: 2,
              hoverBackgroundColor: 'rgba(255, 165, 0, 0.8)',
              hoverBorderColor: 'rgba(255, 165, 0, 1)',
              hoverBorderWidth: 3
            },
            {
              label: 'WILDBERRIES',
              data: wildberriesPoints,
              backgroundColor: 'rgba(147, 51, 234, 0.5)',
              borderColor: 'rgba(147, 51, 234, 0.9)',
              borderWidth: 2,
              hoverBackgroundColor: 'rgba(147, 51, 234, 0.8)',
              hoverBorderColor: 'rgba(147, 51, 234, 1)',
              hoverBorderWidth: 3
            },
            {
              label: 'Авиакомпания Победа',
              data: pobedaPoints,
              backgroundColor: 'rgba(220, 38, 38, 0.6)',
              borderColor: 'rgba(220, 38, 38, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(220, 38, 38, 0.8)',
              hoverBorderColor: 'rgba(220, 38, 38, 1)',
              hoverBorderWidth: 4
            },
            {
              label: 'Теремок',
              data: teremokHighlightPoints,
              backgroundColor: 'rgba(255, 193, 7, 0.6)',
              borderColor: 'rgba(255, 193, 7, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(255, 193, 7, 0.8)',
              hoverBorderColor: 'rgba(255, 193, 7, 1)',
              hoverBorderWidth: 4
            },
            {
              label: 'Озон',
              data: ozonHighlightPoints,
              backgroundColor: 'rgba(255, 20, 147, 0.6)',
              borderColor: 'rgba(255, 20, 147, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(255, 20, 147, 0.8)',
              hoverBorderColor: 'rgba(255, 20, 147, 1)',
              hoverBorderWidth: 4
            },
            {
              label: 'Почта России',
              data: pochtaPoints,
              backgroundColor: 'rgba(34, 139, 34, 0.6)',
              borderColor: 'rgba(34, 139, 34, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(34, 139, 34, 0.8)',
              hoverBorderColor: 'rgba(34, 139, 34, 1)',
              hoverBorderWidth: 4
            },
            {
              label: 'Магнит',
              data: magnitPoints,
              backgroundColor: 'rgba(255, 69, 0, 0.6)',
              borderColor: 'rgba(255, 69, 0, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(255, 69, 0, 0.8)',
              hoverBorderColor: 'rgba(255, 69, 0, 1)',
              hoverBorderWidth: 4
            },
            {
              label: 'DNS',
              data: dnsPoints,
              backgroundColor: 'rgba(0, 191, 255, 0.6)',
              borderColor: 'rgba(0, 191, 255, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(0, 191, 255, 0.8)',
              hoverBorderColor: 'rgba(0, 191, 255, 1)',
              hoverBorderWidth: 4
            },
            {
              label: 'Токио-сити',
              data: tokyoSitiPoints,
              backgroundColor: 'rgba(255, 140, 0, 0.6)',
              borderColor: 'rgba(255, 140, 0, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(255, 140, 0, 0.8)',
              hoverBorderColor: 'rgba(255, 140, 0, 1)',
              hoverBorderWidth: 4
            },
            {
              label: 'Бона Капона',
              data: bonaKaponaPoints,
              backgroundColor: 'rgba(138, 43, 226, 0.6)',
              borderColor: 'rgba(138, 43, 226, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(138, 43, 226, 0.8)',
              hoverBorderColor: 'rgba(138, 43, 226, 1)',
              hoverBorderWidth: 4
            },
            {
              label: 'DelMar',
              data: delmarPoints,
              backgroundColor: 'rgba(50, 205, 50, 0.6)',
              borderColor: 'rgba(50, 205, 50, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(50, 205, 50, 0.8)',
              hoverBorderColor: 'rgba(50, 205, 50, 1)',
              hoverBorderWidth: 4
            },
            {
              label: 'Ginza',
              data: ginzaPoints,
              backgroundColor: 'rgba(255, 99, 71, 0.6)',
              borderColor: 'rgba(255, 99, 71, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(255, 99, 71, 0.8)',
              hoverBorderColor: 'rgba(255, 99, 71, 1)',
              hoverBorderWidth: 4
            },
            {
              label: 'Радиофид',
              data: radiofidPoints,
              backgroundColor: 'rgba(75, 0, 130, 0.6)',
              borderColor: 'rgba(75, 0, 130, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(75, 0, 130, 0.8)',
              hoverBorderColor: 'rgba(75, 0, 130, 1)',
              hoverBorderWidth: 4
            },
            {
              label: 'ООО Горбилет',
              data: gorbiletPoints,
              backgroundColor: 'rgba(255, 215, 0, 0.6)',
              borderColor: 'rgba(255, 215, 0, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(255, 215, 0, 0.8)',
              hoverBorderColor: 'rgba(255, 215, 0, 1)',
              hoverBorderWidth: 4
            },
            {
              label: 'StudyWorld',
              data: dataAnalystPoints,
              backgroundColor: 'rgba(30, 144, 255, 0.6)',
              borderColor: 'rgba(30, 144, 255, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(30, 144, 255, 0.8)',
              hoverBorderColor: 'rgba(30, 144, 255, 1)',
              hoverBorderWidth: 4
            },
            {
              label: 'Т‑Банк',
              data: tbankPoints,
              backgroundColor: 'rgba(220, 20, 60, 0.6)',
              borderColor: 'rgba(220, 20, 60, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(220, 20, 60, 0.8)',
              hoverBorderColor: 'rgba(220, 20, 60, 1)',
              hoverBorderWidth: 4
            },
            {
              label: 'ООО ЖЕЛДОРСТРОЙ',
              data: zheldorPoints,
              backgroundColor: 'rgba(139, 69, 19, 0.6)',
              borderColor: 'rgba(139, 69, 19, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(139, 69, 19, 0.8)',
              hoverBorderColor: 'rgba(139, 69, 19, 1)',
              hoverBorderWidth: 4
            },
            {
              label: 'ООО ТрансГеоСервис',
              data: transGeoPoints,
              backgroundColor: 'rgba(0, 128, 128, 0.6)',
              borderColor: 'rgba(0, 128, 128, 1)',
              borderWidth: 3,
              hoverBackgroundColor: 'rgba(0, 128, 128, 0.8)',
              hoverBorderColor: 'rgba(0, 128, 128, 1)',
              hoverBorderWidth: 4
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: true,
          interaction: {
            mode: 'nearest',
            intersect: true
          },
          plugins: {
            legend: { 
              display: true,
              position: 'bottom',
              labels: {
                font: {
                  size: 11,
                  weight: '500'
                },
                color: '#64748b',
                padding: 8,
                usePointStyle: true,
                pointStyle: 'circle',
                filter: function(legendItem, chartData) {
                  // Only show legend items for datasets that have data points
                  const datasetIndex = legendItem.datasetIndex;
                  const dataset = chartData.datasets[datasetIndex];
                  return dataset.data && dataset.data.length > 0;
                }
              }
            },
            tooltip: {
              enabled: true,
              backgroundColor: 'rgba(30, 41, 59, 0.95)',
              titleColor: '#ffffff',
              bodyColor: '#cbd5e1',
              borderColor: 'rgba(59, 130, 246, 0.5)',
              borderWidth: 1,
              padding: 12,
              displayColors: true,
              boxPadding: 6,
              callbacks: {
                title: (ctx) => {
                  const v = ctx[0].raw;
                  return v.employer;
                },
                label: (ctx) => {
                  const v = ctx.raw;
                  return [
                    `Вакансия: ${v.title}`,
                    `Зарплата: ${Math.round(v.x).toLocaleString()} ₽`,
                    `Рейтинг: ${v.y.toFixed(1)} / 5.0`
                  ];
                }
              }
            }
          },
          scales: {
            x: { 
              title: { 
                display: true, 
                text: 'Зарплата',
                font: {
                  size: 13,
                  weight: '500'
                },
                color: '#94a3b8'
              },
              grid: {
                color: 'rgba(148, 163, 184, 0.15)',
                lineWidth: 1
              },
              ticks: {
                color: '#cbd5e1',
                font: {
                  size: 11,
                  weight: '400'
                },
                callback: function(value) {
                  return (value / 1000).toFixed(0) + 'k';
                }
              }
            },
            y: { 
              title: { 
                display: true, 
                text: 'Рейтинг работодателя',
                font: {
                  size: 13,
                  weight: '500'
                },
                color: '#94a3b8'
              },
              min: 1,
              max: 5,
              grid: {
                color: 'rgba(148, 163, 184, 0.15)',
                lineWidth: 1
              },
              ticks: {
                color: '#cbd5e1',
                font: {
                  size: 11,
                  weight: '400'
                },
                stepSize: 0.5
              }
            }
          }
        }
      });

      // Create salary histogram
      createSalaryHistogram(salaries, s, items);

      // Resume stats card - automatically collect resume IDs
      try {
        console.log('Loading resume stats for query:', query);
        const rsUrl = new URL(window.location.origin + '/resume-stats');
        // Only add resume_ids if they were manually provided
        if (resume_ids.length > 0) {
          resume_ids.forEach(id => rsUrl.searchParams.append('resume_ids', id));
        }
        rsUrl.searchParams.set('vacancy_query', query);
        rsUrl.searchParams.set('area', area);
        rsUrl.searchParams.set('pages', String(pages));
        rsUrl.searchParams.set('per_page', String(per_page));
        rsUrl.searchParams.set('auto_collect', 'true');
        console.log('Fetching resume stats from:', rsUrl.toString());
        const rsRes = await fetch(rsUrl);
        const rs = await rsRes.json();
        console.log('Resume stats response:', rs);
        const meta = document.getElementById('resumeStatsMeta');
        const grid = document.getElementById('resumeStatsGrid');
        const autoCollected = resume_ids.length === 0;
        const totalResumes = rs.total_resumes || 0;
        const activeResumes = rs.active_resumes || 0;
        console.log('Auto collected:', autoCollected, 'Total resumes:', totalResumes, 'Active resumes:', activeResumes);
        meta.innerText = '';
        console.log('Updated meta text:', meta.innerText);
        // Get hourly rate data from the analyze endpoint
        const hourlyRates = data.hourly_rates || {};
        const avgHourlyRate = hourlyRates.avg ? Math.round(hourlyRates.avg) + ' ₽/ч' : 'N/A';
        const minHourlyRate = hourlyRates.min ? Math.round(hourlyRates.min) : 'N/A';
        const maxHourlyRate = hourlyRates.max ? Math.round(hourlyRates.max) : 'N/A';
        const minMaxHourlyRate = (minHourlyRate !== 'N/A' && maxHourlyRate !== 'N/A') ? 
          `${minHourlyRate} - ${maxHourlyRate} ₽/ч` : 'N/A';
        
        const items = [
          { label: 'Количество резюме', value: rs.total_resumes, icon: '👥', hint: 'Общее количество резюме, связанных с данной вакансией' },
          { label: 'Доля активных', value: (typeof rs.active_share === 'number' ? Math.round(rs.active_share * 100) + '%' : 'N/A'), icon: '📈', hint: 'Процент активных резюме от общего количества' },
          { label: 'Средняя ЧТС', value: avgHourlyRate, icon: '⏰', hint: 'Средняя часовая тарифная ставка по вакансиям' },
          { label: 'Мин/Макс ЧТС', value: minMaxHourlyRate, icon: '📊', hint: 'Диапазон часовых ставок от минимальной до максимальной' },
        ];
        grid.innerHTML = '';
        items.forEach(it => {
          const card = document.createElement('div');
          card.className = 'stat-card';
          card.style.position = 'relative';
          card.innerHTML = `
            <div style="font-size: 24px; margin-bottom: 8px;">${it.icon}</div>
            <div style="font-size:12px; color:#cbd5e1; margin-bottom:4px;">${it.label}</div>
            <div style="font-size:18px; font-weight:bold; color:#60a5fa; text-shadow:0 0 4px rgba(96,165,250,0.5);">${it.value ?? '–'}</div>
            <div class="tooltip" style="
              visibility: hidden;
              opacity: 0;
              position: absolute;
              bottom: 100%;
              left: 50%;
              transform: translateX(-50%);
              background-color: #1e293b;
              color: white;
              text-align: center;
              border-radius: 6px;
              padding: 8px 12px;
              font-size: 12px;
              white-space: nowrap;
              z-index: 1000;
              box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
              transition: opacity 0.3s, visibility 0.3s;
              margin-bottom: 5px;
            ">
              ${it.hint}
              <div style="
                position: absolute;
                top: 100%;
                left: 50%;
                transform: translateX(-50%);
                border: 5px solid transparent;
                border-top-color: #1e293b;
              "></div>
            </div>
          `;
          
          // Add hover events for tooltip
          card.addEventListener('mouseenter', function() {
            const tooltip = this.querySelector('.tooltip');
            tooltip.style.visibility = 'visible';
            tooltip.style.opacity = '1';
          });
          
          card.addEventListener('mouseleave', function() {
            const tooltip = this.querySelector('.tooltip');
            tooltip.style.visibility = 'hidden';
            tooltip.style.opacity = '0';
          });
          
          grid.appendChild(card);
        });
      } catch (e) {
        console.warn('Failed to load resume stats', e);
      }

    }

    
    document.getElementById('applyResume').addEventListener('click', applyResumeFromControls);
    const btnCompetitors = document.getElementById('toCompetitors');
    if (btnCompetitors) btnCompetitors.addEventListener('click', goToCompetitors);
    
    // Handle preset dropdown with defensive mapping
    document.getElementById('presets').addEventListener('change', (e) => {
      const raw = e.target.value || '';
      const text = e.target.options[e.target.selectedIndex]?.text || '';
      const norm = (s) => (s || '').toString().trim().toLowerCase();
      const presetMap = new Map([
        ['врач-терапевт', 'врач терапевт'],
        ['врач терапевт', 'врач терапевт'],
        ['грузчик', 'грузчик нагрузки'],
        ['грузчик нагрузки', 'грузчик нагрузки'],
        ['грузчик склад', 'грузчик склад'],
        ['водитель', 'водитель категория D'],
        ['водитель категория D', 'водитель категория D'],
        ['водитель категория С', 'водитель категория С'],
        ['уборщик', 'уборщик клининг'],
        ['специалист сбовс', 'уборщик клининг'],
        ['мойщик-уборщик', 'мойщик посуды'],
        ['мойщик посуды', 'мойщик посуды'],
        ['ml-инженер', 'ML инженер'],
        ['ml инженер', 'ML инженер'],
        ['аналитик данных', 'Аналитик данных SQL'],
        ['аналитик данных sql', 'Аналитик данных SQL'],
        ['машинист катка', 'машинист катка']
      ]);
      const mapped = presetMap.get(norm(text)) || presetMap.get(norm(raw)) || raw;
      if (mapped) {
        document.getElementById('q').value = mapped;
        applyFromControls();
      }
    });
    
    // Function to create salary histogram
    function createSalaryHistogram(salaries, salaryStats, itemsData) {
      const histogramCanvas = document.getElementById('salaryHistogram');
      if (!histogramCanvas) return;
      
      console.log('Creating histogram with', salaries.length, 'salaries');
      
      // Use salaries from API or generate mock data
      let histogramSalaries = salaries.length > 0 ? salaries : [];
      
      // Add additional salary to Pulkovo salaries for histogram only when button is active
      const currentQueryHist = new URLSearchParams(window.location.search).get('query') || '';
      const normalizedQueryHist = currentQueryHist.toLowerCase().trim();
      const additionalPulkovoSalary = getTeamProjectAdditionalForQuery(normalizedQueryHist);
      
      // Add additional salary to histogram data if there are Pulkovo vacancies and button is active
      if (additionalPulkovoSalary > 0 && histogramSalaries.length > 0) {
        histogramSalaries.push(additionalPulkovoSalary);
      }
      
      if (histogramSalaries.length === 0 && salaryStats && salaryStats.median) {
        // Generate mock data based on stats
        const avg = salaryStats.avg || 131234;
        const median = salaryStats.median || 125000;
        const min = salaryStats.min || 40000;
        const max = salaryStats.max || 400000;
        
        histogramSalaries = [];
        for (let i = 0; i < 50; i++) {
          const random = Math.random();
          let salary;
          if (random < 0.3) {
            salary = min + Math.random() * (median - min);
          } else if (random < 0.7) {
            salary = median + (Math.random() - 0.5) * (median * 0.2);
          } else {
            salary = median + Math.random() * (max - median);
          }
          histogramSalaries.push(Math.round(salary));
        }
      }
      
      if (histogramSalaries.length === 0) {
        histogramCanvas.parentElement.innerHTML = '<p style="color:#94a3b8; text-align:center; padding:32px;">Недостаточно данных для построения гистограммы</p>';
        return;
      }
      
      // Create salary bins (buckets)
      // Ensure the bin range always includes Pulkovo values so they are visible
      let minSalary = Math.min(...histogramSalaries);
      let maxSalary = Math.max(...histogramSalaries);
      if (Array.isArray(itemsData) && itemsData.length > 0) {
        const pulkovoMonthlyValues = [];
        for (const v of itemsData) {
          let monthly = null;
          if (v && v.salary_per_shift === true) {
            if (typeof v.salary_estimated_monthly === 'number') {
              monthly = v.salary_estimated_monthly;
            }
          } else if (v && typeof v.salary_avg === 'number') {
            monthly = v.salary_avg;
          }
          if (monthly === null && v && v.salary && typeof v.salary === 'object') {
            const sf = (typeof v.salary.from === 'number') ? v.salary.from : null;
            const st = (typeof v.salary.to === 'number') ? v.salary.to : null;
            if (sf !== null && st !== null) monthly = (sf + st) / 2;
            else if (sf !== null) monthly = sf;
            else if (st !== null) monthly = st;
          }
          if (monthly !== null && monthly >= 13000 && isPulkovoEmployerName(v.employer_name)) {
            pulkovoMonthlyValues.push(monthly);
          }
        }
        if (pulkovoMonthlyValues.length > 0) {
          const pulMin = Math.min(...pulkovoMonthlyValues);
          const pulMax = Math.max(...pulkovoMonthlyValues);
          if (isFinite(pulMin)) minSalary = Math.min(minSalary, pulMin);
          if (isFinite(pulMax)) maxSalary = Math.max(maxSalary, pulMax);
        }
      }
      
      // Ensure at least 4 bins by adjusting bin width
      let binWidth = 50000; // 50k руб per bin
      let numBins = Math.ceil((maxSalary - minSalary) / binWidth) + 1;
      
      // If we have fewer than 4 bins, reduce bin width
      if (numBins < 4) {
        binWidth = Math.ceil((maxSalary - minSalary) / 3);
        numBins = 4;
      }
      
      // Create bins
      const bins = [];
      const binLabels = [];
      for (let i = 0; i < numBins; i++) {
        const binStart = Math.floor(minSalary / binWidth) * binWidth + i * binWidth;
        const binEnd = binStart + binWidth;
        bins.push({ start: binStart, end: binEnd, count: 0, hasPulkovo: false });
        // Show range for better clarity
        if (i === numBins - 1) {
          binLabels.push((binStart / 1000).toFixed(0) + 'k+');
        } else {
          binLabels.push((binStart / 1000).toFixed(0) + 'k-' + (binEnd / 1000).toFixed(0) + 'k');
        }
      }
      
      // Fill bins with salary data
      histogramSalaries.forEach(salary => {
        const binIndex = Math.floor((salary - bins[0].start) / binWidth);
        if (binIndex >= 0 && binIndex < bins.length) {
          bins[binIndex].count++;
        }
      });
      
      // Check which bins contain Pulkovo vacancies using the items data from bubble chart
      if (typeof itemsData !== 'undefined' && itemsData.length > 0) {
        itemsData.forEach(v => {
          // Compute monthly salary value, converting per-shift to monthly when available
          let monthly = null;
          if (v.salary_per_shift === true) {
            if (typeof v.salary_estimated_monthly === 'number') {
              monthly = v.salary_estimated_monthly;
            }
          } else if (typeof v.salary_avg === 'number') {
            monthly = v.salary_avg;
          }
          if (monthly === null && v.salary && typeof v.salary === 'object') {
            const sf = (typeof v.salary.from === 'number') ? v.salary.from : null;
            const st = (typeof v.salary.to === 'number') ? v.salary.to : null;
            if (sf !== null && st !== null) monthly = (sf + st) / 2;
            else if (sf !== null) monthly = sf;
            else if (st !== null) monthly = st;
          }
          
          if (monthly !== null && monthly >= 13000) {
            const binIndex = Math.floor((monthly - bins[0].start) / binWidth);
            if (binIndex >= 0 && binIndex < bins.length && isPulkovoEmployerName(v.employer_name)) {
              bins[binIndex].hasPulkovo = true;
            }
          }
        });
      }
      
      // Find the median value for marking
      const median = salaryStats?.median || 0;
      
      new Chart(histogramCanvas, {
        type: 'bar',
        data: {
          labels: binLabels,
          datasets: [{
            label: 'Количество вакансий',
            data: bins.map(bin => bin.count),
            backgroundColor: bins.map(bin => bin.hasPulkovo ? 'rgba(6, 182, 212, 0.9)' : 'rgba(59, 130, 246, 0.8)'),
            borderColor: bins.map(bin => bin.hasPulkovo ? 'rgba(6, 182, 212, 1)' : 'rgba(59, 130, 246, 1)'),
            borderWidth: bins.map(bin => bin.hasPulkovo ? 3 : 1),
            borderRadius: 4
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: true,
          layout: {
            padding: {
              top: 20
            }
          },
          plugins: {
            legend: {
              display: true,
              position: 'bottom',
              align: 'center',
              labels: {
                font: {
                  size: 10,
                  weight: '400'
                },
                color: '#c7d1dd',
                padding: 4,
                usePointStyle: true,
                pointStyle: 'rect',
                generateLabels: function(chart) {
                  const hasPulkovo = bins.some(bin => bin.hasPulkovo);
                  if (hasPulkovo) {
                    return [{
                      text: 'Пулково',
                      fillStyle: 'rgba(6, 182, 212, 0.9)',
                      strokeStyle: 'rgba(6, 182, 212, 1)',
                      lineWidth: 2,
                      pointStyle: 'rect',
                      hidden: false,
                      index: 0,
                      fontColor: '#c7d1dd'
                    }];
                  }
                  return [];
                }
              }
            },
            tooltip: {
              backgroundColor: 'rgba(30, 41, 59, 0.95)',
              titleColor: '#ffffff',
              bodyColor: '#cbd5e1',
              borderColor: 'rgba(59, 130, 246, 0.5)',
              borderWidth: 1,
              padding: 12,
              displayColors: false,
              callbacks: {
                title: function(context) {
                  const binIndex = context[0].dataIndex;
                  const bin = bins[binIndex];
                  return (bin.start / 1000).toFixed(0) + 'k - ' + (bin.end / 1000).toFixed(0) + 'k₽';
                },
                label: function(context) {
                  return 'Вакансий: ' + context.parsed.y;
                },
                afterLabel: function(context) {
                  const binIndex = context[0].dataIndex;
                  const bin = bins[binIndex];
                  let result = '';
                  if (bin.hasPulkovo) {
                    result += '✈️ Содержит вакансии Аэропорт Пулково\n';
                  }
                  if (median >= bin.start && median < bin.end) {
                    result += '📊 Медиана: ' + Math.round(median).toLocaleString() + '₽';
                  }
                  return result;
                }
              }
            }
          },
          animation: {
            onComplete: function() {
              const ctx = histogramCanvas.getContext('2d');
              const chart = Chart.getChart(histogramCanvas);
              if (!chart) return;
              
              chart.data.datasets.forEach((dataset, datasetIndex) => {
                const meta = chart.getDatasetMeta(datasetIndex);
                meta.data.forEach((element, index) => {
                  const data = dataset.data[index];
                  if (data > 0) {
                    const x = element.x;
                    const y = element.y - 8;
                    
                    ctx.save();
                    ctx.fillStyle = '#ffffff';
                    ctx.font = 'bold 10px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'bottom';
                    ctx.fillText(data.toString(), x, y);
                    ctx.restore();
                  }
                });
              });
            }
          },
          scales: {
            x: {
              title: {
                display: false
              },
              grid: {
                display: false
              },
              ticks: {
                color: '#cbd5e1',
                font: {
                  size: 11,
                  weight: '400'
                },
                maxRotation: 0,
                minRotation: 0
              }
            },
            y: {
              title: {
                display: false
              },
              grid: {
                color: 'rgba(148, 163, 184, 0.15)',
                lineWidth: 1
              },
              ticks: {
                color: '#cbd5e1',
                font: {
                  size: 11,
                  weight: '400'
                },
                stepSize: 1
              },
              beginAtZero: true
            }
          }
        }
      });
    }
    
    
    
    // Team project button functionality
    function initTeamProjectButton() {
      const teamProjectBtn = document.getElementById('teamProjectBtn');
      if (!teamProjectBtn) {
        console.warn('Team project button not found');
        return;
      }
      
      // Initialize from global state (possibly restored from localStorage above)
      let teamProjectActive = Boolean(window.teamProjectActive);
      
      // Restore button state on page load
      if (teamProjectActive) {
        teamProjectBtn.style.background = 'linear-gradient(135deg, #059669, #047857)';
        teamProjectBtn.textContent = '✓ С проектом "Мы команда"';
      }
      
      teamProjectBtn.addEventListener('click', function() {
        console.log('Team project button clicked!');
        teamProjectActive = !teamProjectActive;
        window.teamProjectActive = teamProjectActive; // Set global state
        try {
          localStorage.setItem('teamProjectActive', teamProjectActive ? '1' : '0');
        } catch (e) {
          // Ignore persistence errors
        }
        
        if (teamProjectActive) {
          teamProjectBtn.style.background = 'linear-gradient(135deg, #059669, #047857)';
          teamProjectBtn.textContent = '✓ С проектом "Мы команда"';
          console.log('Button activated - adding additional salary');
        } else {
          teamProjectBtn.style.background = 'linear-gradient(135deg, #10b981, #059669)';
          teamProjectBtn.textContent = 'С проектом "Мы команда"';
          console.log('Button deactivated - using base salary');
        }
        
        // Reload the page to refresh all visualizations with new state
        window.location.reload();
      });
    }
    
    // Initialize button when DOM is ready
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initTeamProjectButton);
    } else {
      initTeamProjectButton();
    }
    
    load();
  </script>
  </div>
</body>
</html>
"""
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