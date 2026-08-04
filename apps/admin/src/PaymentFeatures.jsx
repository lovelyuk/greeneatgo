import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { CalendarDays, CheckCircle2, ChevronDown, ReceiptText, RotateCcw, Search, X } from 'lucide-react';
import { receiptApiPath, receiptTypeLabel, validateReceiptUrl } from './receiptUtils.js';
import { paymentHistoryPeriod } from './paymentHistoryPeriod.js';
import { paymentMethodLabel, refundButtonState } from './paymentHistoryDisplay.js';

const money = (value) => `₩${Number(value ?? 0).toLocaleString('ko-KR')}`;
const today = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });
const dateTime = (value) => {
  if (!value) return '-';
  const parts = Object.fromEntries(new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', year: '2-digit', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(value)).map((part) => [part.type, part.value]));
  return `${parts.year}.${parts.month}.${parts.day} ${parts.hour}:${parts.minute}`;
};
const periodModes = [['year', '올해'], ['month', '월별'], ['date', '날짜'], ['range', '기간']];

function Rows({ items, kind, onOpenReceipt, onRefund }) {
  const rows = Array.isArray(items) ? items : [];
  if (!rows.length) return <p className="history-list-empty">선택한 날짜의 내역이 없어요.</p>;
  return <div className="history-rows">{rows.map((item, index) => {
    const refundEntry = item.kind === 'refund' || Number(item.refund_amount ?? 0) > 0;
    const person = item.customer_name ?? item.employee_name ?? '-';
    const amount = item.is_bonus ? '0원' : money(Math.abs(Number(item.amount ?? item.total ?? item.payment_amount ?? item.refund_amount ?? 0)));
    if (kind === 'transaction') {
      const transactionType = item.pay_type === 'subsidized'
        ? { label: '보조금', tone: 'subsidized' }
        : item.pay_type === 'voucher' || item.company_name === '일반 고객'
          ? { label: item.is_bonus ? '식권 (보너스)' : '식권', tone: 'voucher' }
          : { label: '장부', tone: 'ledger' };
      return <div className="history-row history-row-columns history-row-transaction" key={item.id ?? `${kind}-${index}`}>
        <time dateTime={item.created_at}>{dateTime(item.created_at)}</time>
        <span className="history-company">{item.company_name ?? '일반 고객'}</span>
        <strong className="history-person">{person}</strong>
        <span className={`payment-type-badge ${transactionType.tone}`}>{transactionType.label}</span>
        <b>{amount}</b>
      </div>;
    }
    const paymentType = paymentMethodLabel(item);
    const receiptAvailable = Array.isArray(item.receipt?.types) && item.receipt.types.length > 0;
    const refundState = refundButtonState(item);
    return <div className={`history-row history-row-columns history-row-payment${refundEntry ? ' is-refund' : ''}`} key={item.id ?? `${kind}-${index}`}>
      <time dateTime={item.created_at}>{dateTime(item.created_at)}</time>
      <span className="history-product">{refundEntry ? '환불' : item.product_name ?? '상품'}</span>
      <strong className="history-person">{person}</strong>
      <span className="payment-type-badge">{paymentType}</span>
      <b>{amount}</b>
      <button
        type="button"
        className="receipt-trigger"
        disabled={!receiptAvailable}
        aria-label={receiptAvailable ? `${refundEntry ? '환불 원결제' : item.product_name ?? '결제'} 영수증 보기` : '조회 가능한 영수증 없음'}
        title={receiptAvailable ? '영수증 보기' : '조회 가능한 영수증이 없습니다'}
        onClick={(event) => receiptAvailable && onOpenReceipt(item.receipt, event.currentTarget)}
      ><ReceiptText size={14} aria-hidden="true"/><span>영수증</span></button>
      <button
        type="button"
        className="refund-row-trigger"
        disabled={refundState.disabled}
        aria-label={refundState.completed ? '환불 완료된 결제' : `${item.product_name ?? '결제'} 환불`}
        title={refundState.completed ? '이미 환불된 결제입니다' : refundState.disabled ? '환불할 수 없는 결제입니다' : '환불 처리'}
        onClick={(event) => !refundState.disabled && onRefund(item, event.currentTarget)}
      ><RotateCcw size={13} aria-hidden="true"/><span>{refundState.label}</span></button>
    </div>;
  })}</div>;
}

function ReceiptModal({ modal, onClose, onSelectType }) {
  const dialogRef = useRef(null);
  const closeRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const safeUrl = validateReceiptUrl(modal?.url);
  const descriptor = modal?.descriptor ?? {};
  const types = Array.isArray(descriptor.types) ? descriptor.types : [];

  useEffect(() => {
    const appRoot = document.getElementById('root');
    const previousInert = appRoot?.inert ?? false;
    const previousAriaHidden = appRoot?.getAttribute('aria-hidden');
    if (appRoot) {
      appRoot.inert = true;
      appRoot.setAttribute('aria-hidden', 'true');
    }
    const handleKey = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = [...dialogRef.current.querySelectorAll('button:not(:disabled), iframe, [href], input:not(:disabled), [tabindex]:not([tabindex="-1"])')];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleKey);
    closeRef.current?.focus();
    return () => {
      document.removeEventListener('keydown', handleKey);
      if (appRoot) {
        appRoot.inert = previousInert;
        if (previousAriaHidden == null) appRoot.removeAttribute('aria-hidden');
        else appRoot.setAttribute('aria-hidden', previousAriaHidden);
      }
    };
  }, []);

  const handleTabKey = (event, currentType) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key) || types.length < 2) return;
    event.preventDefault();
    const current = types.indexOf(currentType);
    const nextIndex = event.key === 'Home' ? 0
      : event.key === 'End' ? types.length - 1
        : (current + (event.key === 'ArrowRight' ? 1 : -1) + types.length) % types.length;
    const next = types[nextIndex];
    onSelectType(next);
    requestAnimationFrame(() => document.getElementById(`receipt-tab-${next}`)?.focus());
  };

  return createPortal(<div className="modal-backdrop receipt-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={dialogRef} className="receipt-modal" role="dialog" aria-modal="true" aria-labelledby="receipt-title">
      <header className="receipt-modal-header">
        <div><span className="eyebrow">PAYMENT RECEIPT</span><h2 id="receipt-title">{modal.title || receiptTypeLabel(modal.type, descriptor.source)}</h2></div>
        <button ref={closeRef} type="button" className="icon-button" onClick={onClose} aria-label="영수증 창 닫기"><X size={20}/></button>
      </header>
      {types.length > 1 && <div className="receipt-type-tabs" role="tablist" aria-label="영수증 종류">
        {types.map((type) => <button id={`receipt-tab-${type}`} type="button" role="tab" aria-controls="receipt-panel" aria-selected={modal.type === type} tabIndex={modal.type === type ? 0 : -1} className={modal.type === type ? 'active' : ''} key={type} onClick={() => onSelectType(type)} onKeyDown={(event) => handleTabKey(event, type)}>{receiptTypeLabel(type, descriptor.source)}</button>)}
      </div>}
      {descriptor.source === 'original_payment' && <div className="receipt-source-notice">환불 거래의 원결제 영수증입니다. 환불 완료 전표가 아닙니다.</div>}
      <div id="receipt-panel" className="receipt-modal-body" role={types.length > 1 ? 'tabpanel' : undefined} aria-labelledby={types.length > 1 ? `receipt-tab-${modal.type}` : undefined}>
        {modal.status === 'loading' && <p className="receipt-loading" role="status">영수증을 불러오는 중...</p>}
        {modal.status === 'error' && <div className="alert error" role="alert">{modal.error}</div>}
        {modal.status === 'ready' && safeUrl && <iframe className="receipt-frame" src={safeUrl} title={modal.title || '영수증'} referrerPolicy="no-referrer" sandbox="allow-scripts allow-forms allow-modals allow-same-origin"/>}
      </div>
      <footer className="receipt-modal-footer">
        <button type="button" className="ghost" onClick={onClose}>닫기</button>
      </footer>
    </section>
  </div>, document.body);
}

