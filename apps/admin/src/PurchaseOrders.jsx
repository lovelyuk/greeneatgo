import React, { useEffect, useState } from 'react';
import { ChevronRight, ReceiptText } from 'lucide-react';
import PurchaseHistory, { MerchantChips } from './PurchaseHistory.jsx';
import { won } from './PurchaseCatalog.jsx';
import { completionLookupRows, validateReceiptUrl } from './receiptUtils.js';
import { formatKst, merchantNames, purchaseStatusLabel } from './purchaseExtras.js';

// 내역 tab: meals used (사용) and vouchers bought (구매). A bought row opens its
// receipt again (same paper receipt as right after payment). Mirrors the app's
// `_HistoryTab` + `PurchaseReceiptScreen`.

function ReceiptDialog({ api, orderId, onClose }) {
  const [state, setState] = useState({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setState({ status: 'loading' });
    api(`/payments/history/${encodeURIComponent(orderId)}`)
      .then(data => { if (live) setState(data?.completion ? { status: 'ready', data } : { status: 'error', message: '영수증을 불러오지 못했어요.' }); })
      .catch(error => { if (live) setState({ status: 'error', message: error?.message || '영수증을 불러오지 못했어요.' }); });
    return () => { live = false; };
  }, [api, orderId, attempt]);
  const data = state.data, completion = data?.completion, refund = data?.refund;
  const slip = validateReceiptUrl(completion?.receipts?.sales_slip_url), cash = validateReceiptUrl(completion?.receipts?.cash_receipt_url);
  const lookup = slip ? completionLookupRows(completion) : [];
  const card = [completion?.payment?.issuer_name, completion?.payment?.masked_card_number].filter(Boolean).join(' ');
  return <div className="done-overlay" onKeyDown={e => { if (e.key === 'Escape') onClose(); }}>
    <section className="purchase-card done-dialog receipt-dialog" role="dialog" aria-modal="true" aria-labelledby="receipt-title">
      <h2 id="receipt-title">결제 영수증</h2>
      {state.status === 'loading' && <p role="status" className="done-sub">영수증을 불러오는 중…</p>}
      {state.status === 'error' && <><p role="alert">{state.message}</p><button type="button" className="no-voucher-close" onClick={() => setAttempt(n => n + 1)}>다시 시도</button></>}
      {state.status === 'ready' && <>
        <p className="done-sub">{[data.summary?.merchant_name, data.summary?.product_name].filter(Boolean).join(' · ')}</p>
        {refund && <p className="receipt-refund" role="note">{refund.status === 'completed' ? '환불 완료된 결제예요' : '환불을 처리하고 있어요'}
          {Number.isSafeInteger(refund.refund_amount) && <span> · {won(refund.refund_amount)}</span>}
          {refund.status === 'completed' && refund.completed_at && <span> · {formatKst(refund.completed_at)}</span>}</p>}
        <div className="done-receipt">
          <p className="done-receipt-amount"><span>결제 금액</span><b>{Number(completion.amount).toLocaleString('ko-KR')}원</b></p>
          <div className="done-receipt-cut" aria-hidden="true" />
          <div className="done-rows">
            <p className="done-row"><span>결제수단</span> <b>{completion.payment?.method_label || completion.payment?.method || '정보 없음'}</b></p>
            {card && <p className="done-row"><span>카드</span> <b>{card}</b></p>}
            {completion.payment?.bank_name && <p className="done-row"><span>이용은행</span> <b>{completion.payment.bank_name}</b></p>}
            {completion.payment?.authorization_number && <p className="done-row"><span>승인번호</span> <b>{completion.payment.authorization_number}</b></p>}
            {Number.isSafeInteger(completion.pricing?.point_amount) && completion.pricing.point_amount > 0 && <p className="done-row"><span>사용 포인트</span> <b>{completion.pricing.point_amount.toLocaleString('ko-KR')}P</b></p>}
            <p className="done-row"><span>승인 시각</span> <b>{formatKst(completion.payment?.approved_at)}</b></p>
            <p className="done-row"><span>주문번호</span> <b>{completion.order_id}</b></p>
          </div>
        </div>
        <div className="done-links">
          {slip && <a target="_blank" rel="noopener noreferrer" href={slip}>{data.slip_title || '매출전표'} 보기</a>}
          {cash && <a target="_blank" rel="noopener noreferrer" href={cash}>현금영수증 보기</a>}
        </div>
        {lookup.length > 0 && <p className="done-lookup">매출전표는 키움페이 화면에 아래 값을 입력하면 열려요.<br />
          {lookup.map(({ label, value }) => <span key={label}>{label} <b>{value}</b></span>)}</p>}
      </>}
      <button className="done-ok" autoFocus onClick={onClose}>닫기</button>
    </section>
  </div>;
}

