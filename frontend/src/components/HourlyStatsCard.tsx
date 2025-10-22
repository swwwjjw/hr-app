import React from 'react';

export type HourlyRates = {
  min?: number | null;
  median?: number | null;
  avg?: number | null;
  max?: number | null;
  count?: number | null;
};

export const HourlyStatsCard: React.FC<{ hourly?: HourlyRates }> = ({ hourly }) => {
  const h = hourly || {};
  const fmt = (v?: number | null) => (typeof v === 'number' ? Math.round(v).toLocaleString('ru-RU') + ' ₽/ч' : '—');
  return (
    <div>
      <div className="grid4">
        <div className="miniCard"><div>Мин. ЧТС</div><b>{fmt(h.min)}</b></div>
        <div className="miniCard"><div>Медиана ЧТС</div><b>{fmt(h.median)}</b></div>
        <div className="miniCard"><div>Средняя ЧТС</div><b>{fmt(h.avg)}</b></div>
        <div className="miniCard"><div>Макс. ЧТС</div><b>{fmt(h.max)}</b></div>
      </div>
      <div className="meta" style={{ marginTop: 8 }}>
        {typeof h.count === 'number' && h.count > 0 ? `Основано на ${h.count} вакан${h.count % 10 === 1 && h.count % 100 !== 11 ? 'сии' : (h.count % 10 >= 2 && h.count % 10 <= 4 && (h.count % 100 < 10 || h.count % 100 >= 20)) ? 'сии' : 'сиях'}` : 'Недостаточно данных'}
      </div>
    </div>
  );
};
