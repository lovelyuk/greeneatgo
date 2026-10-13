import React from 'react';
import { Sun, Moon } from 'lucide-react';
import { dashboardTransactions, dashboardSummary } from './purchaseDashboard.js';
import { won } from './PurchaseCatalog.jsx';
function dateOf(row) {
  const date = row.created_at ? new Date(row.created_at) : null;
  return date && !Number.isNaN(date.valueOf()) ? date : null;
}
function dayLabel(date) {
  return date ? `${date.getMonth() + 1}월 ${date.getDate()}일 (${['일', '월', '화', '수', '목', '금', '토'][date.getDay()]})` : '날짜 정보 없음';
}
function UsageRow({ row }) {
  const date = dateOf(row), lunch = (date?.getHours() ?? 0) < 15, Icon = lunch ? Sun : Moon;
  const voucher = row.kind === 'voucher_use' || Object.hasOwn(row, 'voucher_id');
  const subtitle = `${lunch ? '중식' : '석식'}${date ? ` · ${date.getMonth() + 1}월 ${date.getDate()}일 ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}` : ''}`;
  return <article className="usage-row"><span className="usage-icon"><Icon size={18} aria-hidden="true" /></span><div><strong>{[row.merchant_name, row.title || '식대 사용'].filter(Boolean).join(' ')}</strong><p>{subtitle}{row.is_bonus ? ' · 보너스' : ''}</p></div><strong className="usage-amount">−{voucher ? '1장' : won(Math.abs(Number(row.amount) || 0))}</strong></article>;
}
export default function PurchaseHistory({ me, recent = false }) {
  const rows = dashboardTransactions(me), summary = dashboardSummary(rows);
  const groups = new Map();
  for (const row of (recent ? rows.slice(0, 3) : rows)) {
    const day = dayLabel(dateOf(row));
    if (!groups.has(day)) groups.set(day, []);
    groups.get(day).push(row);
  }
  return <section className="usage-history">
    {!recent && <><h1>이용내역</h1><p className="history-month">{new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long' })}</p><div className="usage-summary"><div><span>사용</span><strong>{summary.count}건</strong></div><div><span>금액</span><strong>{won(summary.amount)}</strong></div><div><span>내 부담</span><strong>{won(summary.amount)}</strong></div></div><p className="muted">현재 제공된 이용 내역 전체 · 월별 조회는 지원하지 않아요.</p></>}
    {!rows.length ? <p className="empty-state">아직 이용 내역이 없어요.<br />식당에서 QR로 첫 식사를 결제해 보세요.</p> : [...groups].map(([day, transactions]) => <div key={day}>{!recent && <h3 className="usage-day">{day}</h3>}{transactions.map(row => <UsageRow key={row.id} row={row} />)}</div>)}
  </section>;
}
