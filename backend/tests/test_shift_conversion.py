import math
import pytest

from backend.hh_parser_ver2 import estimate_monthly_salary_from_text
from backend.analytics import salary_stats


def approx_eq(a: float, b: float, tol: float = 1.0):
    assert abs(a - b) <= tol, f"{a} != {b} within {tol}"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Оплата за смену 4 500 ₽. График: 18 смен в месяц", 4500 * 18),
        ("Смена — 5000. 3 смены в неделю", 5000 * 4.33 * 3),
        ("Оплата за см. 4500", 4500 * 15),  # fallback 15 shifts
        ("4-5 т.р/см.", 4500 * 15),  # thousand marker + short shift token
        ("Смена 4.5 тыс", 4500 * 15),  # thousand marker text
        ("За смену 3500, в мес 20 смен", 3500 * 20),  # reversed month pattern
        ("Сутки через двое. 5000 р/смена", 5000 * (30.0 / 3.0)),  # schedule phrase
        ("График 1/3. смена 3500 рублей", 3500 * (30.0 * (1 / (1 + 3)))),  # ratio schedule
        ("Посменная оплата: 4000–5000", 4500 * 15),  # range with word
        ("От 4000 до 5000 за смену", 4500 * 15),  # ot..do.. near shift
    ],
)
def test_estimate_monthly_salary_from_text(text, expected):
    val = estimate_monthly_salary_from_text(
        title="",
        responsibility=text,
        requirement=None,
        description_text="",
    )
    assert isinstance(val, float)
    approx_eq(val, expected, tol=2.0)


def test_salary_stats_includes_per_shift_estimates():
    vacancies = [
        {"salary_per_shift": True, "salary_estimated_monthly": 70000},
        {"salary_per_shift": False, "salary_avg": 120000},
    ]
    stats = salary_stats(vacancies)
    assert stats["count"] == 2
    approx_eq(stats["min"], 70000)
    approx_eq(stats["max"], 120000)
    approx_eq(stats["avg"], (70000 + 120000) / 2.0)
    approx_eq(stats["median"], (70000 + 120000) / 2.0)
