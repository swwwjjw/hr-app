import React, { useMemo } from 'react';
import { Bubble } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  Tooltip,
  Legend,
  LinearScale,
  PointElement,
  Title,
} from 'chart.js';

ChartJS.register(Tooltip, Legend, LinearScale, PointElement, Title);

type SalaryRange = {
  from?: number | null;
  to?: number | null;
};

type Item = {
  salary_avg?: number | null;
  salary?: SalaryRange | null;
  salary_estimated_monthly?: number | null;
  salary_per_shift?: boolean | null;
  employer_mark?: number | null;
  title?: string;
  employer_name?: string;
};

export const SalaryBubbleChart: React.FC<{ items: Item[] }> = ({ items }) => {
  const data = useMemo(() => {
    const points = (items || [])
      .map((i) => {
        // Compute monthly salary value, converting per-shift to monthly when available
        let monthly: number | null = null;
        if (i?.salary_per_shift === true) {
          if (typeof i?.salary_estimated_monthly === 'number') {
            monthly = i.salary_estimated_monthly as number;
          }
        } else if (typeof i?.salary_avg === 'number') {
          monthly = i.salary_avg as number;
        }
        if (monthly === null && i?.salary && typeof i.salary === 'object') {
          const sf = typeof i.salary.from === 'number' ? (i.salary.from as number) : null;
          const st = typeof i.salary.to === 'number' ? (i.salary.to as number) : null;
          if (sf !== null && st !== null) monthly = (sf + st) / 2;
          else if (sf !== null) monthly = sf;
          else if (st !== null) monthly = st;
        }

        const employerMark = typeof i?.employer_mark === 'number' ? (i.employer_mark as number) : null;
        if (monthly === null || employerMark === null || monthly < 10000) {
          return null;
        }
        return {
          x: employerMark,
          y: monthly / 1000,
          r: 6,
          title: i.title,
          employer: i.employer_name,
        };
      })
      .filter((p): p is { x: number; y: number; r: number; title?: string; employer?: string } => Boolean(p));

    return {
      datasets: [
        {
          label: 'Вакансии',
          data: points as any,
          backgroundColor: 'rgba(37, 99, 235, 0.5)',
          borderColor: 'rgba(37, 99, 235, 1)',
        },
      ],
    };
  }, [items]);

  const options = useMemo(() => ({
    responsive: true,
    plugins: {
      legend: { display: false },
      title: { display: false, text: '' },
      tooltip: {
        callbacks: {
          label: (ctx: any) => {
            const d = ctx.raw;
            return `${d?.title || ''} – ${d?.employer || ''}: ${Math.round((d?.y || 0))} тыс.`;
          },
        },
      },
    },
    scales: {
      x: { title: { display: true, text: 'Рейтинг работодателя' }, min: 0, max: 5 },
      y: { title: { display: true, text: 'Зарплата, тыс. ₽' } },
    },
  }), []);

  return <Bubble data={data} options={options as any} />;
};



