"""
Parser for calculating ЧТС (Hourly Rate) for specific companies' vacancies.
ЧТС = Monthly Salary / Working Hours per Month (according to production calendar)

Uses employer IDs to fetch all vacancies directly from company pages.
"""

import asyncio
import httpx
from typing import List, Dict, Any, Optional
import json
from datetime import datetime
import re

# Import existing functions from hh_parser_ver2
from hh_parser_ver2 import normalize_salary

# Employer IDs for target companies
EMPLOYER_IDS = {
    "Аэропорт Пулково": "666661",
    "Авиакомпания Россия": "125493", 
    "Петербургский Метрополитен": "218800",
    "Ozon": "2180",
    "Теремок - Русские Блины": "53742"
}

# Working hours per month according to Russian production calendar (2024)
WORKING_HOURS_PER_MONTH = {
    1: 136,   # January
    2: 159,   # February  
    3: 168,   # March
    4: 168,   # April
    5: 159,   # May
    6: 168,   # June
    7: 176,   # July
    8: 176,   # August
    9: 168,   # September
    10: 176,  # October
    11: 168,  # November
    12: 176   # December
}

def get_working_hours_for_month(month: int) -> int:
    """Get working hours for a specific month according to production calendar."""
    return WORKING_HOURS_PER_MONTH.get(month, 168)  # Default to 168 if month not found

