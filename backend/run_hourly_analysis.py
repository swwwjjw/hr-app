#!/usr/bin/env python3
"""
Simple script to run hourly rate analysis using employer IDs.
"""

import asyncio
from hourly_rate_parser import main

async def run_analysis():
    """Run the analysis and display a formatted summary."""
    print("🔍 Analyzing hourly rates (ЧТС) using employer IDs...")
    print("=" * 60)
    
    try:
        report = await main()
        
        print("\n📊 SUMMARY RESULTS:")
        print("-" * 40)
        print(f"📈 Total vacancies analyzed: {report['summary']['total_vacancies']}")
        print(f"💰 Vacancies with salary info: {report['summary']['vacancies_with_salary']}")
        print(f"📋 Salary coverage: {report['summary']['salary_coverage_percent']}%")
        print(f"⏰ Working hours per month: {report['summary']['working_hours_per_month']}")
        
        if report['statistics']:
            print(f"\n💵 HOURLY RATE STATISTICS:")
            print("-" * 40)
            print(f"🔻 Minimum: {report['statistics']['min_hourly_rate']} руб/час")
            print(f"🔺 Maximum: {report['statistics']['max_hourly_rate']} руб/час")
            print(f"📊 Average: {report['statistics']['avg_hourly_rate']} руб/час")
            print(f"📈 Median: {report['statistics']['median_hourly_rate']} руб/час")
        
        print(f"\n🏢 RESULTS BY COMPANY:")
        print("-" * 40)
        for company, results in report['by_company'].items():
            with_salary = sum(1 for r in results if r['has_salary'])
            print(f"• {company}")
            print(f"  └─ {len(results)} vacancies ({with_salary} with salary)")
        
        # Show some examples
        print(f"\n💼 SAMPLE VACANCIES WITH HOURLY RATES:")
        print("-" * 40)
        count = 0
        for result in report['all_results']:
            if result['has_hourly_rate'] and count < 5:
                hr_info = result['hourly_rate_info']
                print(f"• {result['title']} at {result['employer']}")
                print(f"  └─ {hr_info['calculation']}")
                count += 1
        
        print(f"\n✅ Analysis complete! Detailed results saved to: hourly_rate_analysis.json")
        
    except Exception as e:
        print(f"❌ Error during analysis: {e}")
        return None

if __name__ == "__main__":
    asyncio.run(run_analysis())
