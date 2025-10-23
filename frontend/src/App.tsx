import React, { useEffect, useMemo, useState } from 'react';
import { fetchAnalyze, fetchResumeStats, fetchSimplifiedVacancies, fetchCompetitorHourlyRates } from './api/client';
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
  const [selectedEmployer, setSelectedEmployer] = useState<string>('');
  const [competitorReload, setCompetitorReload] = useState(0);
  const [competitorHourlyRates, setCompetitorHourlyRates] = useState<any>(null);

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
        // Load both regular competitor data and hourly rates
        const [res, hourlyRates] = await Promise.all([
          fetchSimplifiedVacancies({
            query,
            area,
            pages,
            per_page: perPage,
            employer_mark: true,
            fetch_all: true,
          }),
          fetchCompetitorHourlyRates({ area })
        ]);
        
        const items = Array.isArray(res?.items) ? res.items : [];
        setCompetitorItems(items);
        setCompetitorHourlyRates(hourlyRates);
        
        // Set default employer if not chosen yet
        if (!selectedEmployer) {
          // choose the most frequent employer
          const counts = new Map<string, number>();
          for (const it of items) {
            const name = (it?.employer_name || '').toString().trim();
            if (!name) continue;
            counts.set(name, (counts.get(name) || 0) + 1);
          }
          const top = Array.from(counts.entries()).sort((a, b) => b[1] - a[1])[0]?.[0] || '';
          setSelectedEmployer(top);
        }
      } finally {
        setCompetitorLoading(false);
      }
    };
    loadCompetitors();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, query, area, pages, perPage, competitorReload]);

  const competitorOptions = useMemo(() => {
    const counts = new Map<string, number>();
    (competitorItems || []).forEach((it) => {
      const name = (it?.employer_name || '').toString().trim();
      if (!name) return;
      counts.set(name, (counts.get(name) || 0) + 1);
    });
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([name]) => name);
  }, [competitorItems]);

  // Ensure selected employer remains valid when options change
  useEffect(() => {
    if (activeTab !== 'competitors') return;
    if (selectedEmployer && !competitorOptions.includes(selectedEmployer)) {
      setSelectedEmployer(competitorOptions[0] || '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [competitorOptions]);


  return (
    <div className="container">
      <h1>Аналитика вакансий</h1>
      <div className="meta">📍 Санкт-Петербург</div>

      {/* Tabs */}
      <div className="tabs" style={{ marginBottom: 16 }}>
        <button className={activeTab === 'competitors' ? 'tab active' : 'tab'} onClick={() => setActiveTab('competitors')}>Конкуренты</button>
      </div>

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
            <button onClick={load} disabled={loading}>Найти</button>
          </>
        )}
        {activeTab === 'vacancies' && (
          <button onClick={() => setActiveTab('competitors')} title="Перейти к вкладке конкурентов">
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
        <div>
          <div className="card">
            <h3>ЧТС по конкурентам</h3>
            <div className="controls" style={{ marginTop: 8 }}>
              <button onClick={() => setCompetitorReload((x) => x + 1)} disabled={competitorLoading}>
                {competitorLoading ? 'Загрузка...' : 'Обновить данные'}
              </button>
            </div>
            
            {competitorHourlyRates && competitorHourlyRates.company_stats && (
              <div>
                <div className="meta" style={{ marginBottom: 16 }}>
                  Рабочих часов в месяц: {competitorHourlyRates.working_hours_per_month || 168}
                </div>
                
                <div className="grid4" style={{ marginBottom: 24 }}>
                  <div className="miniCard">
                    <div>Всего вакансий</div>
                    <b>{competitorHourlyRates.summary?.total_vacancies || 0}</b>
                  </div>
                  <div className="miniCard">
                    <div>С зарплатой</div>
                    <b>{competitorHourlyRates.summary?.vacancies_with_salary || 0}</b>
                  </div>
                  <div className="miniCard">
                    <div>Покрытие зарплат</div>
                    <b>{competitorHourlyRates.summary?.salary_coverage_percent || 0}%</b>
                  </div>
                  <div className="miniCard">
                    <div>Компаний</div>
                    <b>{Object.keys(competitorHourlyRates.company_stats).length}</b>
                  </div>
                </div>

                <div className="card">
                  <h4>Статистика ЧТС по компаниям</h4>
                  <div style={{ display: 'grid', gap: '12px', marginTop: '16px' }}>
                    {Object.entries(competitorHourlyRates.company_stats).map(([company, stats]: [string, any]) => (
                      <div key={company} style={{ 
                        padding: '16px', 
                        border: '1px solid #e0e0e0', 
                        borderRadius: '8px',
                        backgroundColor: '#f9f9f9'
                      }}>
                        <h5 style={{ margin: '0 0 8px 0', color: '#333' }}>{company}</h5>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '8px' }}>
                          <div>
                            <div style={{ fontSize: '12px', color: '#666' }}>Мин ЧТС</div>
                            <div style={{ fontWeight: 'bold', color: '#e74c3c' }}>{stats.min} ₽/час</div>
                          </div>
                          <div>
                            <div style={{ fontSize: '12px', color: '#666' }}>Макс ЧТС</div>
                            <div style={{ fontWeight: 'bold', color: '#27ae60' }}>{stats.max} ₽/час</div>
                          </div>
                          <div>
                            <div style={{ fontSize: '12px', color: '#666' }}>Средняя ЧТС</div>
                            <div style={{ fontWeight: 'bold', color: '#3498db' }}>{stats.avg} ₽/час</div>
                          </div>
                          <div>
                            <div style={{ fontSize: '12px', color: '#666' }}>Вакансий</div>
                            <div style={{ fontWeight: 'bold' }}>{stats.count}/{stats.total_vacancies}</div>
                          </div>
                          <div>
                            <div style={{ fontSize: '12px', color: '#666' }}>Покрытие</div>
                            <div style={{ fontWeight: 'bold' }}>{stats.salary_coverage}%</div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
            
            {competitorLoading && (
              <div style={{ textAlign: 'center', padding: '20px' }}>
                <div>Загрузка данных о ЧТС...</div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};