export function PaymentHistoryDashboard({ request }) {
  const current = today();
  const [mode, setMode] = useState('date');
  const [date, setDate] = useState(current);
  const [month, setMonth] = useState(current.slice(0, 7));
  const [range, setRange] = useState({ from: current, to: current });
  const [transaction, setTransaction] = useState({});
  const [payment, setPayment] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [receiptModal, setReceiptModal] = useState(null);
  const [refundTarget, setRefundTarget] = useState(null);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const receiptRequestId = useRef(0);
  const receiptTrigger = useRef(null);
  const refundTrigger = useRef(null);

  async function loadReceipt(descriptor, type) {
    const path = receiptApiPath(descriptor, type);
    if (!path) return;
    const requestId = ++receiptRequestId.current;
    setReceiptModal({ descriptor, type, status: 'loading', title: '', url: '', error: '' });
    try {
      const data = await request(path);
      if (requestId !== receiptRequestId.current) return;
      const url = validateReceiptUrl(data?.url);
      if (!url) throw new Error('허용되지 않은 영수증 주소입니다.');
      setReceiptModal({ descriptor, type, status: 'ready', title: data?.title ?? '', url, error: '' });
    } catch (receiptError) {
      if (requestId !== receiptRequestId.current) return;
      setReceiptModal({ descriptor, type, status: 'error', title: receiptTypeLabel(type, descriptor.source), url: '', error: receiptError.message });
    }
  }

  function openReceipt(descriptor, trigger) {
    receiptTrigger.current = trigger;
    const types = Array.isArray(descriptor?.types) ? descriptor.types : [];
    const preferred = types.includes('cash_receipt') ? 'cash_receipt' : types[0];
    if (preferred) loadReceipt(descriptor, preferred);
  }

  function closeReceipt() {
    receiptRequestId.current += 1;
    setReceiptModal(null);
    const trigger = receiptTrigger.current;
    receiptTrigger.current = null;
    requestAnimationFrame(() => trigger?.isConnected && trigger.focus());
  }

  function openRefund(item, trigger) {
    refundTrigger.current = trigger;
    setRefundTarget(item);
  }

  function closeRefund() {
    setRefundTarget(null);
    const trigger = refundTrigger.current;
    refundTrigger.current = null;
    requestAnimationFrame(() => trigger?.isConnected && trigger.focus());
  }

  async function handleRefunded() {
    setHistoryRefreshKey((key) => key + 1);
  }

  useEffect(() => {
    let cancelled = false;
    const { baseDate, granularity, end } = paymentHistoryPeriod({ mode, current, date, month, range });
    setLoading(true);
    request(`/admin/merchant/payment-history?date=${encodeURIComponent(baseDate)}&granularity=${granularity}${end}`).then((data) => {
      if (!cancelled) { setTransaction(data?.transaction ?? {}); setPayment(data?.payment ?? {}); setError(''); }
    }).catch((e) => { if (!cancelled) setError(e.message); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [mode, date, month, range.from, range.to, request, historyRefreshKey, current]);

  const period = paymentHistoryPeriod({ mode, current, date, month, range });
  const filterLabel = period.label ?? (mode === 'range' ? `${range.from} ~ ${range.to}` : new Date(`${date}T00:00:00`).toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' }));
  return <section className="payment-history-dashboard" aria-label="실시간 매출">
    <div className="history-heading"><div><span className="eyebrow">PAYMENT HISTORY</span><p>조회 기간을 선택해 거래와 결제·환불 상세 내역을 확인합니다.</p></div></div>
    <div className="history-period-filter">
      <div className="history-period-modes">{periodModes.map(([id, label]) => <button type="button" key={id} className={mode === id ? 'active' : ''} aria-pressed={mode === id} onClick={() => setMode(id)}>{label}</button>)}</div>
      <div className={`history-period-inputs ${mode === 'range' ? 'is-range' : 'is-single'}`}>
        {mode === 'date' && <label>조회 날짜<input type="date" value={date} onChange={(event) => setDate(event.target.value)}/></label>}
        {mode === 'month' && <label>조회 월<input type="month" value={month} onChange={(event) => setMonth(event.target.value)}/></label>}
        {mode === 'range' && <><label>시작일<input type="date" value={range.from} max={range.to} onChange={(event) => setRange((state) => ({ ...state, from: event.target.value }))}/></label><span>~</span><label>종료일<input type="date" value={range.to} min={range.from} onChange={(event) => setRange((state) => ({ ...state, to: event.target.value }))}/></label></>}
        <div className="history-period-label"><CalendarDays size={19}/><strong>{filterLabel}</strong></div>
      </div>
    </div>
    {error && <div className="alert error">결제내역을 불러오지 못했어요: {error}</div>}
    <div className="payment-history-grid is-detail-only">
      <article className="panel history-detail-card"><header><div><span>거래내역 및 총합</span><strong>{Number(transaction.detail_count ?? (transaction.items ?? []).length).toLocaleString('ko-KR')}건</strong></div><b>{money(transaction.total)}</b></header>{loading ? <p className="history-list-empty">거래내역을 불러오는 중...</p> : <Rows items={transaction.items} kind="transaction"/>}</article>
      <article className="panel history-detail-card payment-detail-card"><header><div><span>결제 · 환불 및 총합</span><strong>{Number(payment.detail_count ?? (payment.items ?? []).length).toLocaleString('ko-KR')}건</strong></div><div className="history-payment-totals"><small>환불 {money(payment.refund_total)}</small><b>순결제 {money(payment.total)}</b></div></header>{loading ? <p className="history-list-empty">결제내역을 불러오는 중...</p> : <Rows items={payment.items} kind="payment" onOpenReceipt={openReceipt} onRefund={openRefund}/>}</article>
    </div>
    {receiptModal && <ReceiptModal modal={receiptModal} onClose={closeReceipt} onSelectType={(type) => loadReceipt(receiptModal.descriptor, type)}/>}
    {refundTarget && <RefundModal request={request} initialPayment={refundTarget} onClose={closeRefund} onRefunded={handleRefunded}/>}
  </section>;
}
function maskPhone(phone) {
  const value = String(phone ?? '');
  if (!value) return '연락처 없음';
  return value.replace(/(\d{3})-?(\d{3,4})-?(\d{4})/, (_, a, b, c) => `${a}-${'*'.repeat(b.length)}-${c}`);
}

export function RefundModal({ request, onClose, onRefunded, initialPayment = null }) {
  const initialCustomer = initialPayment ? {
    id: initialPayment.user_id,
    account_id: initialPayment.user_id,
    name: initialPayment.customer_name ?? initialPayment.employee_name ?? '고객',
  } : null;
  const [step, setStep] = useState(initialPayment ? 'loading-order' : 'search');
  const [query, setQuery] = useState('');
  const [customers, setCustomers] = useState([]);
  const [customer, setCustomer] = useState(initialCustomer);
  const [orders, setOrders] = useState([]);
  const [order, setOrder] = useState(null);
  const [busy, setBusy] = useState(Boolean(initialPayment));
  const [error, setError] = useState('');
  useEffect(() => {
    if (!initialPayment) return undefined;
    let cancelled = false;
    const accountId = initialPayment.user_id;
    setBusy(true);
    setError('');
    request(`/admin/merchant/customers/${encodeURIComponent(accountId)}/refundable-orders`).then((data) => {
      if (cancelled) return;
      const items = Array.isArray(data) ? data : data?.items ?? data?.orders ?? [];
      const match = items.find((item) => String(item.purchase_order_id ?? item.id) === String(initialPayment.order_id));
      setOrders(items);
      if (match) {
        setOrder(match);
        setStep('confirm');
      } else {
        setError('남아 있는 환불 가능 식권이 없는 결제입니다.');
        setStep('orders');
      }
    }).catch((loadError) => {
      if (!cancelled) {
        setError(loadError.message);
        setStep('orders');
      }
    }).finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [initialPayment, request]);

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
  async function refund() {
    if (!order) return; setBusy(true); setError('');
    const body = { order_id: order.purchase_order_id ?? order.id, account_id: order.account_id ?? customer?.account_id ?? customer?.id };
    try { await request('/admin/merchant/refunds', { method: 'POST', body: JSON.stringify(body) }); setStep('success'); await onRefunded?.(); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  const amount = order?.refund_amount ?? 0;
  return <div className="modal-backdrop refund-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}><section className="refund-modal" role="dialog" aria-modal="true" aria-labelledby="refund-title">
    <header className="refund-modal-header"><div className="refund-modal-icon"><RotateCcw size={24}/></div><div><span className="eyebrow">GREENEAT REFUND</span><h2 id="refund-title">결제 환불</h2><p>{step === 'loading-order' ? '선택한 결제의 환불 가능 금액을 확인하고 있어요.' : step === 'search' ? '고객을 검색해 환불 가능한 주문을 확인하세요.' : step === 'orders' ? `${customer?.name ?? customer?.display_name ?? '고객'} · ${maskPhone(customer?.masked_phone ?? customer?.phone)}` : step === 'confirm' ? '환불 내용을 마지막으로 확인해 주세요.' : '환불 처리가 완료됐어요.'}</p></div><button className="icon-button" onClick={onClose} disabled={busy} aria-label="환불 창 닫기"><X size={20}/></button></header>
    <div className="refund-modal-body">{error && <div className="alert error">{error}</div>}
      {step === 'loading-order' && <p className="history-list-empty" role="status">환불 가능 주문을 확인하는 중...</p>}
      {step === 'search' && <><form className="refund-search" onSubmit={searchCustomers}><label>고객 검색<input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="이름 또는 전화번호"/></label><button className="primary" disabled={busy || !query.trim()}><Search size={17}/>{busy ? '검색 중...' : '검색'}</button></form><div className="refund-customer-list">{customers.map((item) => <button type="button" className="refund-select-row" key={item.id} onClick={() => chooseCustomer(item)} disabled={busy}><span><strong>{item.name ?? item.display_name ?? '고객'}</strong><small>{maskPhone(item.masked_phone ?? item.phone)}</small></span><ChevronDown size={18}/></button>)}{!customers.length && query && !busy && <p className="history-list-empty">검색 결과가 없어요.</p>}</div></>}
            {step === 'orders' && <div className="refund-order-list">{!orders.length ? <p className="empty-state">환불 가능한 주문이 없어요.</p> : orders.map((item) => <button type="button" className="refund-order-card" key={item.purchase_order_id ?? item.id} onClick={() => { setOrder(item); setStep('confirm'); }}><div><strong>{item.product_name ?? item.name ?? '결제 상품'}</strong><span>{item.purchased_at || item.created_at ? new Date(item.purchased_at ?? item.created_at).toLocaleString('ko-KR') : '-'}</span></div><dl><div><dt>전체</dt><dd>{Number(item.total_count ?? 0)}장</dd></div><div><dt>사용</dt><dd>{Number(item.used_count ?? 0)}장</dd></div><div><dt>잔여</dt><dd>{Number(item.remaining_count ?? 0)}장</dd></div><div className="estimate"><dt>환불 예상</dt><dd>{money(item.refund_amount)}</dd></div>{Number(item.forfeited_bonus_count ?? 0) > 0 && <div><dt>회수 보너스</dt><dd>{Number(item.forfeited_bonus_count)}장</dd></div>}{Number(item.point_amount ?? 0) > 0 && <div className="point-refund"><dt>포인트 복원</dt><dd>{Number(item.point_amount).toLocaleString('ko-KR')} P</dd></div>}</dl></button>)}</div>}
            {step === 'confirm' && <div className="refund-confirm"><div className="refund-confirm-amount"><span>환불 예정 금액</span><strong>{money(amount)}</strong></div><div className="profile-grid"><span>고객</span><strong>{customer?.name ?? customer?.display_name ?? '-'}</strong><span>연락처</span><strong>{maskPhone(customer?.masked_phone ?? customer?.phone)}</strong><span>상품</span><strong>{order?.product_name ?? order?.name ?? '-'}</strong><span>전체 / 사용 / 잔여</span><strong>{Number(order?.total_count ?? 0)}장 / {Number(order?.used_count ?? 0)}장 / {Number(order?.remaining_count ?? 0)}장</strong><span>보너스 회수</span><strong>{Number(order?.forfeited_bonus_count ?? 0)}장</strong>{Number(order?.point_amount ?? 0) > 0 && <><span>포인트 복원</span><strong className="point-refund-text">{Number(order.point_amount).toLocaleString('ko-KR')} P</strong></>}</div><p className="refund-warning">환불 후에는 되돌릴 수 없습니다. 환불액과 보너스 회수 수량을 확인해 주세요.</p></div>}
      {step === 'success' && <div className="refund-success"><CheckCircle2 size={54}/><h3>환불 완료</h3><strong>{money(amount)}</strong><p>결제내역 대시보드가 최신 정보로 갱신됐어요.</p></div>}
    </div>
    <footer className="refund-modal-footer">{step === 'orders' && (initialPayment ? <button className="ghost" onClick={onClose}>닫기</button> : <button className="ghost" onClick={() => setStep('search')}>고객 다시 찾기</button>)}{step === 'confirm' && <>{!initialPayment && <button className="ghost" onClick={() => setStep('orders')} disabled={busy}>이전</button>}<button className="primary" onClick={refund} disabled={busy}>{busy ? '처리 중...' : '환불 확정'}</button></>}{step === 'success' && <button className="primary" onClick={onClose}>완료</button>}</footer>
  </section></div>;
}
