import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CheckCircle2, Coffee, FileSpreadsheet, LogOut, Package, QrCode, RefreshCw, Sprout, Store, Users, WalletCards, XCircle } from 'lucide-react';
import { createClient } from '@supabase/supabase-js';
import './style.css';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL;

const supabase = supabaseUrl && supabaseAnonKey ? createClient(supabaseUrl, supabaseAnonKey) : null;

function assertEnv() {
  const missing = [];
  if (!supabaseUrl) missing.push('VITE_SUPABASE_URL');
  if (!supabaseAnonKey) missing.push('VITE_SUPABASE_ANON_KEY');
  if (!apiBaseUrl) missing.push('VITE_API_BASE_URL');
  return missing;
}

async function apiFetch(path, token, options = {}) {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(options.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail ?? payload.error ?? {};
    throw new Error(detail.message || detail.code || `API 오류 (${response.status})`);
  }
  return payload.data;
}

function BrandMark() {
  return <div className="brandmark" aria-label="그린잇">
    <span className="sprout-badge"><Sprout size={26} strokeWidth={2.4} /></span>
    <div><strong>그린잇</strong><small>green eat benefit</small></div>
  </div>;
}

function AuthLinkNotice() {
  const params = new URLSearchParams(window.location.search);
  const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  const auth = params.get('auth');
  const error = params.get('error_description') || hashParams.get('error_description');
  const type = params.get('type') || hashParams.get('type');
  const hasAuthCode = params.has('code') || hashParams.has('access_token') || auth === 'confirmed' || type === 'signup';

  if (error) {
    return <div className="alert error">이메일 인증 링크 처리 중 문제가 생겼어요: {decodeURIComponent(error)}</div>;
  }
  if (!hasAuthCode) return null;
  return <div className="alert success">
    이메일 인증이 완료됐어요. 이제 그린잇 앱으로 돌아가 로그인한 뒤 회사 초대코드를 입력해 주세요.
  </div>;
}

function LoginScreen({ missingEnv, onLogin }) {
  const [email, setEmail] = useState('admin@greeneatgo.test');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(event) {
    event.preventDefault();
    setError('');
    setBusy(true);
    const { data, error: loginError } = await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (loginError) {
      setError(loginError.message);
      return;
    }
    onLogin(data.session);
  }

  return <main className="auth-page">
    <section className="auth-visual">
      <BrandMark />
      <div className="hero-copy">
        <span className="pill">TODAY GREEN</span>
        <h1>그린하게 먹고<br/>건강하게 잇는<br/>회사 식대</h1>
        <p>직원 가입 승인부터 식대 지갑, 제휴 매장 운영까지 한 화면에서 관리합니다.</p>
      </div>
      <div className="floating-menu">
        <span>🥗 샐러드</span><span>🍱 점심</span><span>☕ 카페</span>
      </div>
    </section>
    <section className="login-card">
      <p className="eyebrow">ADMIN LOGIN</p>
      <h2>관리자 로그인</h2>
      <p className="muted">회사관리자 계정으로 직원 가입 요청을 승인/거절할 수 있어요.</p>
      <AuthLinkNotice />
      {missingEnv.length > 0 && <div className="alert error">Vercel 환경변수 누락: {missingEnv.join(', ')}</div>}
      <form onSubmit={submit} className="form">
        <label>이메일
          <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" placeholder="admin@example.com" required />
        </label>
        <label>비밀번호
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" placeholder="비밀번호" required />
        </label>
        {error && <div className="alert error">{error}</div>}
        <button className="primary" disabled={busy || missingEnv.length > 0}>{busy ? '로그인 중...' : '운영 시작하기'}</button>
      </form>
    </section>
  </main>;
}

