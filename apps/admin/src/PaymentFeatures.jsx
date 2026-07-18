import React, { useEffect, useState } from 'react';
import { BarChart3, CalendarDays, CheckCircle2, ChevronDown, RotateCcw, Search, X } from 'lucide-react';

const money = (value) => `₩${Number(value ?? 0).toLocaleString('ko-KR')}`;
const today = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });
const granularities = [['year', '연'], ['month', '월'], ['day', '일']];

function Chart({ series, label }) {
  const data = (Array.isArray(series) ? series : []).map((item, index) => ({
    label: String(item?.label ?? item?.period ?? item?.date ?? item?.time ?? index + 1),
    value: Number(item?.value ?? item?.amount ?? item?.total ?? item?.count ?? 0),
  }));
  if (!data.length) return <div className="history-chart-empty">표시할 그래프 데이터가 없어요.</div>;
  const max = Math.max(1, ...data.map((item) => Math.abs(item.value)));
  const x = (index) => data.length === 1 ? 50 : (index / (data.length - 1)) * 100;
  const y = (value) => 38 - (Math.max(0, value) / max) * 32;
  return <div className="history-chart" role="img" aria-label={`${label} 추이: ${data.map((item) => `${item.label} ${item.value.toLocaleString('ko-KR')}`).join(', ')}`}>
    <svg viewBox="0 0 100 42" preserveAspectRatio="none" aria-hidden="true"><line x1="0" y1="38" x2="100" y2="38" className="chart-axis"/><polyline points={data.map((item, index) => `${x(index)},${y(item.value)}`).join(' ')} className="chart-line"/>{data.map((item, index) => <circle key={`${item.label}-${index}`} cx={x(index)} cy={y(item.value)} r="1.4"/>)}</svg>
    <div className="history-chart-labels"><span>{data[0].label}</span><span>{data[data.length - 1].label}</span></div>
  </div>;
}

function Granularity({ value, onChange, label }) {
  return <div className="history-granularity" aria-label={`${label} 그래프 단위`}>{granularities.map(([id, text]) => <button type="button" key={id} className={value === id ? 'active' : ''} aria-pressed={value === id} onClick={() => onChange(id)}>{text}</button>)}</div>;
}

function Rows({ items, kind }) {
  const rows = Array.isArray(items) ? items : [];
  if (!rows.length) return <p className="history-list-empty">선택한 날짜의 내역이 없어요.</p>;
  return <div className="history-rows">{rows.map((item, index) => {
    const refunded = item.kind === 'refund' || item.status === 'refunded' || Number(item.refund_amount ?? 0) > 0;
    return <div className={`history-row${refunded ? ' is-refund' : ''}`} key={item.id ?? `${kind}-${index}`}><div><strong>{item.product_name ?? item.name ?? item.description ?? (refunded ? '환불' : kind === 'transaction' ? '거래' : '결제')}</strong><span>{item.created_at ? new Date(item.created_at).toLocaleString('ko-KR') : item.time ?? item.date ?? '-'}</span></div><div className="history-row-meta"><span>{item.customer_name ?? item.employee_name ?? item.pay_type ?? item.payment_method ?? ''}</span><b>{money(Math.abs(Number(item.amount ?? item.total ?? item.payment_amount ?? item.refund_amount ?? 0)))}</b></div></div>;
  })}</div>;
}