def extract_salary_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Extract salary information from job description or title."""
    if not text:
        return None
    
    # Common salary patterns in Russian job postings
    salary_patterns = [
        r'от\s+(\d+[\s\d]*)\s*руб',  # "от 50000 руб"
        r'до\s+(\d+[\s\d]*)\s*руб',  # "до 80000 руб"
        r'(\d+[\s\d]*)\s*-\s*(\d+[\s\d]*)\s*руб',  # "50000 - 80000 руб"
        r'(\d+[\s\d]*)\s*руб',  # "60000 руб"
        r'от\s+(\d+[\s\d]*)\s*₽',  # "от 50000 ₽"
        r'до\s+(\d+[\s\d]*)\s*₽',  # "до 80000 ₽"
        r'(\d+[\s\d]*)\s*-\s*(\d+[\s\d]*)\s*₽',  # "50000 - 80000 ₽"
        r'(\d+[\s\d]*)\s*₽',  # "60000 ₽"
    ]
    
    for pattern in salary_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            if len(matches[0]) == 2:  # Range: "50000 - 80000"
                try:
                    min_salary = int(matches[0][0].replace(' ', ''))
                    max_salary = int(matches[0][1].replace(' ', ''))
                    return {
                        'min': min_salary,
                        'max': max_salary,
                        'type': 'range'
                    }
                except ValueError:
                    continue
            else:  # Single value: "от 50000" or "до 80000" or "60000"
                try:
                    salary = int(matches[0].replace(' ', ''))
                    if 'от' in text.lower():
                        return {'min': salary, 'type': 'from'}
                    elif 'до' in text.lower():
                        return {'max': salary, 'type': 'to'}
                    else:
                        return {'exact': salary, 'type': 'exact'}
                except ValueError:
                    continue
    
    return None

def calculate_hourly_rate(salary_info: Dict[str, Any], working_hours: int) -> Optional[Dict[str, Any]]:
    """Calculate hourly rate (ЧТС) from salary information."""
    if not salary_info or working_hours <= 0:
        return None
    
    result = {
        'working_hours_per_month': working_hours,
        'salary_info': salary_info
    }
    
    if salary_info['type'] == 'exact':
        hourly_rate = salary_info['exact'] / working_hours
        result['hourly_rate'] = round(hourly_rate, 2)
        result['calculation'] = f"{salary_info['exact']} / {working_hours} = {result['hourly_rate']} руб/час"
    
    elif salary_info['type'] == 'from':
        hourly_rate = salary_info['min'] / working_hours
        result['hourly_rate_min'] = round(hourly_rate, 2)
        result['calculation'] = f"от {salary_info['min']} / {working_hours} = от {result['hourly_rate_min']} руб/час"
    
    elif salary_info['type'] == 'to':
        hourly_rate = salary_info['max'] / working_hours
        result['hourly_rate_max'] = round(hourly_rate, 2)
        result['calculation'] = f"до {salary_info['max']} / {working_hours} = до {result['hourly_rate_max']} руб/час"
    
    elif salary_info['type'] == 'range':
        min_hourly = salary_info['min'] / working_hours
        max_hourly = salary_info['max'] / working_hours
        result['hourly_rate_min'] = round(min_hourly, 2)
        result['hourly_rate_max'] = round(max_hourly, 2)
        result['calculation'] = f"{salary_info['min']}-{salary_info['max']} / {working_hours} = {result['hourly_rate_min']}-{result['hourly_rate_max']} руб/час"
    
    return result

async def fetch_employer_vacancies(employer_id: str, area: int = 2, pages: int = 5) -> List[Dict[str, Any]]:
    """Fetch all vacancies from a specific employer using employer ID."""
    headers = {"User-Agent": "job-analytics-bot/1.0"}
    all_vacancies = []
    
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        page = 0
        while page < pages:
            try:
                params = {
                    "employer_id": employer_id,
                    "area": area,
                    "per_page": 100,
                    "page": page
                }
                
                print(f"Fetching page {page + 1} for employer {employer_id}...")
                resp = await client.get("https://api.hh.ru/vacancies", params=params)
                resp.raise_for_status()
                data = resp.json()
                
                page_items = data.get("items", [])
                if not page_items:
                    print(f"No more items on page {page + 1}, stopping")
                    break
                
                all_vacancies.extend(page_items)
                print(f"Found {len(page_items)} vacancies on page {page + 1}")
                
                # Check if we've reached the last page
                total_pages = int(data.get("pages", 0))
                if page >= total_pages - 1:
                    print(f"Reached last page ({total_pages})")
                    break
                
                page += 1
                
                # Add small delay to be respectful to the API
                await asyncio.sleep(0.5)
                
            except Exception as e:
                print(f"Error fetching page {page + 1} for employer {employer_id}: {e}")
                break
    
    return all_vacancies

async def fetch_all_employer_vacancies(area: int = 2, pages: int = 5) -> List[Dict[str, Any]]:
    """Fetch vacancies from all target employers."""
    all_vacancies = []
    
    for company_name, employer_id in EMPLOYER_IDS.items():
        print(f"\n🏢 Fetching vacancies for: {company_name} (ID: {employer_id})")
        try:
            vacancies = await fetch_employer_vacancies(employer_id, area, pages)
            print(f"✅ Found {len(vacancies)} total vacancies for {company_name}")
            all_vacancies.extend(vacancies)
        except Exception as e:
            print(f"❌ Error fetching vacancies for {company_name}: {e}")
            continue
    
    return all_vacancies

def analyze_hourly_rates(vacancies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Analyze hourly rates for all vacancies."""
    results = []
    current_month = datetime.now().month
    working_hours = get_working_hours_for_month(current_month)
    
    for vacancy in vacancies:
        employer_name = vacancy.get('employer', {}).get('name', '')
        job_title = vacancy.get('name', '')
        
        # Try to extract salary from different sources
        salary_info = None
        
        # 1. Try from salary field
        salary = vacancy.get('salary')
        if salary:
            normalized_salary = normalize_salary(salary)
            if normalized_salary:
                salary_info = {
                    'exact': normalized_salary,
                    'type': 'exact'
                }
        
        # 2. If no salary field, try to extract from job title
        if not salary_info:
            salary_info = extract_salary_from_text(job_title)
        
        # 3. Try from job description if available
        if not salary_info and 'description' in vacancy:
            salary_info = extract_salary_from_text(vacancy['description'])
        
        # Calculate hourly rate if we have salary information
        hourly_rate_info = None
        if salary_info:
            hourly_rate_info = calculate_hourly_rate(salary_info, working_hours)
        
        result = {
            'id': vacancy.get('id'),
            'title': job_title,
            'employer': employer_name,
            'url': vacancy.get('alternate_url'),
            'salary_info': salary_info,
            'hourly_rate_info': hourly_rate_info,
            'working_hours_per_month': working_hours,
            'has_salary': salary_info is not None,
            'has_hourly_rate': hourly_rate_info is not None
        }
        
        results.append(result)
    
    return results

