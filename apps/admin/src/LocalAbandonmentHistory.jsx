import React, { useEffect, useRef, useState } from 'react';
import { validLocalAbandonment } from './paymentClosure.js';

// Server history is authoritative. A local tombstone is not payment finality.
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
      setOrders(result.orders);
    } catch (e) {
      if (run === generation.current && !e.stale) {
        // Read-only: one automatic retry for a slow (cold-start) server.
        if (e.timeout && retry > 0) { locked.current = false; return load(retry - 1); }
        setOrders([]); setError(`중단한 주문 내역 확인 오류: ${e.message}`);
      }
    } finally {
      if (run === generation.current && locked.current) { locked.current = false; setBusy(false); }
    }
  }
  useEffect(() => {
    generation.current++; locked.current = false; setOrders([]); load();
    return () => { generation.current++; };
  }, [userId]);
  return <section className="purchase-card" aria-label="중단한 구매 주문">
    <h2>중단한 구매 주문</h2>
    <p>최근 20건 · 서비스 내 구매 중단이며 PG 취소·환불 확정이 아니에요. 기존 결제창은 다시 이용하지 마세요.</p>
    <button disabled={busy} onClick={() => load()}>중단한 주문 최신 상태 확인</button>
    {busy && <p role="status">중단한 주문 조회 중…</p>}
    {error && <p role="alert">{error} 위 버튼으로 조회만 다시 시도할 수 있어요.</p>}
    {!busy && !error && !orders.length && <p>중단한 구매 주문이 없어요.</p>}
    {orders.map(row => <article key={row.order_id}>
      <h3>{row.order_id}</h3><p>{row.amount.toLocaleString('ko-KR')}원 · {row.local_abandonment.source === 'manual_database_operator' ? '운영자 로컬 중단 판정' : '중단 접수'} {row.local_abandonment.requested_at}</p>
      {row.recovery_action === 'reconcile'
        ? <p role="alert">후속 승인 또는 불일치가 있어 실제 청구 재확인이 필요해요. 식권 발급·자동 환불하지 않았어요. 이 주문 번호로 관리자에게 확인해 주세요.</p>
        : <p>구매 진행 중단 접수 · PG 최종 결과 미확정. 후속 승인이 오면 재확인 내역으로 남아요.</p>}
    </article>)}
  </section>;
}
