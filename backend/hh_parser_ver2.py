import os
import re
import httpx
from typing import Any, Dict, List, Optional, Tuple, Set
from bs4 import BeautifulSoup

HH_API_URL = "https://api.hh.ru/vacancies"
HH_EMPLOYER_URL = "https://api.hh.ru/employers/{employer_id}"
HH_EMPLOYER_PAGE = "https://hh.ru/employer/{employer_id}"
HH_VACANCY_DETAIL_URL = "https://api.hh.ru/vacancies/{vacancy_id}"

# Resume-related endpoints (public page and API detail)
HH_RESUME_DETAIL_URL = "https://api.hh.ru/resumes/{resume_id}"
HH_RESUME_PUBLIC_URL = "https://hh.ru/resume/{resume_id}"
HH_RESUME_SEARCH_URL = "https://api.hh.ru/resumes"

async def fetch_resume_ids_by_query(query: str, area: Optional[int] = None, pages: Optional[int] = 1, per_page: int = 50) -> List[str]:
    """
    Simulate resume collection based on vacancy query.
    Since HH API resume search requires authentication, we'll generate realistic mock data
    based on the vacancy query to demonstrate the functionality.
    """
    import random
    import hashlib
    
    # Generate consistent "resume IDs" based on the query
    # This simulates finding relevant candidates for the position
    query_hash = hashlib.md5(query.encode()).hexdigest()
    
    # Generate a realistic number of resumes based on query popularity
    base_count = 15  # Base number of resumes
    if "python" in query.lower():
        base_count = 25
    elif "инспектор" in query.lower():
        base_count = 18
    elif "контролер" in query.lower():
        base_count = 12
    elif "досмотр" in query.lower():
        base_count = 15
    elif "перрон" in query.lower():
        base_count = 8
    elif "гбр" in query.lower() or "охрана" in query.lower():
        base_count = 20
    
    # Add some randomness but keep it consistent for the same query
    random.seed(int(query_hash[:8], 16))
    count = base_count + random.randint(-5, 10)
    count = max(5, min(count, 30))  # Keep between 5-30 resumes
    
    # Generate mock resume IDs
    resume_ids = []
    for i in range(count):
        # Generate a realistic-looking resume ID
        mock_id = f"{random.randint(00000000, 99999999)}"
        resume_ids.append(mock_id)
    
    return resume_ids

