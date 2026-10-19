// Restaurant counter screen (/counter): a USB QR scanner such as Newland
// NLS-FR2780 works as a keyboard and "types" the member QR followed by Enter.
// This page keeps a focused input, submits on Enter (or when the code stops
// arriving), shows the result big enough to read from the counter, then
// clears itself for the next guest. One scan = one voucher; the server binds
// the QR's one-time nonce to the idempotency key, so a double scan never
// charges twice.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { counterResultView, extractMemberCode } from './counterScan.js';
import './counter.css';

const RESET_AFTER_MS = 4000;
const IDLE_SUBMIT_MS = 120;

export default function CounterScanApp({ supabase, apiBaseUrl }) {
  const [session, setSession] = useState(null), [booting, setBooting] = useState(true);
  useEffect(() => {
    if (!supabase) { setBooting(false); return undefined; }
    supabase.auth.getSession().then(({ data }) => { setSession(data.session); setBooting(false); });
    const { data } = supabase.auth.onAuthStateChange((_e, next) => setSession(next));
    return () => data.subscription.unsubscribe();
  }, [supabase]);
  if (booting) return <main className="counter-app counter-center">불러오는 중…</main>;
  if (!supabase || !apiBaseUrl) return <main className="counter-app counter-center">설정이 없어 사용할 수 없어요.</main>;
  if (!session) return <CounterLogin supabase={supabase} />;
  return <CounterScanner session={session} apiBaseUrl={apiBaseUrl} onLogout={() => supabase.auth.signOut()} />;
}

function CounterLogin({ supabase }) {
  const [email, setEmail] = useState(''), [password, setPassword] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('');
    const { error: err } = await supabase.auth.signInWithPassword({ email, password });
    if (err) setError('이메일 또는 비밀번호를 확인해 주세요.');
    setBusy(false);
  }
  return <main className="counter-app counter-center">
    <form className="counter-login" onSubmit={submit}>
      <img src="/brand/greeneat_logo_light.png" alt="그린잇" />
      <h1>식권 스캔 카운터</h1>
      <p>식당관리자 계정으로 로그인해 주세요.</p>
      <label>이메일<input type="email" autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} required /></label>
      <label>비밀번호<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required /></label>
      {error && <p role="alert">{error}</p>}
      <button disabled={busy}>로그인</button>
    </form>
  </main>;
}

function CounterScanner({ session, apiBaseUrl, onLogout }) {
  const input = useRef(null), idle = useRef(null), resetTimer = useRef(null), inFlight = useRef(false);
  const [state, setState] = useState({ kind: 'ready' }), [history, setHistory] = useState([]), [value, setValue] = useState('');
  const chime = useRef(typeof Audio !== 'undefined' ? new Audio('/audio/payment-success.mp3') : null);

  const focus = useCallback(() => { if (document.activeElement !== input.current) input.current?.focus({ preventScroll: true }); }, []);
  useEffect(() => {
    focus();
    const keep = setInterval(focus, 1000);
    window.addEventListener('click', focus);
    return () => { clearInterval(keep); window.removeEventListener('click', focus); };
  }, [focus]);

  async function redeem(raw) {
    const code = extractMemberCode(raw);
    setValue('');
    if (!code || inFlight.current) return;
    inFlight.current = true; clearTimeout(resetTimer.current);
    setState({ kind: 'busy' });
    let view;
    try {
      const response = await fetch(`${apiBaseUrl}/transactions/member-qr/redeem`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${session.access_token}` },
        body: JSON.stringify({ code }),
      });
      const payload = await response.json().catch(() => ({}));
      view = counterResultView(response.ok, payload);
    } catch {
      view = counterResultView(false, { detail: { code: 'NETWORK', message: '인터넷 연결을 확인하고 다시 찍어 주세요.' } });
    }
    inFlight.current = false;
    setState(view);
    if (view.kind === 'success') {
      try { chime.current.currentTime = 0; await chime.current.play(); } catch { /* browser may block audio until first click */ }
      setHistory(h => [{ at: new Date(), name: view.name, remaining: view.remaining, duplicate: view.duplicate }, ...h].slice(0, 8));
    }
    if (view.code === 'UNAUTHENTICATED') return;
    resetTimer.current = setTimeout(() => setState({ kind: 'ready' }), RESET_AFTER_MS);
    focus();
  }

  function onChange(e) {
    setValue(e.target.value);
    clearTimeout(idle.current);
    // Scanners configured without an Enter suffix: submit once input stops.
    idle.current = setTimeout(() => { if (extractMemberCode(e.target.value)) redeem(e.target.value); }, IDLE_SUBMIT_MS);
  }

  return <main className={`counter-app counter-${state.kind}`}>
    <header className="counter-head">
      <strong>식권 스캔 카운터</strong>
      <button type="button" onClick={onLogout}>로그아웃</button>
    </header>
    <section className="counter-stage" aria-live="assertive">
      {state.kind === 'ready' && <><div className="counter-icon" aria-hidden="true">▣</div><h1>손님 앱의 QR을 스캐너에 대 주세요</h1><p>앱 하단 <b>QR</b> 탭 → <b>내 QR 보여주기</b></p></>}
      {state.kind === 'busy' && <h1>확인 중…</h1>}
      {state.kind === 'success' && <><div className="counter-icon" aria-hidden="true">✓</div><h1>{state.title}</h1><p className="counter-name">{state.name}</p><p>{state.detail}</p></>}
      {state.kind === 'error' && <><div className="counter-icon" aria-hidden="true">!</div><h1>{state.title}</h1><p>{state.detail}</p>{state.code === 'UNAUTHENTICATED' && <button type="button" onClick={onLogout}>다시 로그인</button>}</>}
    </section>
    <form onSubmit={e => { e.preventDefault(); redeem(value); }} className="counter-input">
      <label htmlFor="counter-code">스캔 입력</label>
      <input id="counter-code" ref={input} value={value} onChange={onChange} onBlur={() => setTimeout(focus, 50)}
        autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false} inputMode="none" />
    </form>
    {history.length > 0 && <ol className="counter-history" aria-label="최근 사용">
      {history.map((h, i) => <li key={i}><time>{h.at.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time><span>{h.name}</span><span>{h.duplicate ? '중복 스캔' : `남은 식권 ${h.remaining ?? '—'}장`}</span></li>)}
    </ol>}
  </main>;
}