function Orders({ api, active }) {
  const [state, setState] = useState({ status: 'idle', items: [] });
  const [attempt, setAttempt] = useState(0);
  const [merchant, setMerchant] = useState(null), [open, setOpen] = useState(null);
  useEffect(() => {
    if (!active) return undefined;
    let live = true;
    setState(s => ({ ...s, status: 'loading' }));
    api('/payments/history')
      .then(data => { if (live) setState({ status: 'ready', items: Array.isArray(data?.items) ? data.items : [] }); })
      .catch(error => { if (live) setState({ status: 'error', items: [], message: error?.message || '구매 내역을 불러오지 못했어요.' }); });
    return () => { live = false; };
  }, [api, active, attempt]);
  const names = merchantNames(state.items);
  const rows = merchant ? state.items.filter(row => row.merchant_name === merchant) : state.items;
  return <>
    {state.status === 'loading' && !state.items.length && <p role="status">구매 내역 확인 중…</p>}
    {state.status === 'error' && <><p role="alert">{state.message}</p><button type="button" onClick={() => setAttempt(n => n + 1)}>다시 시도</button></>}
    {state.status === 'ready' && !state.items.length && <p className="empty-state">아직 구매 내역이 없어요.<br />식권을 구매하면 여기에서 영수증을 볼 수 있어요.</p>}
    <MerchantChips names={names} value={merchant} onChange={setMerchant} />
    <div className="order-list">{rows.map(row => {
      const status = purchaseStatusLabel(row.status);
      const detail = [row.merchant_name, formatKst(row.approved_at), row.method_label].filter(Boolean).join(' · ');
      return <button key={row.order_id} type="button" className={`order-row${status ? ' refunded' : ''}`} disabled={!row.has_receipt} onClick={() => setOpen(row.order_id)}
        aria-label={`${row.product_name || '식권 구매'} 영수증 보기`}>
        <span className="usage-icon"><ReceiptText size={18} aria-hidden="true" /></span>
        <span className="order-main"><strong>{row.product_name || '식권 구매'}{status && <em>{status}</em>}</strong><small>{detail}</small></span>
        <b>{won(row.amount)}</b>{row.has_receipt && <ChevronRight size={18} aria-hidden="true" />}
      </button>;
    })}</div>
    {open && <ReceiptDialog api={api} orderId={open} onClose={() => setOpen(null)} />}
  </>;
}

export default function HistoryPanel({ me, api, active }) {
  const [view, setView] = useState('usage');
  const segments = <div className="history-segments" role="tablist" aria-label="내역 종류">
    <button type="button" role="tab" aria-selected={view === 'usage'} onClick={() => setView('usage')}>사용</button>
    <button type="button" role="tab" aria-selected={view === 'orders'} onClick={() => setView('orders')}>구매</button>
  </div>;
  if (view === 'usage') return <PurchaseHistory me={me} header={segments} />;
  return <section className="usage-history"><h1>이용내역</h1>{segments}<Orders api={api} active={active} /></section>;
}