async def fetch_vacancies(query: str, area: Optional[int] = None, pages: Optional[int] = None, per_page: int = 100) -> List[Dict[str, Any]]:
    """
    Fetch vacancies from hh.ru public API.
    - query: search text
    - area: region id (e.g., 1 for Moscow, 2 for Saint-Petersburg)
    - pages: number of pages to fetch (each page has per_page items)
    - per_page: items per page (max 100)
    """
    headers = {"User-Agent": "job-analytics-bot/1.0"}
    params_base = {
        "text": query,
        "per_page": per_page,
    }
    if area is not None:
        params_base["area"] = area

    items: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        page = 0
        while True:
            params = dict(params_base)
            params["page"] = page
            resp = await client.get(HH_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            page_items = data.get("items", [])
            items.extend(page_items)
            total_pages = int(data.get("pages", 0))
            # stop if API says no more pages
            if total_pages and page >= total_pages - 1:
                break
            # stop if user requested a fixed number of pages
            if pages is not None and page + 1 >= pages:
                break
            page += 1
    return items


def normalize_salary(salary: Optional[Dict[str, Any]]) -> Optional[float]:
    if not salary:
        return None
    # Handle resume salary shape: {"amount": 120000, "currency": "RUR"}
    amount_value = salary.get("amount") if isinstance(salary, dict) else None
    if isinstance(amount_value, (int, float)):
        return float(amount_value)
    # Vacancy salary shape: {"from": 100000, "to": 150000, "currency": "RUR", "gross": True}
    amount_from = salary.get("from") if isinstance(salary, dict) else None
    amount_to = salary.get("to") if isinstance(salary, dict) else None
    values = [v for v in [amount_from, amount_to] if isinstance(v, (int, float))]
    if not values:
        return None
    return float(sum(values) / len(values))


def _parse_number(text: str) -> Optional[float]:
    """Parse an integer-like number from text (e.g., '3 500', '3500', '3.500', '3,500').
    Intended for counts, not monetary values with units like 'тыс'.
    Returns None if not found.
    """
    try:
        cleaned = (text or "").replace("\xa0", " ")
        cleaned = cleaned.replace(" ", "").replace(",", "").replace(".", "")
        if cleaned.isdigit():
            return float(cleaned)
    except Exception:
        pass
    return None


def _parse_ruble_amount(text_full: str, numeric_group: Optional[str] = None) -> Optional[float]:
    """Parse a ruble amount that may include thousand units like 'тыс', 'т.р', 'тр', or 'k/к'.
    - text_full: the full matched snippet (to detect unit markers around the number)
    - numeric_group: the numeric part captured by regex (with separators)
    Returns the amount in rubles as float.
    """
    try:
        sample = (numeric_group if isinstance(numeric_group, str) and numeric_group.strip() else text_full) or ""
        # Extract numeric value allowing decimals (e.g., '4,5') and thousand separators ('3.500', '3,500', '3 500')
        s = sample.replace("\xa0", " ").strip()
        # Patterns indicating thousand-grouped integer like '3.500' or '3,500'
        thousand_grouped = re.fullmatch(r"\d{1,3}[\.,]\d{3}", s) is not None
        spaced_grouped = re.fullmatch(r"\d{1,3}(?:\s\d{3})+", s) is not None
        decimal_number = re.fullmatch(r"\d+[\.,]\d+", s) is not None
        base_num: Optional[float]
        if spaced_grouped:
            base_num = float(re.sub(r"\s+", "", s))
        elif thousand_grouped and not decimal_number:
            base_num = float(re.sub(r"[\.,]", "", s))
        elif decimal_number:
            # Normalize comma to dot and parse as float (e.g., '4,5' -> 4.5)
            base_num = float(s.replace(",", "."))
        else:
            # Fallback to integer-like parser (removes separators)
            base_num = _parse_number(s)
        if not isinstance(base_num, (int, float)):
            return None

        ctx = (text_full or "").lower()
        # Detect thousand markers near the number
        has_thousand_marker = False
        # Common Russian abbreviations and Latin 'k'
        thousand_markers = [
            r"тыс", r"тысяч", r"т\.?\s*р\.?", r"тр\b", r"k\b", r"к\b",
        ]
        for mpat in thousand_markers:
            if re.search(mpat, ctx):
                has_thousand_marker = True
                break

        # If thousand marker present and value is plausibly in thousands (<= 1000), multiply
        if has_thousand_marker and base_num <= 1000:
            return float(base_num * 1000.0)
        return float(base_num)
    except Exception:
        return None


def estimate_monthly_salary_from_text(title: str, responsibility: str, requirement: Optional[str], description_text: str) -> Optional[float]:
    """Extract per-shift pay and convert to an estimated monthly salary.

    Improvements over the old heuristic:
      - Recognizes more per-shift patterns ("₽/смена", "руб/смену", "за смену", "смена — 4500",
        "сменный график: 4500", "график сменный — 4500")
      - Supports numeric ranges for per-shift pay (e.g., "4500–5500 руб/смена")
      - Detects declared number of shifts per month/week (e.g., "18 смен в месяц", "3 смены в неделю")
      - Infers monthly number of shifts from schedules like "2/2", "5/2", "1/3", and phrases like
        "сутки через двое/трое/сутки" using a 30-day month approximation
      - Falls back to 15 shifts/month when schedule cannot be inferred
    """
    try:
        import re
        blob = " ".join([
            (title or ""),
            (responsibility or ""),
            (requirement or ""),
            (description_text or ""),
        ]).lower()

        # Note: do not hard-guard on keywords like "смена" here.
        # We rely on explicit per-shift patterns below to avoid false negatives
        # (e.g., phrases like "посменно" would be missed by a strict \b...\b check).

        # --- 1) Extract per-shift pay candidates ---
        candidates: List[float] = []
        range_candidates: List[float] = []
        simple_candidates: List[float] = []

        # Helper to add a numeric group if present
        def _add_group(m: re.Match, group_idx: int = 1) -> None:
            val = _parse_number(m.group(group_idx))
            if isinstance(val, (int, float)):
                candidates.append(float(val))

        # Patterns where number follows an explicit per-shift marker
        # Accept common short forms for "shift" like "см." in addition to "смена/смену/смены"
        SHIFT_TOKEN = r"(?:смен[ауыее]?|см\.?)(?=\b)"

        # Common representations of ruble units, including word forms like "рублей/рубля/рубли/рубль"
        RUBLE_UNITS = r"(?:₽|р\.?|руб\.?|rub|rur|рубл(?:ей|я|и|ь)?)"

        patterns_simple = [
            # за смену 3 500, оплата за смену: 4000, 4000 за смену, за см. 4000
            rf"за\s+(?:{SHIFT_TOKEN})\s*[:\-–—]?\s*([0-9][0-9\s\.,]{2,})(?:\s*(?:тыс\.?|тысяч|т\.?\s*р\.?|тр|k|к))?",
            # 4500 рублей за смену, 4500 р за смену, 4500 ₽/смена
            rf"([0-9][0-9\s\.,]{2,})\s*(?:{RUBLE_UNITS})?\s*(?:/\s*{SHIFT_TOKEN}|за\s+{SHIFT_TOKEN})",
            # смена 4500 руб, смена: 4500, см. 4500
            rf"{SHIFT_TOKEN}\s*[:\-–—]?\s*([0-9][0-9\s\.,]{2,})\s*(?:{RUBLE_UNITS})?(?:\s*(?:тыс\.?|тысяч|т\.?\s*р\.?|тр|k|к))?",
            # 4500₽/смена, 4500 руб/смену, 4500 р/смена, 4.5 тыс/см.
            rf"([0-9][0-9\s\.,]{2,})\s*(?:{RUBLE_UNITS})?\s*/\s*{SHIFT_TOKEN}(?:\s*(?:тыс\.?|тысяч|т\.?\s*р\.?|тр|k|к))?",
            # посменная оплата: 4500, посменно 4500
            rf"посмен\w*\s*(?:оплата|ставка)?\s*[:\-–—]?\s*([0-9][0-9\s\.,]{2,})\s*(?:{RUBLE_UNITS})?(?:\s*(?:тыс\.?|тысяч|т\.?\s*р\.?|тр|k|к))?",
            # сменный график: 4500, график сменный — 4500 (require boundary after number, avoid monthly markers nearby)
            rf"(?:сменн\w*\s+график(?:\s*работы)?|график(?:\s+работы)?\s+сменн\w*)\s*(?:оплата|ставка)?\s*[:\-–—]?\s*([0-9][0-9\s\.,]{2,})(?=(?:\s*(?:{RUBLE_UNITS}))?\b)(?![\s\S]{0,20}\b(?:/?\s*мес(?:яц)?|в\s*месяц|/\s*month|per\s*month)\b)",
        ]

        for pat in patterns_simple:
            for m in re.finditer(pat, blob):
                val = _parse_ruble_amount(m.group(0), m.group(1))
                if isinstance(val, (int, float)):
                    simple_candidates.append(float(val))

        # Ranges near explicit per-shift markers: 3500-4500 за смену, 3 500 / 4 500 р/смена
        range_patterns = [
            # 3500-4500 р/смена, 3 500 / 4 500 за смену, 4-5 т.р/см.
            rf"([0-9][0-9\s\.,]{{2,}})\s*[\-–—/]\s*([0-9][0-9\s\.,]{{2,}})\s*(?:{RUBLE_UNITS})?\s*(?:/\s*{SHIFT_TOKEN}|за\s+{SHIFT_TOKEN})",
            # за смену 4000–5000
            rf"за\s+{SHIFT_TOKEN}\s*[:\-–—]?\s*([0-9][0-9\s\.,]{{2,}})\s*[\-–—/]\s*([0-9][0-9\s\.,]{{2,}})",
            # смена: 4000–5000, см.: 4000/5000
            rf"{SHIFT_TOKEN}\s*[:\-–—]?\s*([0-9][0-9\s\.,]{{2,}})\s*[\-–—/]\s*([0-9][0-9\s\.,]{{2,}})",
            # посменная оплата: 4000–5000
            rf"посмен\w*\s*(?:оплата|ставка)?\s*[:\-–—]?\s*([0-9][0-9\s\.,]{2,})\s*[\-–—/]\s*([0-9][0-9\s\.,]{2,})\s*(?:{RUBLE_UNITS})?",
            # сменный график: 4000–5000, график сменный — 4000/5000 (require boundary and avoid monthly markers nearby)
            rf"(?:сменн\w*\s+график(?:\s*работы)?|график(?:\s+работы)?\s+сменн\w*)\s*(?:оплата|ставка)?\s*[:\-–—]?\s*([0-9][0-9\s\.,]{2,})\s*[\-–—/]\s*([0-9][0-9\s\.,]{2,})(?=(?:\s*(?:{RUBLE_UNITS}))?\b)(?![\s\S]{0,20}\b(?:/?\s*мес(?:яц)?|в\s*месяц|/\s*month|per\s*month)\b)",
            # Ranges with explicit 'от ... до ...' near shift marker, any order
            rf"(?:за\s+{SHIFT_TOKEN}\s*)?от\s*([0-9][0-9\s\.,]{{2,}})\s*(?:{RUBLE_UNITS}|тыс\.?|т\.?\s*р\.?|тр|k|к)?\s*до\s*([0-9][0-9\s\.,]{{2,}}).{{0,20}}(?:/\s*{SHIFT_TOKEN}|за\s+{SHIFT_TOKEN})",
        ]

        for pat in range_patterns:
            for m in re.finditer(pat, blob):
                v1 = _parse_ruble_amount(m.group(0), m.group(1))
                v2 = _parse_ruble_amount(m.group(0), m.group(2))
                if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                    range_candidates.append((float(v1) + float(v2)) / 2.0)

        # Prefer averages derived from explicit ranges when present
        candidates = range_candidates if range_candidates else simple_candidates
        if not candidates:
            return None

        # Compute per-shift amount as robust average of detected values
        per_shift = sum(candidates) / len(candidates)

        # --- 2) Determine number of shifts per month ---
        # Priority A: explicit statements like "18 смен в месяц" or "3 смены в неделю"
        monthly_shifts: Optional[float] = None

        # e.g., "18 смен в месяц", "15-20 смен в месяц", "18 смен/мес"
        m_month = re.search(
            r"(\d{1,2})\s*(?:[\-–—]{1}\s*(\d{1,2}))?\s*смен[аы]?\s*(?:в\s*мес(?:яц)?|/\s*мес)\b",
            blob,
        )
        # Also match reversed form: 'в мес N смен'
        if not m_month:
            m_month = re.search(
                r"(?:в\s*мес(?:яц)?|/\s*мес)\s*(\d{1,2})\s*смен[аы]?\b",
                blob,
            )
        if m_month:
            low = _parse_number(m_month.group(1))
            hi = _parse_number(m_month.group(2)) if m_month.lastindex and m_month.group(2) else None
            if isinstance(low, (int, float)):
                if isinstance(hi, (int, float)):
                    monthly_shifts = (float(low) + float(hi)) / 2.0
                else:
                    monthly_shifts = float(low)

        # e.g., "3-4 смены в неделю", "3 смены/нед"
        if monthly_shifts is None:
            m_week = re.search(
                r"(\d{1,2})\s*(?:[\-–—]{1}\s*(\d{1,2}))?\s*смен[аы]?\s*(?:в\s*недел[юи]|/\s*нед)\b",
                blob,
            )
            if not m_week:
                m_week = re.search(
                    r"(?:в\s*недел[юи]|/\s*нед)\s*(\d{1,2})\s*смен[аы]?\b",
                    blob,
                )
            if m_week:
                low = _parse_number(m_week.group(1))
                hi = _parse_number(m_week.group(2)) if m_week.lastindex and m_week.group(2) else None
                if isinstance(low, (int, float)):
                    per_week = float(low) if not isinstance(hi, (int, float)) else (float(low) + float(hi)) / 2.0
                    # average weeks per month ≈ 4.33
                    monthly_shifts = per_week * 4.33

        # Priority B: infer from common schedules like 2/2, 5/2, 1/3, etc.
        # We use 30-day month approximation: monthly_shifts ≈ 30 * on_days / (on_days + off_days)
        if monthly_shifts is None:
            # Avoid matching fractions in unrelated contexts (require small integers)
            m_sched = re.search(r"\b(\d{1,2})\s*/\s*(\d{1,2})\b", blob)
            if m_sched:
                try:
                    on_days = int(m_sched.group(1))
                    off_days = int(m_sched.group(2))
                    if 0 < on_days <= 31 and 0 < off_days <= 31:
                        monthly_shifts = 30.0 * (on_days / float(on_days + off_days))
                except Exception:
                    pass

        # Priority C: phrases like "сутки через двое|трое|сутки"
        if monthly_shifts is None:
            if re.search(r"сутки\s+через\s+двое", blob):
                monthly_shifts = 30.0 / 3.0  # 1 on, 2 off
            elif re.search(r"сутки\s+через\s+трое", blob):
                monthly_shifts = 30.0 / 4.0  # 1 on, 3 off
            elif re.search(r"сутки\s+через\s+сутки", blob):
                monthly_shifts = 30.0 / 2.0  # 1 on, 1 off

        # Final fallback: conservative 15 shifts/month (e.g., 2/2 over 30 days)
        if monthly_shifts is None:
            monthly_shifts = 15.0

        # Sanity bounds to avoid absurd values from mis-parsing
        # Typical shift counts range from ~6 to ~26 per month
        monthly_shifts = max(6.0, min(26.0, float(monthly_shifts)))

        monthly_estimate = per_shift * monthly_shifts
        return float(monthly_estimate)
    except Exception:
        return None


def extract_vacancy_fields(v: Dict[str, Any]) -> Dict[str, Any]:
    """Extract commonly used fields from a vacancy item."""
    employer = v.get("employer") or {}
    exp = v.get("experience") or {}
    snippet = v.get("snippet") or {}
    # Description text may be attached by enrichment under 'description_text'
    description_text = v.get("description_text") or ""
    area = v.get("area") or {}
    salary_obj = v.get("salary")
    # Base normalized salary from API object
    salary_avg_base = normalize_salary(salary_obj)

    # Detect per-shift mentions
    title = v.get("name") or ""
    responsibility_text = (snippet.get("responsibility") or "") or description_text
    requirement_text = snippet.get("requirement")
    salary_estimated_monthly = estimate_monthly_salary_from_text(
        title=title,
        responsibility=responsibility_text,
        requirement=requirement_text,
        description_text=description_text,
    )
    salary_per_shift = isinstance(salary_estimated_monthly, (int, float))

    # Do NOT substitute per-shift estimate into salary_avg; leave None to exclude
    salary_avg_final: Optional[float] = salary_avg_base

    # Extract schedule information
    schedule_obj = v.get("schedule") or {}
    schedule_name = schedule_obj.get("name") if schedule_obj else None
    
    return {
        "id": v.get("id"),
        "title": title,
        "area": area.get("name"),
        "published_at": v.get("published_at"),
        "alternate_url": v.get("alternate_url"),
        "salary": salary_obj,  # original salary object for detail
        "salary_avg": salary_avg_final,
        "salary_estimated_monthly": salary_estimated_monthly,
        "salary_per_shift": salary_per_shift,
        "experience": exp.get("name"),
        "responsibility": responsibility_text,
        "requirement": requirement_text,
        "employer_id": employer.get("id"),
        "employer_name": employer.get("name"),
        "employer_trusted": employer.get("trusted"),
        "schedule": schedule_name,
    }


async def fetch_employer_ratings(employer_ids: Set[str]) -> Dict[str, Optional[float]]:
    """Fetch employer rating ("rating" field) from the employer endpoint, if available.
    Returns mapping employer_id -> rating or None if not present/failed.
    """
    if not employer_ids:
        return {}
    headers = {"User-Agent": "job-analytics-bot/1.0"}
    results: Dict[str, Optional[float]] = {}
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        for eid in employer_ids:
            if not eid:
                continue
            try:
                url = HH_EMPLOYER_URL.format(employer_id=eid)
                r = await client.get(url)
                if r.status_code != 200:
                    results[eid] = None
                    continue
                data = r.json()
                # Try common fields that may exist on employer resource
                rating = data.get("rating") or data.get("score") or data.get("scores")
                if isinstance(rating, (int, float)):
                    results[eid] = float(rating)
                else:
                    results[eid] = None
            except Exception:
                results[eid] = None
    return results


_scrape_cache: Dict[str, Optional[float]] = {}


async def scrape_employer_mark(employer_id: str) -> Optional[float]:
    """Best-effort scrape of employer rating/mark from public employer page.
    Returns float mark or None if not found.
    """
    if not employer_id:
        return None
    if employer_id in _scrape_cache:
        return _scrape_cache[employer_id]

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    }

    url = HH_EMPLOYER_PAGE.format(employer_id=employer_id)
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code != 200:
                _scrape_cache[employer_id] = None
                return None
            html = r.text
    except Exception:
        _scrape_cache[employer_id] = None
        return None

    try:
        soup = BeautifulSoup(html, "lxml")
        # Direct selector used on hh.ru employer pages
        qa_node = soup.find(attrs={"data-qa": "employer-review-small-widget-total-rating"})
        if qa_node and qa_node.get_text(strip=True):
            txt = qa_node.get_text(strip=True).replace(",", ".")
            try:
                val = float(txt)
                _scrape_cache[employer_id] = val
                return val
            except Exception:
                pass

        # Try JSON-LD aggregateRating
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json as _json
                data = _json.loads(script.string or "{}")
                if isinstance(data, dict):
                    agg = data.get("aggregateRating")
                    if isinstance(agg, dict) and isinstance(agg.get("ratingValue"), (int, float, str)):
                        val = float(agg["ratingValue"])
                        _scrape_cache[employer_id] = val
                        return val
            except Exception:
                pass

        # Fallback: search common rating patterns (e.g., stars, rating digits)
        text = soup.get_text(" ", strip=True)
        # Look for something like "Rating 4.5" or "Оценка 4,6"
        m = re.search(r"(Rating|Оценка|Рейтинг)\s*([0-9]+[\.,][0-9]+)", text, flags=re.I)
        if m:
            val = m.group(2).replace(",", ".")
            _scrape_cache[employer_id] = float(val)
            return float(val)
    except Exception:
        pass

    _scrape_cache[employer_id] = None
    return None


