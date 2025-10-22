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
    // Helper to compute monthly salary from an item
    const toMonthly = (i: Item): number | null => {
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
      return typeof monthly === 'number' ? monthly : null;
    };

    // Robust outlier filtering based on IQR (exclude extreme single values)
    const validMonthlyValues = (items || [])
      .map(toMonthly)
      .filter((v): v is number => typeof v === 'number' && v >= 13000);

    const sorted = validMonthlyValues.slice().sort((a, b) => a - b);
    const quantile = (arr: number[], p: number): number => {
      const pos = (arr.length - 1) * p;
      const base = Math.floor(pos);
      const rest = pos - base;
      if (arr[base + 1] !== undefined) return arr[base] + rest * (arr[base + 1] - arr[base]);
      return arr[base] ?? 0;
    };
    const q1 = sorted.length >= 4 ? quantile(sorted, 0.25) : null;
    const q3 = sorted.length >= 4 ? quantile(sorted, 0.75) : null;
    const iqr = q1 !== null && q3 !== null ? (q3 - q1) : null;
    const upperFence = iqr !== null ? (q3 as number) + 1.5 * iqr : Number.POSITIVE_INFINITY;

    const points = (items || [])
      .map((i) => {
        const monthly = toMonthly(i);
        const employerMark = typeof i?.employer_mark === 'number' ? (i.employer_mark as number) : null;
        if (monthly === null || employerMark === null || monthly < 13000) {
          return null;
        }
        // Filter out extreme outliers by salary
        if (monthly > upperFence) {
          return null;
        }
        return {
          x: monthly / 1000,
          y: employerMark,
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
            const d = ctx.raw as any;
            const salaryThs = Math.round(d?.x || 0);
            const rating = (d?.y ?? 0).toFixed ? (d.y as number).toFixed(1) : d?.y;
            return `${d?.title || ''} – ${d?.employer || ''}: ${salaryThs} тыс., рейтинг ${rating}`;
          },
        },
      },
    },
    scales: {
      x: { title: { display: true, text: 'Зарплата, тыс. ₽' } },
      y: { title: { display: true, text: 'Рейтинг работодателя' }, min: 0, max: 5 },
    },
  }), []);

  return <Bubble data={data} options={options as any} />;
};



