// Restaurant counter screen (/counter): a USB QR scanner such as Newland
// NLS-FR2780 works as a keyboard and "types" the member QR followed by Enter.
// This page keeps a focused input, submits on Enter (or when the code stops
// arriving), shows the result big enough to read from the counter, then
// clears itself for the next guest. One scan = one voucher; the server binds
// the QR's one-time nonce to the idempotency key, so a double scan never
// charges twice.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { classifyScan, counterResultView } from './counterScan.js';
import { installCounterManifest, keepScreenAwake, unlockAudio, LOGOUT_HOLD_MS } from './counterKiosk.js';
import './counter.css';

const RESET_AFTER_MS = 4000;
const IDLE_SUBMIT_MS = 120;

export default function CounterScanApp({ supabase, apiBaseUrl }) {
  const [session, setSession] = useState(null), [booting, setBooting] = useState(true);
  // Installable full-screen app (Android: Chrome → 홈 화면에 추가 / 앱 설치).
  useEffect(() => installCounterManifest(), []);
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

// Press and hold (1.5 s) so a stray tap at the counter cannot log out.
function HoldButton({ onHold, label, hint }) {
  const timer = useRef(null), [holding, setHolding] = useState(false);
  const start = e => { e.preventDefault(); setHolding(true); timer.current = setTimeout(() => { setHolding(false); onHold(); }, LOGOUT_HOLD_MS); };
  const stop = () => { clearTimeout(timer.current); setHolding(false); };
  useEffect(() => () => clearTimeout(timer.current), []);
  return <button type="button" className={`counter-hold ${holding ? 'holding' : ''}`} aria-label={hint} title={hint}
    onPointerDown={start} onPointerUp={stop} onPointerLeave={stop} onPointerCancel={stop}
    onKeyDown={e => { if ((e.key === 'Enter' || e.key === ' ') && !e.repeat) start(e); }} onKeyUp={stop}
    style={{ '--hold-ms': `${LOGOUT_HOLD_MS}ms` }}>
    <span className="counter-hold-fill" aria-hidden="true" />{label}
  </button>;
}

// Idle screen: guidance on the left, a looping phone demo on the right that
// replays the guest's real path (홈 → QR 탭 → 내 QR → 스캐너 → 사용 완료).
// The demo QR is scrambled so the scanner can never read the picture.
function ReadyGuide() {
  return <div className="counter-ready-layout">
    <div className="counter-guide">
      <p className="counter-over">어서 오세요!</p>
      <h1>QR은<br />스캐너에 대 주세요</h1>
      <ol className="counter-steps" aria-label="사용 방법">
        <li className="s1">앱 홈에서 <b>QR</b> 탭</li>
        <li className="s2"><b>내 QR</b> 화면 열기</li>
        <li className="s3">스캐너에 화면 대기</li>
      </ol>
      <p className="counter-down"><span aria-hidden="true">↓</span>스캐너는 화면 아래에 있어요</p>
    </div>
    <div className="counter-demo" aria-hidden="true">
      <div className="demo-phone">
        <div className="demo-screen">
          <img className="d-home" src="/counter/demo-1-home.jpg" alt="" />
          <img className="d-qr" src="/counter/demo-2-qr.jpg" alt="" />
          <img className="d-used" src="/counter/demo-3-used.jpg" alt="" />
          <span className="d-tap" />
          <span className="d-beam" />
        </div>
      </div>
      <div className="demo-scanner"><span className="demo-light" /></div>
    </div>
  </div>;
}

function CounterScanner({ session, apiBaseUrl, onLogout }) {
  const input = useRef(null), idle = useRef(null), resetTimer = useRef(null), inFlight = useRef(false);
  const [state, setState] = useState({ kind: 'ready' }), [history, setHistory] = useState([]), [value, setValue] = useState('');
  const chime = useRef(typeof Audio !== 'undefined' ? new Audio('/audio/payment-success.mp3') : null);
  const [online, setOnline] = useState(typeof navigator === 'undefined' ? true : navigator.onLine !== false);
  const [soundBlocked, setSoundBlocked] = useState(false);
  const [wake, setWake] = useState('pending');

  // Kiosk: keep the tablet screen on, watch the connection, check the chime.
  useEffect(() => keepScreenAwake({ onChange: setWake }), []);
  useEffect(() => {
    const up = () => setOnline(true), down = () => setOnline(false);
    window.addEventListener('online', up); window.addEventListener('offline', down);
    return () => { window.removeEventListener('online', up); window.removeEventListener('offline', down); };
  }, []);
  useEffect(() => { unlockAudio(chime.current).then(ok => setSoundBlocked(!ok)); }, []);
  async function enableSound() {
    const ok = await unlockAudio(chime.current);
    setSoundBlocked(!ok);
    focus();
  }

  const focus = useCallback(() => { if (document.activeElement !== input.current) input.current?.focus({ preventScroll: true }); }, []);
  useEffect(() => {
    focus();
    const keep = setInterval(focus, 1000);
    window.addEventListener('click', focus);
    return () => { clearInterval(keep); window.removeEventListener('click', focus); };
  }, [focus]);

  async function redeem(raw) {
    const scan = classifyScan(raw);
    setValue('');
    if (!scan || inFlight.current) return;
    const code = scan.code;
    const endpoint = scan.kind === 'kiosk' ? 'kiosk-receipt/redeem' : 'member-qr/redeem';
    inFlight.current = true; clearTimeout(resetTimer.current);
    setState({ kind: 'busy' });
    let view;
    try {
      const response = await fetch(`${apiBaseUrl}/transactions/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${session.access_token}` },
        body: JSON.stringify({ code }),
      });
      const payload = await response.json().catch(() => ({}));
      view = counterResultView(response.ok, payload);
      setOnline(true);
    } catch {
      setOnline(navigator.onLine !== false);
      view = counterResultView(false, { detail: { code: 'NETWORK', message: '인터넷 연결을 확인하고 다시 찍어 주세요.' } });
    }
    inFlight.current = false;
    setState(view);
    if (view.kind === 'success') {
      try { chime.current.currentTime = 0; await chime.current.play(); setSoundBlocked(false); } catch { setSoundBlocked(true); }
      setHistory(h => [{ at: new Date(), name: view.name, remaining: view.remaining, duplicate: view.duplicate, receipt: view.receipt }, ...h].slice(0, 8));
    }
    if (view.code === 'UNAUTHENTICATED') return;
    resetTimer.current = setTimeout(() => setState({ kind: 'ready' }), RESET_AFTER_MS);
    focus();
  }

  function onChange(e) {
    setValue(e.target.value);
    clearTimeout(idle.current);
    // Scanners configured without an Enter suffix: submit once input stops.
    idle.current = setTimeout(() => { if (classifyScan(e.target.value)) redeem(e.target.value); }, IDLE_SUBMIT_MS);
  }

  return <main className={`counter-app counter-${state.kind}`}>
    <header className="counter-head">
      <strong>식권 스캔 카운터</strong>
      <div className="counter-head-right">
        <span className={`counter-net ${online ? 'on' : 'off'}`} role="status" aria-label={online ? '인터넷 연결됨' : '인터넷 연결 끊김'}><i aria-hidden="true" />{online ? '연결됨' : '연결 끊김'}</span>
        {wake === 'off' && <span className="counter-net warn" title="화면 꺼짐 방지가 해제됐어요">화면 꺼짐 주의</span>}
        <HoldButton onHold={onLogout} label="로그아웃" hint="길게 눌러 로그아웃" />
      </div>
    </header>
    {!online && <div className="counter-banner offline" role="alert">인터넷 연결이 끊겼어요. 와이파이를 확인해 주세요. 연결되면 자동으로 다시 찍을 수 있어요.</div>}
    {online && soundBlocked && <button type="button" className="counter-banner sound" onClick={enableSound}>🔈 효과음이 꺼져 있어요. 눌러서 소리 켜기</button>}
    <section className="counter-stage" aria-live="assertive">
      {state.kind === 'ready' && <ReadyGuide />}
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
      {history.map((h, i) => <li key={i}><time>{h.at.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time><span>{h.name}</span><span>{h.receipt ? '키오스크 영수증' : h.duplicate ? '중복 스캔' : `남은 식권 ${h.remaining ?? '—'}장`}</span></li>)}
    </ol>}
  </main>;
}
