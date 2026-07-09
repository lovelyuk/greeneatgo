export function mockSettlementRows(companyName, totalAmount) {
  const now = new Date();
  return [0, 1, 2].map((offset) => {
    const d = new Date(now.getFullYear(), now.getMonth() - offset, 1);
    const last = new Date(d.getFullYear(), d.getMonth() + 1, 0);
    const waiting = offset === 0;
    const overdue = offset === 1;
    return {
      id: `${companyName}-${offset}`,
      period_from: d.toISOString().slice(0, 10),
      period_to: last.toISOString().slice(0, 10),
      amount: Math.max(8000, Math.round((totalAmount || 96000) * (offset ? 0.82 + offset * 0.11 : 1))),
      status: waiting ? '입금대기' : overdue ? '연체' : '입금완료',
      paid_at: waiting || overdue ? '' : new Date(last.getFullYear(), last.getMonth() + 1, 5).toISOString().slice(0, 10),
    };
  });
}
