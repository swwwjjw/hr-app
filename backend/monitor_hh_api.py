#!/usr/bin/env python3
"""
Monitor script to check when HH API starts returning results for driver searches.
"""

import asyncio
import httpx
import time
from datetime import datetime

async def check_hh_api(query: str, area: int = 2):
    """Check if HH API returns results for the given query."""
    headers = {"User-Agent": "job-analytics-bot/1.0"}
    params = {
        "text": query,
        "area": area,
        "per_page": 100,
        "page": 0
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            resp = await client.get("https://api.hh.ru/vacancies", params=params)
            resp.raise_for_status()
            data = resp.json()
            
            found = data.get("found", 0)
            pages = data.get("pages", 0)
            items_count = len(data.get("items", []))
            
            return {
                "found": found,
                "pages": pages,
                "items_count": items_count,
                "success": True
            }
    except Exception as e:
        return {
            "found": 0,
            "pages": 0,
            "items_count": 0,
            "success": False,
            "error": str(e)
        }

async def monitor_driver_searches():
    """Monitor driver searches and report when results are found."""
    queries = [
        "водитель категория D",
        "водитель автобуса", 
        "водитель",
        "автобус"
    ]
    
    print(f"🚀 Starting HH API monitoring at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    while True:
        print(f"\n⏰ Checking at {datetime.now().strftime('%H:%M:%S')}")
        
        for query in queries:
            result = await check_hh_api(query)
            
            if result["success"] and result["found"] > 0:
                print(f"✅ FOUND: '{query}' - {result['found']} vacancies, {result['pages']} pages")
                if result["found"] >= 170:
                    print(f"🎉 SUCCESS! Found {result['found']} vacancies for '{query}' - this meets your target!")
                    return
            else:
                status = "❌ No results" if result["success"] else f"❌ Error: {result.get('error', 'Unknown')}"
                print(f"   '{query}': {status}")
        
        print("⏳ Waiting 30 seconds before next check...")
        await asyncio.sleep(30)

if __name__ == "__main__":
    try:
        asyncio.run(monitor_driver_searches())
    except KeyboardInterrupt:
        print("\n🛑 Monitoring stopped by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")

