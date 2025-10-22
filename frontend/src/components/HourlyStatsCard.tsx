import React from 'react';

export type HourlyRates = {
  min?: number | null;
  median?: number | null;
  avg?: number | null;
  max?: number | null;
};

export const HourlyStatsCard: React.FC<{ hourly?: HourlyRates }> = ({ hourly }) => {
  const h = hourly || {};
  const fmt = (v?: number | null) => (typeof v === 'number' ? Math.round(v).toLocaleString('ru-RU') + ' ₽/ч' : '—');
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div className="miniCard"><div>Мин. ЧТС</div><b>{fmt(h.min)}</b></div>
        <div className="miniCard"><div>Медиана ЧТС</div><b>{fmt(h.median)}</b></div>
        <div className="miniCard"><div>Средняя ЧТС</div><b>{fmt(h.avg)}</b></div>
        <div className="miniCard"><div>Макс. ЧТС</div><b>{fmt(h.max)}</b></div>
      </div>
    </div>
  );
};
