from typing import Any, Dict, List, Optional, Tuple
import math
from collections import Counter

try:
    from .hh_parser_ver2 import normalize_salary
except Exception:
    from hh_parser_ver2 import normalize_salary


def salary_stats(vacancies: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    # Prefer already computed monthly averages if available, then fall back to API salary.
    # If vacancy is per-shift and has an estimated monthly, include that to avoid losing data.
    raw: List[Optional[float]] = []
    for v in vacancies:
        if v.get("salary_per_shift"):
            est = v.get("salary_estimated_monthly")
            raw.append(est if isinstance(est, (int, float)) else None)
            continue
        val = v.get("salary_avg")
        if val is None:
            val = normalize_salary(v.get("salary"))
        raw.append(val if isinstance(val, (int, float)) else None)
    # Filter out invalid/likely per-shift small values (< 13 000₽)
    MIN_VALID_MONTHLY = 13000.0
    salaries = [s for s in raw if s is not None and float(s) >= MIN_VALID_MONTHLY]
    if not salaries:
        return {"count": 0, "avg": None, "median": None, "min": None, "max": None}
    salaries.sort()

    # Remove extreme high outliers so single huge values don't skew stats.
    # Primary rule: Tukey IQR fence (Q3 + 1.5*IQR) when we have enough data.
    # Fallback: if too few values for IQR, drop a single max if it is
    # disproportionately larger than median.
    def percentile(sorted_arr: List[float], p: float) -> float:
        if not sorted_arr:
            return float('nan')
        idx = (len(sorted_arr) - 1) * p
        lo = math.floor(idx)
        hi = math.ceil(idx)
        if lo == hi:
            return float(sorted_arr[lo])
        frac = idx - lo
        return float(sorted_arr[lo]) * (1 - frac) + float(sorted_arr[hi]) * frac

    n = len(salaries)
    filtered = salaries
    if n >= 4:
        q1 = percentile(salaries, 0.25)
        q3 = percentile(salaries, 0.75)
        iqr = q3 - q1
        if iqr > 0:
            high_cut = q3 + 1.5 * iqr
            filtered = [s for s in salaries if s <= high_cut]
            # Ensure we don't drop everything; keep at least 3 values if possible
            if len(filtered) < 3 and n >= 3:
                filtered = salaries[:-1] if n > 1 else salaries
    else:
        # For very small samples (n < 4), remove the max if it is a clear outlier
        # relative to the median (more than 2x median).
        med_small = salaries[n // 2] if n % 2 == 1 else (salaries[n // 2 - 1] + salaries[n // 2]) / 2
        if n >= 2 and salaries[-1] > 2 * med_small:
            filtered = salaries[:-1]

    if not filtered:
        filtered = salaries

    n = len(filtered)
    avg = sum(filtered) / n
    median = filtered[n // 2] if n % 2 == 1 else (filtered[n // 2 - 1] + filtered[n // 2]) / 2
    return {
        "count": n,
        "avg": round(avg, 2),
        "median": round(median, 2),
        "min": round(filtered[0], 2),
        "max": round(filtered[-1], 2),
    }


def hourly_rate_stats(vacancies: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """
    Calculate hourly rate statistics (ЧТС - Часовая Тарифная Ставка).
    Formula: ЗП ÷ 164 (average working hours per month)
    Only includes positions with both salary and schedule information.
    """
    # Average working hours per month (164 hours)
    HOURS_PER_MONTH = 164.0
    
    hourly_rates: List[float] = []
    for v in vacancies:
        # Skip per-shift flagged vacancies
        if v.get("salary_per_shift"):
            continue
            
        # Get salary
        salary = v.get("salary_avg")
        if salary is None:
            salary = normalize_salary(v.get("salary"))
        
        # Check if we have valid salary
        if salary is None or not isinstance(salary, (int, float)) or salary < 10000:
            continue
            
        # Check if schedule is specified (we assume if schedule exists, it's a regular position)
        schedule = v.get("schedule")
        if not schedule:
            continue
            
        # Calculate hourly rate
        hourly_rate = float(salary) / HOURS_PER_MONTH
        hourly_rates.append(hourly_rate)
    
    if not hourly_rates:
        return {"count": 0, "avg": None, "median": None, "min": None, "max": None}
    
    hourly_rates.sort()
    n = len(hourly_rates)
    avg = sum(hourly_rates) / n
    median = hourly_rates[n // 2] if n % 2 == 1 else (hourly_rates[n // 2 - 1] + hourly_rates[n // 2]) / 2
    
    return {
        "count": n,
        "avg": round(avg, 2),
        "median": round(median, 2),
        "min": round(hourly_rates[0], 2),
        "max": round(hourly_rates[-1], 2),
    }


def top_skills(vacancies: List[Dict[str, Any]], top_n: int = 20) -> List[Tuple[str, int]]:
    # skills from key_skills or parse from description if available
    counter: Counter[str] = Counter()
    for v in vacancies:
        skills = v.get("key_skills") or []
        for s in skills:
            name = s.get("name") if isinstance(s, dict) else str(s)
            if name:
                counter[name.strip().lower()] += 1
    return counter.most_common(top_n)