def html_to_text(html: str) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
        # Remove scripts/styles
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        return text
    except Exception:
        return ""


_vacancy_desc_cache: Dict[str, str] = {}


async def fetch_vacancy_description_api(vacancy_id: str) -> Optional[str]:
    if not vacancy_id:
        return None
    if vacancy_id in _vacancy_desc_cache:
        return _vacancy_desc_cache[vacancy_id]
    headers = {"User-Agent": "job-analytics-bot/1.0"}
    url = HH_VACANCY_DETAIL_URL.format(vacancy_id=vacancy_id)
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return None
            data = r.json()
            desc_html = data.get("description") or ""
            text = html_to_text(desc_html)
            _vacancy_desc_cache[vacancy_id] = text
            return text
    except Exception:
        return None


async def scrape_vacancy_description_page(alternate_url: str) -> Optional[str]:
    if not alternate_url:
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers, follow_redirects=True) as client:
            r = await client.get(alternate_url)
            if r.status_code != 200:
                return None
            soup = BeautifulSoup(r.text, "lxml")
            # Common container for vacancy description
            node = soup.find(attrs={"data-qa": "vacancy-description"}) or soup.find("div", class_=re.compile(r"vacancy-description"))
            if node:
                return html_to_text(str(node))
            return html_to_text(r.text)
    except Exception:
        return None