export function PaymentHistoryDashboard({ request, refreshKey }) {
  const [date, setDate] = useState(today());
  const [transactionGranularity, setTransactionGranularity] = useState('day');
  const [paymentGranularity, setPaymentGranularity] = useState('day');
  const [transaction, setTransaction] = useState({});
  const [payment, setPayment] = useState({});
  const [loading, setLoading] = useState({ transaction: true, payment: true });
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false; setLoading((s) => ({ ...s, transaction: true }));
    request(`/admin/merchant/payment-history?date=${encodeURIComponent(date)}&granularity=${transactionGranularity}`).then((data) => { if (!cancelled) { setTransaction(data?.transaction ?? {}); setError(''); } }).catch((e) => { if (!cancelled) setError(e.message); }).finally(() => { if (!cancelled) setLoading((s) => ({ ...s, transaction: false })); });
    return () => { cancelled = true; };
  }, [date, transactionGranularity, request, refreshKey]);
  useEffect(() => {
    let cancelled = false; setLoading((s) => ({ ...s, payment: true }));
    request(`/admin/merchant/payment-history?date=${encodeURIComponent(date)}&granularity=${paymentGranularity}`).then((data) => { if (!cancelled) { setPayment(data?.payment ?? {}); setError(''); } }).catch((e) => { if (!cancelled) setError(e.message); }).finally(() => { if (!cancelled) setLoading((s) => ({ ...s, payment: false })); });
    return () => { cancelled = true; };
  }, [date, paymentGranularity, request, refreshKey]);

  const dateLabel = new Date(`${date}T00:00:00`).toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' });
  return <section className="payment-history-dashboard" aria-labelledby="payment-history-title">
    <div className="history-heading"><div><span className="eyebrow">PAYMENT ANALYTICS</span><h2 id="payment-history-title">결제내역</h2><p>거래와 실결제 흐름을 단위별로 비교하고 날짜별 상세 내역을 확인합니다.</p></div><BarChart3 size={34}/></div>
    {error && <div className="alert error">결제내역을 불러오지 못했어요: {error}</div>}
    <div className="payment-history-grid">
      <article className="panel history-summary-card"><header><div><span>거래 합계</span><strong>{money(transaction.total)}</strong><small>{Number(transaction.count ?? 0).toLocaleString('ko-KR')}건</small></div><Granularity label="거래" value={transactionGranularity} onChange={setTransactionGranularity}/></header>{loading.transaction ? <div className="history-chart-empty">거래 그래프를 불러오는 중...</div> : <Chart series={transaction.series} label="거래 합계"/>}</article>
      <article className="panel history-summary-card payment-card"><header><div><span>결제 합계</span><strong>{money(payment.total)}</strong><small>{Number(payment.count ?? 0).toLocaleString('ko-KR')}건</small></div><Granularity label="결제" value={paymentGranularity} onChange={setPaymentGranularity}/></header>{loading.payment ? <div className="history-chart-empty">결제 그래프를 불러오는 중...</div> : <Chart series={payment.series} label="결제 합계"/>}</article>
      <article className="panel history-detail-card"><header><div><span>선택 날짜 거래 상세</span><strong>{Number(transaction.detail_count ?? (transaction.items ?? []).length).toLocaleString('ko-KR')}건</strong></div><b>{money((transaction.items ?? []).reduce((sum, item) => sum + Math.abs(Number(item.amount ?? 0)), 0))}</b></header><Rows items={transaction.items} kind="transaction"/></article>
      <article className="panel history-detail-card payment-detail-card"><header><div><span>선택 날짜 결제 · 환불 상세</span><strong>{Number(payment.detail_count ?? (payment.items ?? []).length).toLocaleString('ko-KR')}건</strong></div><div className="history-payment-totals"><small>기간 환불 {money(payment.refund_total)}</small><b>기간 순결제 {money(payment.total)}</b></div></header><Rows items={payment.items} kind="payment"/></article>
    </div>
    <footer className="history-date-dock"><div><CalendarDays size={22}/><span>조회 날짜</span><strong>{dateLabel}</strong></div><label>날짜 변경<input type="date" value={date} onChange={(event) => setDate(event.target.value)}/></label></footer>
  </section>;
}

function maskPhone(phone) {
  const value = String(phone ?? '');
  if (!value) return '연락처 없음';
  return value.replace(/(\d{3})-?(\d{3,4})-?(\d{4})/, (_, a, b, c) => `${a}-${'*'.repeat(b.length)}-${c}`);
}

