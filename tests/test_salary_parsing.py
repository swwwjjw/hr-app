import math
from typing import Optional

from backend.hh_parser_ver2 import estimate_monthly_salary_from_text


def approx(a: float, b: float, rel: float = 0.02, abs_tol: float = 1.0) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol)


def test_explicit_per_month_shifts_rub_per_shift():
    # 4500 ₽ за смену, 18 смен в месяц => 81_000 ₽
    title = "Охранник"
    responsibility = ""
    requirement = None
    description = "Оплата 4 500 ₽ за смену. 18 смен в месяц."
    monthly: Optional[float] = estimate_monthly_salary_from_text(title, responsibility, requirement, description)
    assert isinstance(monthly, float)
    assert approx(monthly, 4500 * 18)


def test_range_per_shift_with_schedule_fraction():
    # 4000–5000 руб/смена, график 2/2 => per-shift ~4500, monthly ~15 shifts => 67_500 ₽
    title = "Сотрудник"
    responsibility = ""
    requirement = None
    description = "Ставка 4 000–5 000 руб/смена, график 2/2"
    monthly = estimate_monthly_salary_from_text(title, responsibility, requirement, description)
    assert isinstance(monthly, float)
    assert approx(monthly, 4500 * 15)


def test_colloquial_in_shift_and_per_week_count():
    # 4000 в смену, 3 смены в неделю => 3*4.33 ≈ 12.99 shifts
    title = "Сторож"
    responsibility = ""
    requirement = None
    description = "Оплата 4000 в смену, 3 смены в неделю"
    monthly = estimate_monthly_salary_from_text(title, responsibility, requirement, description)
    assert isinstance(monthly, float)
    expected = 4000 * 3 * 4.33
    assert approx(monthly, expected, rel=0.03)


def test_oplata_smeny_phrase():
    # оплата смены: 4500 => fallback 15 shifts => 67_500 ₽
    title = "Контролёр"
    responsibility = ""
    requirement = None
    description = "Оплата смены: 4500"
    monthly = estimate_monthly_salary_from_text(title, responsibility, requirement, description)
    assert isinstance(monthly, float)
    assert approx(monthly, 4500 * 15)


def test_sutki_phrase_and_schedule():
    # 5000 за сутки, сутки через двое => 10 shifts => 50_000 ₽
    title = "Охранник"
    responsibility = ""
    requirement = None
    description = "Ставка 5000 за сутки, график сутки через двое"
    monthly = estimate_monthly_salary_from_text(title, responsibility, requirement, description)
    assert isinstance(monthly, float)
    assert approx(monthly, 5000 * (30 / 3))


def test_thousand_marker_short_form():
    # 4,5 тыс/см. => 4500 per shift, fallback 15 => 67_500 ₽
    title = "Сотрудник"
    responsibility = ""
    requirement = None
    description = "Ставка 4,5 тыс/см."
    monthly = estimate_monthly_salary_from_text(title, responsibility, requirement, description)
    assert isinstance(monthly, float)
    assert approx(monthly, 4500 * 15, rel=0.03)


def test_english_per_shift_variants():
    # 4000 RUB per shift, 18 смен/мес => 72_000 ₽
    title = "Security guard"
    responsibility = ""
    requirement = None
    description = "Pay 4000 RUB per shift, 18 смен/мес"
    monthly = estimate_monthly_salary_from_text(title, responsibility, requirement, description)
    assert isinstance(monthly, float)
    assert approx(monthly, 4000 * 18)
