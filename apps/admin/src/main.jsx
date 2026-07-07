import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CheckCircle2, FileSpreadsheet, LogOut, QrCode, RefreshCw, Users, WalletCards, XCircle } from 'lucide-react';
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

  return <main className="shell auth-shell">
    <section className="login-card">
      <p className="eyebrow">greeneatGo Admin</p>
      <h1>관리자 로그인</h1>
      <p className="muted">회사관리자 계정으로 로그인하면 가입 요청을 승인/거절할 수 있어요.</p>
      {missingEnv.length > 0 && <div className="alert error">Vercel 환경변수 누락: {missingEnv.join(', ')}</div>}
      <form onSubmit={submit} className="form">
        <label>이메일
          <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" placeholder="admin@example.com" required />
        </label>
        <label>비밀번호
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" placeholder="비밀번호" required />
        </label>
        {error && <div className="alert error">{error}</div>}
        <button className="primary" disabled={busy || missingEnv.length > 0}>{busy ? '로그인 중...' : '로그인'}</button>
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
    ['가입 요청', `${requests.length}명`, Users],
    ['직원 관리', me?.role === 'company_admin' ? '관리자' : '권한 확인', Users],
    ['제휴 식당', '5곳', QrCode],
    ['정산 예정', 'M2 예정', FileSpreadsheet],
    ['식대 지급', 'M1 예정', WalletCards],
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
      <div>
        <p className="eyebrow">greeneatGo Admin</p>
        <h1>밥장부 관리자</h1>
        <p>가입 요청 승인과 운영 기능을 관리합니다.</p>
      </div>
      <div className="top-actions">
        <button className="ghost" onClick={load} disabled={busy}><RefreshCw size={16}/> 새로고침</button>
        <button className="ghost" onClick={onLogout}><LogOut size={16}/> 로그아웃</button>
      </div>
    </header>

    {error && <div className="alert error">{error}</div>}
    {message && <div className="alert success">{message}</div>}

    <section className="grid">
      {cards.map(([label, value, Icon]) => <article className="card" key={label}>
        <Icon size={28}/><span>{label}</span><strong>{value}</strong>
      </article>)}
    </section>

    <section className="panel profile-panel">
      <h2>로그인 정보</h2>
      <div className="profile-grid">
        <span>이메일</span><strong>{session.user.email}</strong>
        <span>이름</span><strong>{me?.display_name ?? '-'}</strong>
        <span>권한</span><strong>{me?.role ?? '-'}</strong>
        <span>상태</span><strong>{me?.status ?? '-'}</strong>
      </div>
    </section>

    <section className="panel">
      <div className="panel-title">
        <h2>가입 요청 승인</h2>
        <span className="badge">pending {requests.length}</span>
      </div>
      {requests.length === 0 ? <p className="muted">승인 대기 중인 직원이 없어요.</p> : <div className="table-wrap">
        <table>
          <thead><tr><th>이름</th><th>그룹</th><th>요청일</th><th>처리</th></tr></thead>
          <tbody>
            {requests.map((request) => <tr key={request.id}>
              <td>{request.display_name}</td>
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

  if (booting) return <main className="shell"><div className="panel">로딩 중...</div></main>;
  if (!session) return <LoginScreen missingEnv={missingEnv} onLogin={setSession} />;
  return <Dashboard session={session} onLogout={logout} />;
}

createRoot(document.getElementById('root')).render(<App />);
