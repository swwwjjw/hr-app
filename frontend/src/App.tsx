import React, { useEffect, useMemo, useState } from 'react';
import { fetchAnalyze, fetchResumeStats, fetchSimplifiedVacancies } from './api/client';
import { SalaryBubbleChart } from './components/SalaryBubbleChart';
import { SalaryStatsCard } from './components/SalaryStatsCard';
import { HourlyStatsCard } from './components/HourlyStatsCard';
import WordCloud from 'wordcloud';

export const App: React.FC = () => {
  const [query, setQuery] = useState('контролер кпп');
  const [area, setArea] = useState<number>(2);
  const [pages, setPages] = useState<number>(2);
  const [perPage, setPerPage] = useState<number>(50);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any>(null);
  const [resumeStats, setResumeStats] = useState<any>(null);
  const [activeTab, setActiveTab] = useState<'vacancies' | 'competitors'>('vacancies');

  // Competitor tab state
  const [competitorLoading, setCompetitorLoading] = useState(false);
  const [competitorItems, setCompetitorItems] = useState<any[]>([]);
  const [competitorReload, setCompetitorReload] = useState(0);

  const presets = useMemo(() => [
    { value: 'контролер кпп', label: 'Инспекторы-контролёры' },
    { value: 'инспектор досмотр', label: 'Инспекторы по досмотру' },
    { value: 'инспектор перрон', label: 'Инспекторы перронного контроля' },
    { value: 'гбр, охрана', label: 'Инспектор ГБР' }
  ], []);

  const load = async (overrides?: { query?: string; area?: number; pages?: number; per_page?: number }) => {
    setLoading(true);
    try {
      const qv = overrides?.query ?? query;
      const av = overrides?.area ?? area;
      const pg = overrides?.pages ?? pages;
      const pp = overrides?.per_page ?? perPage;
      const [analyze, resumes] = await Promise.all([
        fetchAnalyze({ query: qv, area: av, pages: pg, per_page: pp }),
        fetchResumeStats({ vacancy_query: qv, area: av, pages: pg, per_page: pp })
      ]);
      setData(analyze);
      setResumeStats(resumes);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // If no explicit query in URL, load with defaults on mount
    const sp = new URLSearchParams(window.location.search);
    if (!sp.get('query')) {
      load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Initialize from URL: tab, query, area, pages, per_page
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    const tab = sp.get('tab');
    if (tab === 'competitors') setActiveTab('competitors');

    const overrides: { query?: string; area?: number; pages?: number; per_page?: number } = {};
    const q = sp.get('query');
    if (q) {
      setQuery(q);
      overrides.query = q;
    }
    const a = sp.get('area');
    if (a != null && a !== '' && !Number.isNaN(Number(a))) {
      const ai = Number(a);
      setArea(ai);
      overrides.area = ai;
    }
    const pg = sp.get('pages');
    if (pg != null && pg !== '' && !Number.isNaN(Number(pg))) {
      const pgi = Number(pg);
      setPages(pgi);
      overrides.pages = pgi;
    }
    const pp = sp.get('per_page');
    if (pp != null && pp !== '' && !Number.isNaN(Number(pp))) {
      const ppi = Number(pp);
      setPerPage(ppi);
      overrides.per_page = ppi;
    }
    if (Object.keys(overrides).length > 0) {
      // Use overrides immediately to avoid racing state updates
      load(overrides);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load competitor items when switching to competitors tab or when filters change
  useEffect(() => {
    const loadCompetitors = async () => {
      if (activeTab !== 'competitors') return;
      setCompetitorLoading(true);
      try {
        const res = await fetchSimplifiedVacancies({
          // Intentionally ignore the query on competitors tab to aggregate by area
          query: '',
          area,
          // Use maximum page size and fetch all pages to include all vacancies
          per_page: 100,
          employer_mark: true,
          fetch_all: true,
        });
        const items = Array.isArray(res?.items) ? res.items : [];
        setCompetitorItems(items);
      } finally {
        setCompetitorLoading(false);
      }
    };
    loadCompetitors();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, query, area, pages, perPage, competitorReload]);

  // Region options for dropdown (basic set)
  const regionOptions = useMemo(() => [
    { value: 1, label: 'Москва' },
    { value: 2, label: 'Санкт-Петербург' },
  ], []);

  const competitorHourly = useMemo(() => {
    // Aggregate hourly stats across all vacancies in the selected region
    const HOURS_PER_MONTH = 164.0;
    const monthly: number[] = [];
    for (const v of competitorItems || []) {
      if (v?.salary_per_shift === true) continue; // exclude per-shift
      if (!v?.schedule) continue; // need schedule to treat as hourly-based role
      let m: number | null = null;
      if (typeof v?.salary_avg === 'number') {
        m = v.salary_avg as number;
      } else if (v?.salary && typeof v.salary === 'object') {
        const sf = typeof v.salary.from === 'number' ? (v.salary.from as number) : null;
        const st = typeof v.salary.to === 'number' ? (v.salary.to as number) : null;
        if (sf !== null && st !== null) m = (sf + st) / 2;
        else if (sf !== null) m = sf;
        else if (st !== null) m = st;
      }
      if (m !== null && m >= 10000) {
        monthly.push(m);
      }
    }
    if (!monthly.length) return {} as any;
    const hourly = monthly.map((m) => m / HOURS_PER_MONTH).sort((a, b) => a - b);
    const avg = hourly.reduce((a, b) => a + b, 0) / hourly.length;
    const n = hourly.length;
    const median = n % 2 === 1 ? hourly[(n - 1) / 2] : (hourly[n / 2 - 1] + hourly[n / 2]) / 2;
    return {
      min: hourly[0],
      median,
      avg,
      max: hourly[hourly.length - 1],
      count: hourly.length,
    } as any;
  }, [competitorItems]);

  return (
    <div className="container">
      <h1>Аналитика вакансий</h1>
      <div className="meta">📍 Санкт-Петербург</div>

      {/* Tabs removed: 'Конкуренты' button deleted as requested */}

      {/* Shared controls for query selection */}
      <div className="controls">
        {activeTab === 'vacancies' && (
          <>
            <select value={query} onChange={(e) => setQuery(e.target.value)}>
              <option value="">Выберите вакансию</option>
              {presets.map(p => (
                <option key={p.value} value={p.value} style={{color: '#000000ff'}}>{p.label}</option>
              ))}
            </select>
          </>
        )}
        {activeTab === 'vacancies' && (
          <button
            onClick={() => {
              const { protocol, hostname } = window.location;
              const url = new URL(`${protocol}//${hostname}/competitors.html`);
              url.searchParams.set('query', (query || '').toString());
              if (area != null) url.searchParams.set('area', String(area));
              if (pages != null) url.searchParams.set('pages', String(pages));
              if (perPage != null) url.searchParams.set('per_page', String(perPage));
              window.location.href = url.toString();
            }}
            title="Перейти к вкладке конкурентов"
          >
            К конкурентам
          </button>
        )}
        {activeTab === 'competitors' && (
          <button
            onClick={() => {
              const { protocol, hostname } = window.location;
              const url = new URL(`${protocol}//${hostname}:8000/dashboard`);
              // Preserve current filters when returning to backend dashboard
              url.searchParams.set('query', (query || '').toString());
              if (area != null) url.searchParams.set('area', String(area));
              if (pages != null) url.searchParams.set('pages', String(pages));
              if (perPage != null) url.searchParams.set('per_page', String(perPage));
              window.location.href = url.toString();
            }}
            title="Вернуться на порт 8000"
          >
            К вакансиям
          </button>
        )}
      </div>

      {activeTab === 'vacancies' && data && (
        <div className="row">
          <div className="card">
            <h3>Зарплата vs Рейтинг работодателя</h3>
            <SalaryBubbleChart items={data.items || []} />
          </div>
          <div className="card">
            <h3>Статистика зарплат</h3>
            <SalaryStatsCard salaries={data.salaries} />
          </div>
        </div>
      )}

      {activeTab === 'vacancies' && resumeStats && (
        <div className="card" style={{ marginTop: 24 }}>
          <h3>Статистика резюме</h3>
          <div className="meta">Резюме (всего: {resumeStats.total_resumes || 0}, активные: {resumeStats.active_resumes || 0})</div>
          <div className="grid4">
            <div className="miniCard"><div>Активные резюме</div><b>{resumeStats.active_resumes ?? '—'}</b></div>
            <div className="miniCard"><div>Доля активных</div><b>{typeof resumeStats.active_share === 'number' ? Math.round(resumeStats.active_share * 100) + '%' : '—'}</b></div>
            <div className="miniCard"><div>Вакансий по запросу</div><b>{resumeStats.vacancy_count ?? '—'}</b></div>
            <div className="miniCard"><div>Резюме на вакансию</div><b>{typeof resumeStats.resumes_per_vacancy === 'number' ? resumeStats.resumes_per_vacancy.toFixed(2) : '—'}</b></div>
          </div>
        </div>
      )}

      {/* Competitors Tab */}
      {activeTab === 'competitors' && (
        <div className="card">
          <h3>ЧТС по регионам</h3>
          <div className="controls" style={{ marginTop: 8 }}>
            <select
              value={area ?? ''}
              onChange={(e) => {
                const newArea = Number(e.target.value);
                setArea(newArea);
                setCompetitorReload((x) => x + 1);
              }}
            >
              <option value="">Выберите регион</option>
              {regionOptions.map((r) => (
                <option key={r.value} value={r.value} style={{ color: '#000000ff' }}>{r.label}</option>
              ))}
            </select>
          </div>
          <div className="meta">{regionOptions.find(r => r.value === area)?.label || 'Регион не выбран'}</div>
          <HourlyStatsCard hourly={competitorHourly} />
        </div>
      )}
    </div>
  );
};