export function RefundModal({ request, onClose, onRefunded }) {
  const [step, setStep] = useState('search');
  const [query, setQuery] = useState('');
  const [customers, setCustomers] = useState([]);
  const [customer, setCustomer] = useState(null);
  const [orders, setOrders] = useState([]);
  const [order, setOrder] = useState(null);
  const [account, setAccount] = useState({ bank: '', accountNumber: '', holderName: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function searchCustomers(event) {
    event.preventDefault(); if (!query.trim()) return; setBusy(true); setError('');
    try { const data = await request(`/admin/merchant/customers/search?query=${encodeURIComponent(query.trim())}`); setCustomers(Array.isArray(data) ? data : data?.items ?? data?.customers ?? []); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function chooseCustomer(item) {
    setCustomer(item); setBusy(true); setError('');
    try { const data = await request(`/admin/merchant/customers/${encodeURIComponent(item.id)}/refundable-orders`); setOrders(Array.isArray(data) ? data : data?.items ?? data?.orders ?? []); setStep('orders'); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function refund(manual = false) {
    if (!order) return; setBusy(true); setError('');
    const body = { order_id: order.purchase_order_id ?? order.id, account_id: order.account_id ?? customer?.account_id ?? customer?.id, ...(manual ? { refund_account: account } : {}) };
    try { await request('/admin/merchant/refunds', { method: 'POST', body: JSON.stringify(body) }); setStep('success'); await onRefunded(); }
    catch (e) { const marker = `${e.code ?? ''} ${e.message}`.toLowerCase(); if (!manual && (marker.includes('account') || marker.includes('계좌') || e.status === 422)) setStep('account'); else setError(e.message); }
    finally { setBusy(false); }
  }
  const amount = order?.refund_amount ?? 0;
  return <div className="modal-backdrop refund-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}><section className="refund-modal" role="dialog" aria-modal="true" aria-labelledby="refund-title">
    <header className="refund-modal-header"><div className="refund-modal-icon"><RotateCcw size={24}/></div><div><span className="eyebrow">GREENEAT REFUND</span><h2 id="refund-title">결제 환불</h2><p>{step === 'search' ? '고객을 검색해 환불 가능한 주문을 확인하세요.' : step === 'orders' ? `${customer?.name ?? customer?.display_name ?? '고객'} · ${maskPhone(customer?.masked_phone ?? customer?.phone)}` : step === 'confirm' ? '환불 내용을 마지막으로 확인해 주세요.' : step === 'account' ? '환불받을 계좌정보가 필요합니다.' : '환불 처리가 완료됐어요.'}</p></div><button className="icon-button" onClick={onClose} disabled={busy} aria-label="환불 창 닫기"><X size={20}/></button></header>
    <div className="refund-modal-body">{error && <div className="alert error">{error}</div>}
      {step === 'search' && <><form className="refund-search" onSubmit={searchCustomers}><label>고객 검색<input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="이름 또는 전화번호"/></label><button className="primary" disabled={busy || !query.trim()}><Search size={17}/>{busy ? '검색 중...' : '검색'}</button></form><div className="refund-customer-list">{customers.map((item) => <button type="button" className="refund-select-row" key={item.id} onClick={() => chooseCustomer(item)} disabled={busy}><span><strong>{item.name ?? item.display_name ?? '고객'}</strong><small>{maskPhone(item.masked_phone ?? item.phone)}</small></span><ChevronDown size={18}/></button>)}{!customers.length && query && !busy && <p className="history-list-empty">검색 결과가 없어요.</p>}</div></>}
            {step === 'orders' && <div className="refund-order-list">{!orders.length ? <p className="empty-state">환불 가능한 주문이 없어요.</p> : orders.map((item) => <button type="button" className="refund-order-card" key={item.purchase_order_id ?? item.id} onClick={() => { setOrder(item); setStep('confirm'); }}><div><strong>{item.product_name ?? item.name ?? '결제 상품'}</strong><span>{item.purchased_at || item.created_at ? new Date(item.purchased_at ?? item.created_at).toLocaleString('ko-KR') : '-'}</span></div><dl><div><dt>전체</dt><dd>{Number(item.total_count ?? 0)}장</dd></div><div><dt>사용</dt><dd>{Number(item.used_count ?? 0)}장</dd></div><div><dt>잔여</dt><dd>{Number(item.remaining_count ?? 0)}장</dd></div><div className="estimate"><dt>환불 예상</dt><dd>{money(item.refund_amount)}</dd></div>{Number(item.forfeited_bonus_count ?? 0) > 0 && <div><dt>회수 보너스</dt><dd>{Number(item.forfeited_bonus_count)}장</dd></div>}{Number(item.point_amount ?? 0) > 0 && <div className="point-refund"><dt>포인트 복원</dt><dd>{Number(item.point_amount).toLocaleString('ko-KR')} P</dd></div>}</dl></button>)}</div>}
            {step === 'confirm' && <div className="refund-confirm"><div className="refund-confirm-amount"><span>환불 예정 금액</span><strong>{money(amount)}</strong></div><div className="profile-grid"><span>고객</span><strong>{customer?.name ?? customer?.display_name ?? '-'}</strong><span>연락처</span><strong>{maskPhone(customer?.masked_phone ?? customer?.phone)}</strong><span>상품</span><strong>{order?.product_name ?? order?.name ?? '-'}</strong><span>전체 / 사용 / 잔여</span><strong>{Number(order?.total_count ?? 0)}장 / {Number(order?.used_count ?? 0)}장 / {Number(order?.remaining_count ?? 0)}장</strong><span>보너스 회수</span><strong>{Number(order?.forfeited_bonus_count ?? 0)}장</strong>{Number(order?.point_amount ?? 0) > 0 && <><span>포인트 복원</span><strong className="point-refund-text">{Number(order.point_amount).toLocaleString('ko-KR')} P</strong></>}</div><p className="refund-warning">환불 후에는 되돌릴 수 없습니다. 환불액과 보너스 회수 수량을 확인해 주세요.</p></div>}
            {step === 'account' && <form className="refund-account-form" onSubmit={(e) => { e.preventDefault(); refund(true); }}><div className="alert warning">등록된 환불 계좌가 없어 수동 계좌정보를 입력해야 합니다.</div><label>은행 코드<input value={account.bank} onChange={(e) => setAccount((s) => ({ ...s, bank: e.target.value }))} placeholder="예: 20 (우리은행)" required/></label><label>계좌번호<input value={account.accountNumber} onChange={(e) => setAccount((s) => ({ ...s, accountNumber: e.target.value }))} inputMode="numeric" placeholder="숫자만 입력" required/></label><label>예금주<input value={account.holderName} onChange={(e) => setAccount((s) => ({ ...s, holderName: e.target.value }))} required/></label><button className="primary" disabled={busy}>{busy ? '환불 처리 중...' : `${money(amount)} 환불하기`}</button></form>}
      {step === 'success' && <div className="refund-success"><CheckCircle2 size={54}/><h3>환불 완료</h3><strong>{money(amount)}</strong><p>결제내역 대시보드가 최신 정보로 갱신됐어요.</p></div>}
    </div>
    <footer className="refund-modal-footer">{step === 'orders' && <button className="ghost" onClick={() => setStep('search')}>고객 다시 찾기</button>}{step === 'confirm' && <><button className="ghost" onClick={() => setStep('orders')} disabled={busy}>이전</button><button className="primary" onClick={() => refund(false)} disabled={busy}>{busy ? '처리 중...' : '환불 확정'}</button></>}{step === 'success' && <button className="primary" onClick={onClose}>완료</button>}</footer>
  </section></div>;
}
