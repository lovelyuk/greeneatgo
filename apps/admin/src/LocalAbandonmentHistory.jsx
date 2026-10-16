import React, { useEffect, useRef, useState } from 'react';
import { validLocalAbandonment } from './paymentClosure.js';

const kst = stamp => {
  const date = new Date(stamp);
  return Number.isFinite(date.getTime())
    ? date.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
    : '';
};

// Server history is authoritative. Ordinary cancelled purchases are not shown;
// only a cancelled order that later received a real approval (reconcile) needs
// the buyer's attention.
export default function LocalAbandonmentHistory({ api, userId }) {
  const [orders, setOrders] = useState([]), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const generation = useRef(0), locked = useRef(false);
  async function load(retry = 1) {
    if (locked.current) return;
    locked.current = true;
    const run = generation.current;
    setBusy(true); setError('');
    try {
      const result = await api('/payments/local-abandonments?limit=20', undefined, { readTimeoutMs: 30000 });
      if (run !== generation.current) return;
      const ids = new Set();
      if (!Array.isArray(result?.orders) || result.orders.length > 20 || result.orders.some(row => {
        if (!validLocalAbandonment(row, row, userId, { history: true }) || ids.has(row.order_id)) return true;
        ids.add(row.order_id); return false;
      })) throw new Error('주문 내역 응답을 확인하지 못했어요.');
      setOrders(result.orders.filter(row => row.recovery_action === 'reconcile'));
    } catch (e) {
      if (run === generation.current && !e.stale) {
        // Read-only: one automatic retry for a slow (cold-start) server.
        if (e.timeout && retry > 0) { locked.current = false; return load(retry - 1); }
        setOrders([]); setError(e.message);
      }
    } finally {
      if (run === generation.current && locked.current) { locked.current = false; setBusy(false); }
    }
  }
  useEffect(() => {
    generation.current++; locked.current = false; setOrders([]); load();
    return () => { generation.current++; };
  }, [userId]);
  if (!orders.length && !error) return null;
  return <section className="purchase-card" aria-label="결제 확인이 필요한 주문">
    <h2>결제 확인이 필요한 주문</h2>
    {error ? <><p role="alert">취소한 주문의 결제 여부를 확인하지 못했어요. {error}</p><button disabled={busy} onClick={() => load()}>다시 확인</button></> : <>
      <p>구매를 취소했지만 이후 결제가 승인된 주문이에요. 식권 발급·환불이 자동으로 처리되지 않았으니 관리자에게 아래 주문번호로 확인을 요청해 주세요.</p>
      {orders.map(row => <article key={row.order_id}>
        <h3>{row.amount.toLocaleString('ko-KR')}원 · {kst(row.local_abandonment.requested_at)}</h3>
        <p className="muted">주문번호 {row.order_id}</p>
      </article>)}
    </>}
  </section>;
}
