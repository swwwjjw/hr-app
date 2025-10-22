import axios from 'axios';

const api = axios.create({ baseURL: '/api' });

export async function fetchAnalyze(params: { query: string; area?: number | string; pages?: number; per_page?: number }) {
  const res = await api.get('/analyze', { params });
  return res.data;
}

export async function fetchResumeStats(params: { vacancy_query: string; area?: number | string; pages?: number; per_page?: number }) {
  const res = await api.get('/resume-stats', { params });
  return res.data;
}

export async function fetchSimplifiedVacancies(params: {
  query: string;
  area?: number | string;
  pages?: number;
  per_page?: number;
  employer_mark?: boolean;
  fetch_all?: boolean;
}): Promise<{ count: number; items: any[] }> {
  const res = await api.get('/fetch', {
    params: {
      ...params,
      simplified: true,
      // By default fetch all available pages for more complete stats
      fetch_all: params.fetch_all ?? true,
    },
  });
  return res.data;
}



