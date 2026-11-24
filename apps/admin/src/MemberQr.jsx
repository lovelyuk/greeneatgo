// Buyer's "내 QR" for the counter scanner. Fetches a 60-second signed code from
// the server, draws it locally (no third-party QR image service), and refreshes
// before expiry. When the voucher balance drops (the counter used it), it shows
// a used confirmation and stops refreshing until the buyer opens it again.
import React, { useEffect, useRef, useState } from 'react';
import qrcode from 'qrcode-generator';

export function memberQrSvg(code) {
  const qr = qrcode(0, 'M');
  qr.addData(code, 'Numeric');
  qr.make();
  return qr.createSvgTag({ cellSize: 8, margin: 4, scalable: true });
}

/** Most vouchers one scan may use: what the buyer holds, never more than 10, at least 1. */
export function maxQuantity(balance) {
  return Number.isSafeInteger(balance) ? Math.max(1, Math.min(10, balance)) : 1;
}

export default function MemberQr({ api, refresh, balance }) {
  const [state, setState] = useState({ kind: 'loading' }), [left, setLeft] = useState(0);
  const [quantity, setQuantity] = useState(1);
  const startBalance = useRef(balance), timer = useRef(null), poll = useRef(null), alive = useRef(true);
  const wanted = useRef(1);
  const most = maxQuantity(startBalance.current);

  function pick(next) {
    const value = Math.max(1, Math.min(most, next));
    if (value === wanted.current) return;
    wanted.current = value; setQuantity(value);
    setState({ kind: 'loading' }); load();   // the count is inside the code, so make a new one
  }

  async function load() {
    clearTimeout(timer.current);
    const asked = wanted.current;
    try {
      const data = await api(asked > 1 ? `/transactions/member-qr?quantity=${asked}` : '/transactions/member-qr');
      if (!alive.current || asked !== wanted.current) return;
      if (typeof data?.code !== 'string' || !/^\d{81}$/.test(data.code)) throw new Error('QR을 만들지 못했어요.');
      setState({ kind: 'ready', code: data.code, svg: memberQrSvg(data.code), expiresAt: data.expires_at * 1000 });
      timer.current = setTimeout(load, Math.max(5000, (data.ttl - 10) * 1000));
    } catch (e) {
      if (alive.current && !e.stale) setState({ kind: 'error', message: e.message || 'QR을 만들지 못했어요.' });
    }
  }

  useEffect(() => {
    alive.current = true; startBalance.current = balance; load();
    // Watch the balance so the buyer sees the counter's redemption.
    poll.current = setInterval(() => { refresh?.(); }, 4000);
    return () => { alive.current = false; clearTimeout(timer.current); clearInterval(poll.current); };
  }, []);

  useEffect(() => {
    if (state.kind === 'ready' && Number.isSafeInteger(balance) && Number.isSafeInteger(startBalance.current) && balance < startBalance.current) {
      clearTimeout(timer.current); clearInterval(poll.current);
      setState({ kind: 'used', remaining: balance, used: startBalance.current - balance });
    }
  }, [balance, state.kind]);

  useEffect(() => {
    if (state.kind !== 'ready') return undefined;
    const tick = () => setLeft(Math.max(0, Math.ceil((state.expiresAt - Date.now()) / 1000)));
    tick(); const id = setInterval(tick, 500);
    return () => clearInterval(id);
  }, [state]);

  const stepper = most > 1 && <div className="member-qr-quantity" role="group" aria-label="사용할 식권 수">
    <button type="button" aria-label="한 장 줄이기" disabled={quantity <= 1} onClick={() => pick(quantity - 1)}>−</button>
    <strong aria-live="polite">{quantity}장</strong>
    <button type="button" aria-label="한 장 늘리기" disabled={quantity >= most} onClick={() => pick(quantity + 1)}>+</button>
  </div>;
  if (state.kind === 'loading') return <section className="purchase-card member-qr" role="status">{stepper}QR 만드는 중…</section>;
  if (state.kind === 'error') return <section className="purchase-card member-qr"><p role="alert">{state.message}</p><button onClick={load}>다시 만들기</button></section>;
  if (state.kind === 'used') return <section className="purchase-card member-qr member-qr-used" role="status">
    <span className="done-check" aria-hidden="true">✓</span><h2>식권 {state.used}장 사용 완료</h2><p>남은 식권 {state.remaining}장</p>
    <button onClick={() => { startBalance.current = balance; wanted.current = 1; setQuantity(1); setState({ kind: 'loading' }); load(); poll.current = setInterval(() => refresh?.(), 4000); }}>QR 다시 보기</button>
  </section>;
  return <section className="purchase-card member-qr" aria-label="내 식권 QR">
    {stepper}
    <div className="member-qr-code" role="img" aria-label="식권 사용 QR 코드" dangerouslySetInnerHTML={{ __html: state.svg }} />
    <p className="member-qr-help">카운터 스캐너에 화면을 대 주세요</p>
    <p className="member-qr-timer">{left > 0 ? `${left}초 후 새 QR로 바뀌어요` : '새 QR로 바꾸는 중…'}</p>
    <p className="muted">한 번 찍으면 식권 {quantity}장이 사용돼요. 화면을 캡처해서 쓸 수 없어요.</p>
  </section>;
}
