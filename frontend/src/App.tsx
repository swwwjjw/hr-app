// import React, { useEffect, useMemo, useState } from 'react';
// import { fetchAnalyze, fetchResumeStats } from './api/client';
// import { SalaryBubbleChart } from './components/SalaryBubbleChart';
// import { SalaryStatsCard } from './components/SalaryStatsCard';

// export const App: React.FC = () => {
//   const [query, setQuery] = useState('контролер кпп');
//   const [area] = useState<number>(2);
//   const [pages] = useState<number>(2);
//   const [perPage] = useState<number>(50);
//   const [loading, setLoading] = useState(false);
//   const [data, setData] = useState<any>(null);
//   const [resumeStats, setResumeStats] = useState<any>(null);

//   const presets = useMemo(() => [
//     { value: 'контролер кпп', label: 'Инспекторы-контролёры' },
//     { value: 'инспектор досмотр', label: 'Инспекторы по досмотру' },
//     { value: 'инспектор перрон', label: 'Инспекторы перронного контроля' },
//     { value: 'гбр, охрана', label: 'Инспектор ГБР' }
//   ], []);

//   const load = async () => {
//     setLoading(true);
//     try {
//       const [analyze, resumes] = await Promise.all([
//         fetchAnalyze({ query, area, pages, per_page: perPage }),
//         fetchResumeStats({ vacancy_query: query, area, pages, per_page: perPage })
//       ]);
//       setData(analyze);
//       setResumeStats(resumes);
//     } finally {
//       setLoading(false);
//     }
//   };

//   useEffect(() => {
//     load();
//     // eslint-disable-next-line react-hooks/exhaustive-deps
//   }, []);

//   return (
//     <div className="container">
//       <h1>Аналитика вакансий</h1>
//       <div className="meta">📍 Санкт-Петербург</div>

//       <div className="controls">
//         <select value={query} onChange={(e) => setQuery(e.target.value)}>
//           <option value="">Выберите вакансию</option>
//           {presets.map(p => (
//             <option key={p.value} value={p.value} style={{color: '#000000ff'}}>{p.label}</option>
//           ))}
//         </select>
//         <button onClick={load} disabled={loading}>Найти</button>
//       </div>

//       {data && (
//         <div className="row">
//           <div className="card">
//             <h3>Зарплата vs Рейтинг работодателя</h3>
//             <SalaryBubbleChart items={data.items || []} />
//           </div>
//           <div className="card">
//             <h3>Статистика зарплат</h3>
//             <SalaryStatsCard salaries={data.salaries} />
//           </div>
//         </div>
//       )}

//       {resumeStats && (
//         <div className="card" style={{ marginTop: 24 }}>
//           <h3>Статистика резюме</h3>
//           <div className="meta">Резюме (всего: {resumeStats.total_resumes || 0}, активные: {resumeStats.active_resumes || 0})</div>
//           <div className="grid4">
//             <div className="miniCard"><div>Активные резюме</div><b>{resumeStats.active_resumes ?? '—'}</b></div>
//             <div className="miniCard"><div>Доля активных</div><b>{typeof resumeStats.active_share === 'number' ? Math.round(resumeStats.active_share * 100) + '%' : '—'}</b></div>
//             <div className="miniCard"><div>Вакансий по запросу</div><b>{resumeStats.vacancy_count ?? '—'}</b></div>
//             <div className="miniCard"><div>Резюме на вакансию</div><b>{typeof resumeStats.resumes_per_vacancy === 'number' ? resumeStats.resumes_per_vacancy.toFixed(2) : '—'}</b></div>
//           </div>
//         </div>
//       )}
//     </div>
//   );
// };


import React, { useEffect, useMemo, useState, useRef } from 'react';
import { fetchAnalyze, fetchResumeStats } from './api/client';
import { SalaryBubbleChart } from './components/SalaryBubbleChart';
import { SalaryStatsCard } from './components/SalaryStatsCard';

// Определяем интерфейс для опций выпадающего списка
interface SelectOption {
  value: string;
  label: string;
}

// Определяем интерфейс для пропсов компонента CustomSelect
interface CustomSelectProps {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder: string;
}

const CustomSelect: React.FC<CustomSelectProps> = ({ value, onChange, options, placeholder }) => {
  const [isOpen, setIsOpen] = useState(false);
  const selectRef = useRef<HTMLDivElement>(null);

  const selectedOption = options.find(opt => opt.value === value) || { label: placeholder };

  const handleSelect = (option: SelectOption) => {
    onChange(option.value);
    setIsOpen(false);
  };

  // Закрытие при клике вне компонента
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (selectRef.current && !selectRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className="custom-select" ref={selectRef}>
      <div 
        className={`select-trigger ${isOpen ? 'open' : ''}`}
        onClick={() => setIsOpen(!isOpen)}
      >
        <span>{selectedOption.label}</span>
        <svg className="select-arrow" width="12" height="8" viewBox="0 0 12 8" fill="none">
          <path d="M1 1.5L6 6.5L11 1.5" stroke="currentColor" strokeWidth="2"/>
        </svg>
      </div>
      
      {isOpen && (
        <div className="select-options">
          {options.map(option => (
            <div
              key={option.value}
              className={`select-option ${value === option.value ? 'selected' : ''}`}
              onClick={() => handleSelect(option)}
            >
              {option.label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export const App: React.FC = () => {
  const [query, setQuery] = useState('контролер кпп');
  const [area] = useState<number>(2);
  const [pages] = useState<number>(2);
  const [perPage] = useState<number>(50);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any>(null);
  const [resumeStats, setResumeStats] = useState<any>(null);

  const presets = useMemo(() => [
    { value: 'контролер кпп', label: 'Инспекторы-контролёры' },
    { value: 'инспектор досмотр', label: 'Инспекторы по досмотру' },
    { value: 'инспектор перрон', label: 'Инспекторы перронного контроля' },
    { value: 'гбр, охрана', label: 'Инспектор ГБР' }
  ], []);

  const load = async () => {
    setLoading(true);
    try {
      const [analyze, resumes] = await Promise.all([
        fetchAnalyze({ query, area, pages, per_page: perPage }),
        fetchResumeStats({ vacancy_query: query, area, pages, per_page: perPage })
      ]);
      setData(analyze);
      setResumeStats(resumes);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="container">
      <h1>Аналитика вакансий</h1>
      <div className="meta">📍 Санкт-Петербург</div>

      <div className="controls">
        <CustomSelect
          value={query}
          onChange={setQuery}
          options={presets}
          placeholder="Выберите вакансию"
        />
        <button onClick={load} disabled={loading}>Найти</button>
      </div>

      {data && (
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

      {resumeStats && (
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
    </div>
  );
};