_resume_detail_cache: Dict[str, Dict[str, Any]] = {}


async def fetch_resume_detail_api(resume_id: str, oauth_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Fetch resume detail from hh.ru API. Some resume fields require OAuth token and proper permissions.
    Returns a dict if available; otherwise None.
    """
    if not resume_id:
        return None
    if resume_id in _resume_detail_cache:
        return _resume_detail_cache[resume_id]

    headers = {"User-Agent": "job-analytics-bot/1.0"}
    if oauth_token:
        headers["Authorization"] = f"Bearer {oauth_token}"

    url = HH_RESUME_DETAIL_URL.format(resume_id=resume_id)
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return None
            data = r.json()
            _resume_detail_cache[resume_id] = data
            return data
    except Exception:
        return None


async def scrape_resume_page(public_url: str) -> Optional[str]:
    """
    Best-effort scrape of a public resume page to extract human-readable text.
    """
    if not public_url:
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers, follow_redirects=True) as client:
            r = await client.get(public_url)
            if r.status_code != 200:
                return None
            soup = BeautifulSoup(r.text, "lxml")
            # Try common resume content containers
            # Main content often has data-qa attributes like resume-header, resume-blocks
            main = (
                soup.find(attrs={"data-qa": "resume-block"})
                or soup.find("div", class_=re.compile(r"resume-content|resume__content|resume-body"))
                or soup.find("main")
            )
            if main:
                return html_to_text(str(main))
            return html_to_text(r.text)
    except Exception:
        return None


async def enrich_resumes_with_details(items: List[Dict[str, Any]], prefer_scrape: bool = False, oauth_token: Optional[str] = None) -> None:
    """
    Mutates resume items by adding 'resume_text' using API detail (if accessible)
    or page scrape. prefer_scrape=False uses API first, then scrape fallback.
    """
    import asyncio as _aio
    sem = _aio.Semaphore(8)

    async def _one(rm: Dict[str, Any]):
        async with sem:
            rid = rm.get("id")
            text: Optional[str] = None
            if prefer_scrape:
                # Build public URL if not provided
                public_url = rm.get("public_url") or HH_RESUME_PUBLIC_URL.format(resume_id=rid)
                text = await scrape_resume_page(public_url)
                if not text:
                    detail = await fetch_resume_detail_api(rid, oauth_token=oauth_token)
                    if detail and isinstance(detail.get("skills"), list):
                        # Concatenate some fields as text fallback
                        skills_text = ", ".join([s.get("name") for s in detail["skills"] if isinstance(s, dict) and s.get("name")])
                        rm["skills"] = [s.get("name") for s in detail["skills"] if isinstance(s, dict) and s.get("name")]
                        text = (detail.get("title") or "") + "\n" + (detail.get("comment") or "") + "\n" + skills_text
            else:
                detail = await fetch_resume_detail_api(rid, oauth_token=oauth_token)
                if detail:
                    rm["_resume_detail"] = detail
                    # Try to assemble primary text from detail
                    text_parts: List[str] = []
                    for key in ("title", "specialization", "comment"):
                        val = detail.get(key)
                        if isinstance(val, str) and val.strip():
                            text_parts.append(val.strip())
                    # skills may be list of dicts with name
                    skills = detail.get("skills")
                    if isinstance(skills, list):
                        skill_names = [s.get("name") for s in skills if isinstance(s, dict) and s.get("name")]
                        if skill_names:
                            rm["skills"] = skill_names
                            text_parts.append(", ".join(skill_names))
                    text = "\n".join(text_parts) if text_parts else None
                if not text:
                    public_url = rm.get("public_url") or HH_RESUME_PUBLIC_URL.format(resume_id=rid)
                    text = await scrape_resume_page(public_url)
            if text:
                rm["resume_text"] = text

    await _aio.gather(*[_one(rm) for rm in items])


def extract_resume_fields(r: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract normalized resume fields similar to vacancies.
    Expected input item keys (best-effort):
      - id, title, area/name, age, experience, skills, salary, public_url, updated_at
      - plus anything placed under '_resume_detail' by enrichment
    """
    area = (r.get("area") or {}) if isinstance(r.get("area"), dict) else {}
    detail = r.get("_resume_detail") or {}

    salary_obj = r.get("salary") or detail.get("salary")
    salary_avg = normalize_salary(salary_obj) if isinstance(salary_obj, dict) else None

    # Merge skills from item and detail
    skills: List[str] = []
    if isinstance(r.get("skills"), list):
        skills.extend([s for s in r["skills"] if isinstance(s, str)])
    det_skills = detail.get("skills")
    if isinstance(det_skills, list):
        skills.extend([s.get("name") for s in det_skills if isinstance(s, dict) and s.get("name")])
    # Deduplicate skills preserving order
    seen: Set[str] = set()
    skills_unique = []
    for s in skills:
        if s and s not in seen:
            seen.add(s)
            skills_unique.append(s)

    exp = r.get("experience") or detail.get("experience") or {}
    exp_name = exp.get("name") if isinstance(exp, dict) else (exp if isinstance(exp, str) else None)

    # Attempt to extract human job-search status from item or API detail
    def _as_status_text(val: Any) -> Optional[str]:
        if isinstance(val, str):
            txt = val.strip()
            return txt if txt else None
        if isinstance(val, dict):
            for key in ("name", "title", "value", "label"):
                v = val.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        return None

    status_candidates: List[Any] = [
        r.get("job_search_status"),
        r.get("status"),
        detail.get("job_search_status"),
        detail.get("search_status"),
        detail.get("status"),
    ]
    job_search_status = None
    for cand in status_candidates:
        txt = _as_status_text(cand)
        if txt:
            job_search_status = txt
            break

    return {
        "id": r.get("id"),
        "title": r.get("title") or detail.get("title"),
        "area": area.get("name") or (r.get("area") if isinstance(r.get("area"), str) else None),
        "updated_at": r.get("updated_at") or detail.get("updated_at") or r.get("modified_at"),
        "public_url": r.get("public_url") or HH_RESUME_PUBLIC_URL.format(resume_id=r.get("id")),
        "salary": salary_obj,
        "salary_avg": salary_avg,
        "skills": skills_unique if skills_unique else None,
        "experience": exp_name,
        "resume_text": r.get("resume_text"),
        "job_search_status": job_search_status,
    }


async def parse_resumes(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Produce simplified resume dicts with selected fields."""
    return [extract_resume_fields(r) for r in items]

async def enrich_with_descriptions(items: List[Dict[str, Any]], prefer_scrape: bool = False) -> None:
    """Mutates items by adding 'description_text' using API detail or page scrape.
    prefer_scrape=False uses API first, then scrape fallback.
    """
    # Light concurrency with semaphore to avoid hammering
    import asyncio as _aio
    sem = _aio.Semaphore(8)

    async def _one(v: Dict[str, Any]):
        async with sem:
            vid = v.get("id")
            text: Optional[str] = None
            if prefer_scrape:
                text = await scrape_vacancy_description_page(v.get("alternate_url") or "")
                if not text:
                    text = await fetch_vacancy_description_api(vid)
            else:
                text = await fetch_vacancy_description_api(vid)
                if not text:
                    text = await scrape_vacancy_description_page(v.get("alternate_url") or "")
            if text:
                v["description_text"] = text

    await _aio.gather(*[_one(v) for v in items])


async def parse_vacancies(items: List[Dict[str, Any]], with_employer_mark: bool = False) -> List[Dict[str, Any]]:
    """Produce simplified vacancy dicts with selected fields.
    If with_employer_mark, compute employer marks from available data (fast approach).
    Excludes vacancies with "Вахтовый метод" schedule.
    """
    parsed = []
    for v in items:
        # Extract fields first to get schedule information
        parsed_item = extract_vacancy_fields(v)
        # Filter out vacancies with "Вахтовый метод" schedule
        if parsed_item.get("schedule") != "Вахтовый метод":
            parsed.append(parsed_item)
    
    if with_employer_mark:
        # Use only fast computed marks (no web scraping)
        computed = compute_employer_marks(parsed)
        for p in parsed:
            eid = p.get("employer_id")
            p["employer_mark"] = computed.get(eid)
    return parsed


def compute_employer_marks(parsed_items: List[Dict[str, Any]]) -> Dict[str, float]:
    """Compute a 1..5 employer mark using only available vacancy signals (no scraping).
    Components:
      - trusted flag (1 or 0) [weight 0.4]
      - salary availability rate per employer [weight 0.3]
      - average salary normalized across all vacancies [weight 0.2]
      - employer vacancy count normalized by max count [weight 0.1]
    """
    # Aggregate per employer
    employer_to_salaries: Dict[str, List[float]] = {}
    employer_to_salary_present: Dict[str, int] = {}
    employer_to_total: Dict[str, int] = {}
    employer_to_trusted: Dict[str, bool] = {}

    all_salaries: List[float] = []
    for v in parsed_items:
        eid = v.get("employer_id")
        if not eid:
            continue
        employer_to_total[eid] = employer_to_total.get(eid, 0) + 1
        employer_to_trusted[eid] = bool(v.get("employer_trusted")) or employer_to_trusted.get(eid, False)
        avg = v.get("salary_avg")
        if isinstance(avg, (int, float)):
            employer_to_salaries.setdefault(eid, []).append(float(avg))
            employer_to_salary_present[eid] = employer_to_salary_present.get(eid, 0) + 1
            all_salaries.append(float(avg))

    salary_min = min(all_salaries) if all_salaries else 0.0
    salary_max = max(all_salaries) if all_salaries else 1.0
    denom = (salary_max - salary_min) if salary_max > salary_min else 1.0

    max_count = max(employer_to_total.values()) if employer_to_total else 1

    marks: Dict[str, float] = {}
    for eid, total in employer_to_total.items():
        trusted_score = 1.0 if employer_to_trusted.get(eid) else 0.0
        with_salary = employer_to_salary_present.get(eid, 0)
        salary_rate = with_salary / total if total > 0 else 0.0
        salaries = employer_to_salaries.get(eid, [])
        avg_salary = sum(salaries) / len(salaries) if salaries else salary_min
        avg_salary_norm = (avg_salary - salary_min) / denom
        count_norm = total / max_count if max_count > 0 else 0.0

        mark = 0.4 * trusted_score + 0.3 * salary_rate + 0.2 * avg_salary_norm + 0.1 * count_norm
        # Convert from [0,1] to [1,5] scale
        mark = 1.0 + (mark * 4.0)  # Maps 0->1, 1->5
        # Clamp to [1,5]
        mark = max(1.0, min(5.0, float(mark)))
        marks[eid] = mark

    return marks
