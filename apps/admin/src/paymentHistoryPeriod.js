export function paymentHistoryPeriod({ mode, current, date, month, range }) {
  const safeCurrent = String(current ?? '');
  const safeMonth = /^\d{4}-\d{2}$/.test(String(month ?? '')) ? String(month) : safeCurrent.slice(0, 7);
  const baseDate = mode === 'year'
    ? `${safeCurrent.slice(0, 4)}-01-01`
    : mode === 'month'
      ? `${safeMonth}-01`
      : mode === 'range'
        ? range.from
        : date;
  return {
    baseDate,
    granularity: mode === 'date' ? 'day' : mode,
    end: mode === 'range' ? `&end_date=${encodeURIComponent(range.to)}` : '',
    label: mode === 'year'
      ? `${safeCurrent.slice(0, 4)}년`
      : mode === 'month'
        ? `${Number(safeMonth.slice(5, 7))}월`
        : null,
  };
}