function Dashboard({ session, onLogout }) {
  const token = session.access_token;
  const [me, setMe] = useState(null);
  const [requests, setRequests] = useState([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const cards = useMemo(() => [
    ['가입 요청', `${requests.length}명`, Users, 'orange'],
    ['직원 권한', me?.role === 'company_admin' ? '관리자' : '확인 필요', WalletCards, 'brown'],
    ['제휴 식당', '5곳', Store, 'green'],
    ['QR 결제', '운영중', QrCode, 'orange'],
    ['정산 예정', 'M2 예정', FileSpreadsheet, 'brown'],
  ], [requests.length, me]);

  async function load() {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const [meData, requestData] = await Promise.all([
        apiFetch('/me', token),
        apiFetch('/admin/join-requests', token),
      ]);
      setMe(meData);
      setRequests(requestData.items ?? []);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setBusy(false);
    }
  }

  async function decide(userId, action) {
    const reason = action === 'reject' ? window.prompt('거절 사유를 입력해 주세요') : null;
    if (action === 'reject' && !reason) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await apiFetch(`/admin/join-requests/${userId}/${action}`, token, {
        method: 'POST',
        body: JSON.stringify(reason ? { reason } : {}),
      });
      setMessage(action === 'approve' ? '가입 요청을 승인했어요.' : '가입 요청을 거절했어요.');
      await load();
    } catch (decisionError) {
      setError(decisionError.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { load(); }, []);

  return <main className="shell">
    <header className="topbar">
      <div className="top-copy">
        <BrandMark />
        <span className="pill">OPERATIONS</span>
        <h1>오늘의 식대 운영 현황</h1>
        <p>가입 승인, 직원 상태, 결제 준비를 그린잇 스타일의 카드 대시보드로 확인합니다.</p>
      </div>
      <div className="top-actions">
        <button className="ghost" onClick={load} disabled={busy}><RefreshCw size={16}/> 새로고침</button>
        <button className="ghost" onClick={onLogout}><LogOut size={16}/> 로그아웃</button>
      </div>
    </header>

    {error && <div className="alert error">{error}</div>}
    {message && <div className="alert success">{message}</div>}

    <section className="hero-panel">
      <div>
        <span className="pill light">LUNCH WALLET</span>
        <h2>든든한 한 끼를 빠르게 승인하세요</h2>
        <p>대기 중인 직원 {requests.length}명 · 관리자 {me?.display_name ?? session.user.email}</p>
      </div>
      <Package className="hero-icon" size={96}/>
    </section>

    <section className="grid">
      {cards.map(([label, value, Icon, tone]) => <article className={`card ${tone}`} key={label}>
        <Icon size={28}/><span>{label}</span><strong>{value}</strong>
      </article>)}
    </section>

    <section className="two-col">
      <article className="panel profile-panel">
        <div className="panel-title"><h2>로그인 정보</h2><span className="badge">secure</span></div>
        <div className="profile-grid">
          <span>이메일</span><strong>{session.user.email}</strong>
          <span>이름</span><strong>{me?.display_name ?? '-'}</strong>
          <span>권한</span><strong>{me?.role ?? '-'}</strong>
          <span>상태</span><strong>{me?.status ?? '-'}</strong>
        </div>
      </article>
      <article className="panel menu-panel">
        <div className="panel-title"><h2>오늘의 카테고리</h2><Coffee size={22}/></div>
        <div className="menu-chips"><span>🥗 샐러드</span><span>🍱 점심</span><span>☕ 카페</span><span>🍜 야근식</span></div>
      </article>
    </section>

    <section className="panel">
      <div className="panel-title">
        <h2>가입 요청 승인</h2>
        <span className="badge">pending {requests.length}</span>
      </div>
      {requests.length === 0 ? <p className="empty-state">승인 대기 중인 직원이 없어요. 오늘 운영은 깔끔해요 🌱</p> : <div className="table-wrap">
        <table>
          <thead><tr><th>이름</th><th>그룹</th><th>요청일</th><th>처리</th></tr></thead>
          <tbody>
            {requests.map((request) => <tr key={request.id}>
              <td><strong>{request.display_name}</strong></td>
              <td>{request.group_id?.slice(0, 8) ?? '-'}</td>
              <td>{request.created_at ? new Date(request.created_at).toLocaleString('ko-KR') : '-'}</td>
              <td className="row-actions">
                <button className="approve" onClick={() => decide(request.id, 'approve')} disabled={busy}><CheckCircle2 size={16}/> 승인</button>
                <button className="reject" onClick={() => decide(request.id, 'reject')} disabled={busy}><XCircle size={16}/> 거절</button>
              </td>
            </tr>)}
          </tbody>
        </table>
      </div>}
    </section>
  </main>;
}

function App() {
  const missingEnv = assertEnv();
  const [session, setSession] = useState(null);
  const [booting, setBooting] = useState(true);

  useEffect(() => {
    if (!supabase) {
      setBooting(false);
      return;
    }
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setBooting(false);
    });
    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => setSession(nextSession));
    return () => listener.subscription.unsubscribe();
  }, []);

  async function logout() {
    await supabase.auth.signOut();
    setSession(null);
  }

  if (booting) return <main className="loading"><BrandMark /><div className="spinner"/></main>;
  if (!session) return <LoginScreen missingEnv={missingEnv} onLogin={setSession} />;
  return <Dashboard session={session} onLogout={logout} />;
}

createRoot(document.getElementById('root')).render(<App />);