def generate_hourly_rate_report(analysis_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate a comprehensive report of hourly rates."""
    total_vacancies = len(analysis_results)
    vacancies_with_salary = sum(1 for r in analysis_results if r['has_salary'])
    vacancies_with_hourly_rate = sum(1 for r in analysis_results if r['has_hourly_rate'])
    
    # Group by company
    by_company = {}
    for result in analysis_results:
        company = result['employer']
        if company not in by_company:
            by_company[company] = []
        by_company[company].append(result)
    
    # Calculate statistics
    hourly_rates = []
    for result in analysis_results:
        if result['hourly_rate_info']:
            hr_info = result['hourly_rate_info']
            if 'hourly_rate' in hr_info:
                hourly_rates.append(hr_info['hourly_rate'])
            elif 'hourly_rate_min' in hr_info:
                hourly_rates.append(hr_info['hourly_rate_min'])
            elif 'hourly_rate_max' in hr_info:
                hourly_rates.append(hr_info['hourly_rate_max'])
    
    stats = {}
    if hourly_rates:
        stats = {
            'min_hourly_rate': min(hourly_rates),
            'max_hourly_rate': max(hourly_rates),
            'avg_hourly_rate': round(sum(hourly_rates) / len(hourly_rates), 2),
            'median_hourly_rate': round(sorted(hourly_rates)[len(hourly_rates)//2], 2)
        }
    
    return {
        'summary': {
            'total_vacancies': total_vacancies,
            'vacancies_with_salary': vacancies_with_salary,
            'vacancies_with_hourly_rate': vacancies_with_hourly_rate,
            'salary_coverage_percent': round((vacancies_with_salary / total_vacancies * 100), 2) if total_vacancies > 0 else 0,
            'working_hours_per_month': analysis_results[0]['working_hours_per_month'] if analysis_results else 0
        },
        'statistics': stats,
        'by_company': by_company,
        'all_results': analysis_results
    }

async def main():
    """Main function to run the hourly rate analysis."""
    print("🚀 Starting hourly rate analysis...")
    print("=" * 60)
    
    # Fetch vacancies from all target employers
    vacancies = await fetch_all_employer_vacancies(area=2, pages=3)  # Saint-Petersburg, 3 pages
    print(f"\n📊 Total vacancies fetched: {len(vacancies)}")
    
    # Analyze hourly rates
    analysis_results = analyze_hourly_rates(vacancies)
    
    # Generate report
    report = generate_hourly_rate_report(analysis_results)
    
    # Print summary
    print("\n" + "="*50)
    print("HOURLY RATE ANALYSIS REPORT")
    print("="*50)
    print(f"Total vacancies analyzed: {report['summary']['total_vacancies']}")
    print(f"Vacancies with salary info: {report['summary']['vacancies_with_salary']}")
    print(f"Salary coverage: {report['summary']['salary_coverage_percent']}%")
    print(f"Working hours per month: {report['summary']['working_hours_per_month']}")
    
    if report['statistics']:
        print(f"\nHourly Rate Statistics:")
        print(f"  Min: {report['statistics']['min_hourly_rate']} руб/час")
        print(f"  Max: {report['statistics']['max_hourly_rate']} руб/час")
        print(f"  Average: {report['statistics']['avg_hourly_rate']} руб/час")
        print(f"  Median: {report['statistics']['median_hourly_rate']} руб/час")
    
    print(f"\nResults by company:")
    for company, results in report['by_company'].items():
        with_salary = sum(1 for r in results if r['has_salary'])
        print(f"  {company}: {len(results)} vacancies ({with_salary} with salary)")
    
    # Save detailed results to file
    with open('hourly_rate_analysis.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\nDetailed results saved to: hourly_rate_analysis.json")
    
    return report

if __name__ == "__main__":
    asyncio.run(main())
