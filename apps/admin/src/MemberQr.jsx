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

export default function MemberQr({ api, refresh, balance }) {
  const [state, setState] = useState({ kind: 'loading' }), [left, setLeft] = useState(0);
  const startBalance = useRef(balance), timer = useRef(null), poll = useRef(null), alive = useRef(true);

  async function load() {
    clearTimeout(timer.current);
    try {
      const data = await api('/transactions/member-qr');
      if (!alive.current) return;
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
      setState({ kind: 'used', remaining: balance });
    }
  }, [balance, state.kind]);

  useEffect(() => {
    if (state.kind !== 'ready') return undefined;
    const tick = () => setLeft(Math.max(0, Math.ceil((state.expiresAt - Date.now()) / 1000)));
    tick(); const id = setInterval(tick, 500);
    return () => clearInterval(id);
  }, [state]);

  if (state.kind === 'loading') return <section className="purchase-card member-qr" role="status">QR 만드는 중…</section>;
  if (state.kind === 'error') return <section className="purchase-card member-qr"><p role="alert">{state.message}</p><button onClick={load}>다시 만들기</button></section>;
  if (state.kind === 'used') return <section className="purchase-card member-qr member-qr-used" role="status">
    <span className="done-check" aria-hidden="true">✓</span><h2>식권 1장 사용 완료</h2><p>남은 식권 {state.remaining}장</p>
    <button onClick={() => { startBalance.current = balance; setState({ kind: 'loading' }); load(); poll.current = setInterval(() => refresh?.(), 4000); }}>QR 다시 보기</button>
  </section>;
  return <section className="purchase-card member-qr" aria-label="내 식권 QR">
    <div className="member-qr-code" role="img" aria-label="식권 사용 QR 코드" dangerouslySetInnerHTML={{ __html: state.svg }} />
    <p className="member-qr-help">카운터 스캐너에 화면을 대 주세요</p>
    <p className="member-qr-timer">{left > 0 ? `${left}초 후 새 QR로 바뀌어요` : '새 QR로 바꾸는 중…'}</p>
    <p className="muted">한 번 찍으면 식권 1장이 사용돼요. 화면을 캡처해서 쓸 수 없어요.</p>
  </section>;
}
