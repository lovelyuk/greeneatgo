import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AlertTriangle, CalendarDays, CheckCircle2, ChevronDown, Coffee, Download, FileSpreadsheet, FileText, LogOut, QrCode, RefreshCw, Search, Sprout, Users, WalletCards, X, XCircle } from 'lucide-react';
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

async function publicApiFetch(path, options = {}) {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
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
        <p>직원 가입 승인부터 식대 지갑, 정산 현황까지 한 화면에서 관리합니다.</p>
      </div>
      <div className="floating-menu">
        <span>🥗 샐러드</span><span>🍱 점심</span><span>☕ 카페</span>
      </div>
    </section>
    <section className="login-card">
      <p className="eyebrow">ADMIN LOGIN</p>
      <h2>관리자 로그인</h2>
      <p className="muted">회사관리자 또는 식당관리자 계정으로 운영 화면에 들어갈 수 있어요.</p>
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


function InviteClaimScreen({ token, missingEnv, session, onClaimed }) {
  const [invite, setInvite] = useState(null);
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    async function loadInvite() {
      setBusy(true);
      setError('');
      try {
        const data = await publicApiFetch(`/invites/${token}`);
        setInvite(data);
        setPhone(data.phone ?? '');
      } catch (inviteError) {
        setError(inviteError.message);
      } finally {
        setBusy(false);
      }
    }
    loadInvite();
  }, [token]);

  async function sendOtp(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const { error: otpError } = await supabase.auth.signInWithOtp({ phone });
      if (otpError) throw otpError;
      setMessage('인증번호를 보냈어요. 문자로 받은 번호를 입력해 주세요.');
    } catch (otpError) {
      setError(otpError.message);
    } finally {
      setBusy(false);
    }
  }

  async function verifyAndClaim(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setMessage('');
    try {
      let activeSession = session;
      if (!activeSession) {
        const { data, error: verifyError } = await supabase.auth.verifyOtp({ phone, token: otp, type: 'sms' });
        if (verifyError) throw verifyError;
        activeSession = data.session;
      }
      if (!activeSession?.user?.id) throw new Error('인증된 사용자 정보를 찾을 수 없어요');
      await publicApiFetch(`/invites/${token}/claim`, {
        method: 'POST',
        body: JSON.stringify({ auth_user_id: activeSession.user.id, display_name: displayName.trim() || null }),
      });
      setMessage('초대가 연결됐어요. 이제 관리자 화면으로 이동합니다.');
      setTimeout(onClaimed, 700);
    } catch (claimError) {
      setError(claimError.message);
    } finally {
      setBusy(false);
    }
  }

  return <main className="auth-page">
    <section className="auth-visual">
      <BrandMark />
      <div className="hero-copy">
        <span className="pill">INVITE</span>
        <h1>그린잇<br/>운영자 초대</h1>
        <p>전화번호 인증 후 식당관리자 또는 회사관리자 계정으로 연결합니다.</p>
      </div>
    </section>
    <section className="login-card">
      <p className="eyebrow">CLAIM INVITE</p>
      <h2>초대 수락</h2>
      {missingEnv.length > 0 && <div className="alert error">Vercel 환경변수 누락: {missingEnv.join(', ')}</div>}
      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert success">{message}</div>}
      {invite && <div className="profile-grid">
        <span>권한</span><strong>{invite.role === 'merchant_admin' ? '식당관리자' : '회사관리자'}</strong>
        <span>상태</span><strong>{invite.status}</strong>
        <span>만료</span><strong>{new Date(invite.expires_at).toLocaleString('ko-KR')}</strong>
      </div>}
      <form className="form" onSubmit={sendOtp}>
        <label>전화번호
          <input value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="01012345678" required />
        </label>
        <button className="ghost" disabled={busy || missingEnv.length > 0 || !invite}>인증번호 받기</button>
      </form>
      <form className="form" onSubmit={verifyAndClaim}>
        <label>인증번호
          <input value={otp} onChange={(event) => setOtp(event.target.value)} placeholder="문자 인증번호" required={!session} />
        </label>
        <label>이름
          <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="표시 이름" />
        </label>
        <button className="primary" disabled={busy || missingEnv.length > 0 || !invite}>{session ? '현재 로그인 계정에 초대 연결' : '인증 후 초대 수락'}</button>
      </form>
    </section>
  </main>;
}

const krw = (value) => `₩${Number(value ?? 0).toLocaleString('ko-KR')}`;
const dateKey = (value) => value ? new Date(value).toISOString().slice(0, 10) : new Date().toISOString().slice(0, 10);
const dayLabel = (key) => new Date(`${key}T00:00:00`).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' });
const todayInput = () => new Date().toISOString().slice(0, 10);

function buildTransactionRows(rawItems, range, q) {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();
  const presets = {
    current: [new Date(y, m, 1), new Date(y, m + 1, 0, 23, 59, 59)],
    previous: [new Date(y, m - 1, 1), new Date(y, m, 0, 23, 59, 59)],
    quarter: [new Date(y, m - 2, 1), new Date(y, m + 1, 0, 23, 59, 59)],
  };
  const [from, to] = range.type === 'custom'
    ? [new Date(`${range.from || todayInput()}T00:00:00`), new Date(`${range.to || todayInput()}T23:59:59`)]
    : presets[range.type] ?? presets.current;
  const query = q.trim().toLowerCase();
  const normalized = rawItems.map((tx, index) => {
    const rawAmount = Number(tx.amount ?? tx.product_price ?? 0);
    const cancelled = tx.status === 'cancelled' || tx.status === 'refund' || tx.kind === 'refund' || tx.kind === 'cancel';
    const amount = cancelled ? -Math.abs(rawAmount) : Math.abs(rawAmount);
    return {
      id: tx.id ?? `mock-${index}`,
      created_at: tx.created_at ?? new Date(y, m, Math.max(1, now.getDate() - index), 12, 10 + index).toISOString(),
      time: tx.created_at ? new Date(tx.created_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }) : '12:00',
      employee_name: tx.employee_name ?? tx.user_name ?? ['김민준', '이지은', '박서준', '최유나'][index % 4],
      employee_no: tx.employee_no ?? tx.user_id?.slice(0, 6) ?? `E${String(index + 1).padStart(3, '0')}`,
      menu: tx.product_name ?? tx.meal_window ?? '구내식당 식권',
      pay_type: tx.kind === 'wallet' ? '식권' : '장부',
      amount,
      status: cancelled ? 'refund' : 'paid',
      tx_code: tx.tx_code ?? '-',
    };
  }).filter((tx) => {
    const created = new Date(tx.created_at);
    const matchesDate = created >= from && created <= to;
    const matchesQuery = !query || `${tx.employee_name} ${tx.employee_no}`.toLowerCase().includes(query);
    return matchesDate && matchesQuery;
  });
  return normalized;
}

function VendorTransactionModal({ txModal, token, onClose }) {
  const dialogRef = useRef(null);
  const returnFocusRef = useRef(document.activeElement);
  const [activeTab, setActiveTab] = useState('transactions');
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [range, setRange] = useState({ type: 'current', from: todayInput().slice(0, 8) + '01', to: todayInput() });
  const [query, setQuery] = useState('');
  const [collapsed, setCollapsed] = useState({});
  const [apiError, setApiError] = useState('');
  const [serverSummary, setServerSummary] = useState(null);
  const [serverDays, setServerDays] = useState(null);
  const [settlements, setSettlements] = useState([]);

  useEffect(() => {
    const timer = setTimeout(() => setLoading(false), 350);
    dialogRef.current?.focus();
    function onKeyDown(event) {
      if (event.key === 'Escape' && !exporting) onClose();
      if (event.key === 'Tab' && dialogRef.current) {
        const focusable = [...dialogRef.current.querySelectorAll('button, input, [href], [tabindex]:not([tabindex="-1"])')].filter((el) => !el.disabled);
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('keydown', onKeyDown);
      returnFocusRef.current?.focus?.();
    };
  }, [exporting, onClose]);

  useEffect(() => { setLoading(true); const timer = setTimeout(() => setLoading(false), 260); return () => clearTimeout(timer); }, [range, query, activeTab]);

  function rangeParams() {
    const now = new Date();
    const y = now.getFullYear();
    const m = now.getMonth();
    const pad = (value) => String(value).padStart(2, '0');
    if (range.type === 'previous') {
      const start = new Date(y, m - 1, 1);
      const end = new Date(y, m, 0);
      return { from: `${start.getFullYear()}-${pad(start.getMonth() + 1)}-01`, to: `${end.getFullYear()}-${pad(end.getMonth() + 1)}-${pad(end.getDate())}` };
    }
    if (range.type === 'quarter') {
      const start = new Date(y, m - 2, 1);
      const end = new Date(y, m + 1, 0);
      return { from: `${start.getFullYear()}-${pad(start.getMonth() + 1)}-01`, to: `${end.getFullYear()}-${pad(end.getMonth() + 1)}-${pad(end.getDate())}` };
    }
    if (range.type === 'custom') return { from: range.from, to: range.to };
    const end = new Date(y, m + 1, 0);
    return { from: `${y}-${pad(m + 1)}-01`, to: `${y}-${pad(m + 1)}-${pad(end.getDate())}` };
  }

  useEffect(() => {
    if (!txModal.companyId) return;
    let cancelled = false;
    async function loadVendorDetail() {
      setLoading(true);
      setApiError('');
      const { from, to } = rangeParams();
      const params = `from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`;
      try {
        const [summaryData, txData, settlementData] = await Promise.all([
          apiFetch(`/admin/merchant/companies/${txModal.companyId}/summary?${params}`, token),
          apiFetch(`/admin/merchant/companies/${txModal.companyId}/transactions?${params}&q=${encodeURIComponent(query)}`, token),
          apiFetch(`/admin/merchant/companies/${txModal.companyId}/settlements`, token),
        ]);
        if (cancelled) return;
        setServerSummary(summaryData);
        setServerDays(txData.days ?? []);
        setSettlements(settlementData.items ?? []);
      } catch (detailError) {
        if (!cancelled) {
          setApiError(detailError.message);
          setServerSummary(null);
          setServerDays(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    loadVendorDetail();
    return () => { cancelled = true; };
  }, [txModal.companyId, range, query, token]);

  const serverRows = useMemo(() => serverDays ? serverDays.flatMap((day) => (day.items ?? []).map((item) => ({
    ...item,
    time: item.created_at ? new Date(item.created_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }) : item.time,
    menu: item.menu ?? item.product_name ?? item.meal_window ?? '식대 사용',
    pay_type: item.pay_type ?? (item.kind === 'spend' ? '식권' : '장부'),
  }))) : null, [serverDays]);

  const rows = useMemo(() => serverRows ?? buildTransactionRows(txModal.txItems, range, query), [serverRows, txModal.txItems, range, query]);
  const summary = useMemo(() => {
    if (serverSummary) {
      const next = serverSummary.next_settlement_date ? new Date(`${serverSummary.next_settlement_date}T00:00:00`) : new Date();
      const dday = Math.ceil((new Date(next.toDateString()) - new Date(new Date().toDateString())) / 86400000);
      return {
        total: serverSummary.total_amount ?? 0,
        count: serverSummary.total_count ?? 0,
        cancelCount: serverSummary.cancel_count ?? 0,
        unsettled: serverSummary.unsettled_amount ?? 0,
        nextSettlement: `${next.getMonth() + 1}/${next.getDate()} (D-${dday})`,
      };
    }
    const total = rows.reduce((sum, row) => sum + Number(row.amount ?? 0), 0);
    const cancelCount = rows.filter((row) => row.status === 'refund').length;
    const next = new Date();
    next.setMonth(next.getMonth() + 1, 0);
    const dday = Math.ceil((new Date(next.toDateString()) - new Date(new Date().toDateString())) / 86400000);
    return { total, count: rows.length, cancelCount, unsettled: Math.max(0, total), nextSettlement: `${next.getMonth() + 1}/${next.getDate()} (D-${dday})` };
  }, [rows, serverSummary]);
  const unpaid = settlements.filter((item) => item.status !== '입금완료');
  const unpaidAmount = unpaid.reduce((sum, item) => sum + Number(item.amount ?? 0), 0);
  const contract = serverSummary?.contract ?? txModal.contract ?? null;
  const groups = useMemo(() => {
    const byDay = new Map();
    rows.forEach((row) => {
      const key = dateKey(row.created_at);
      if (!byDay.has(key)) byDay.set(key, []);
      byDay.get(key).push(row);
    });
    return [...byDay.entries()].map(([key, items]) => ({ key, items, subtotal: items.reduce((sum, item) => sum + Number(item.amount ?? 0), 0) })).sort((a, b) => b.key.localeCompare(a.key));
  }, [rows]);

  async function download(format) {
    setExporting(true);
    const { from } = rangeParams();
    const ym = from.slice(0, 7).replace('-', '');
    const fileName = `${txModal.companyName}_${format === 'xlsx' ? '거래내역' : '청구서'}_${ym}.${format}`;
    try {
      if (txModal.companyId) {
        const { from, to } = rangeParams();
        const response = await fetch(`${apiBaseUrl}/admin/merchant/companies/${txModal.companyId}/export?format=${format}&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!response.ok) throw new Error(`다운로드 API 오류 (${response.status})`);
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = fileName; a.click();
        URL.revokeObjectURL(url);
        return;
      }
      const lines = [
        `${txModal.companyName} ${format === 'xlsx' ? '거래내역' : '청구서'}`,
        `총액,${summary.total},건수,${summary.count},미정산,${summary.unsettled}`,
        '일자,시간,직원,사번,메뉴,결제구분,금액,상태',
        ...rows.map((row) => `${dateKey(row.created_at)},${row.time},${row.employee_name},${row.employee_no},${row.menu},${row.pay_type},${row.amount},${row.status}`),
      ];
      const blob = new Blob([lines.join('\n')], { type: format === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = fileName; a.click();
      URL.revokeObjectURL(url);
    } catch (downloadError) {
      setApiError(downloadError.message);
    } finally {
      setTimeout(() => setExporting(false), 300);
    }
  }

  async function confirmPayment(item) {
    const paidAt = window.prompt('입금일을 입력해 주세요', todayInput());
    if (!paidAt) return;
    try {
      if (txModal.companyId && item.id) {
        await apiFetch(`/admin/merchant/companies/${txModal.companyId}/settlements/${item.id}/confirm-payment`, token, {
          method: 'POST',
          body: JSON.stringify({ paid_at: paidAt }),
        });
      }
      setSettlements((list) => list.map((row) => row.id === item.id ? { ...row, status: '입금완료', paid_at: paidAt } : row));
      setServerSummary((prev) => prev ? { ...prev, unsettled_amount: Math.max(0, Number(prev.unsettled_amount ?? 0) - Number(item.amount ?? 0)) } : prev);
    } catch (paymentError) {
      setApiError(paymentError.message);
    }
  }

  return <div className="vendor-modal-backdrop" onClick={() => !exporting && onClose()}>
    <section className="vendor-modal" role="dialog" aria-modal="true" aria-labelledby="vendor-modal-title" tabIndex={-1} ref={dialogRef} onClick={(event) => event.stopPropagation()}>
      <header className="vendor-modal-header">
        <div className="vendor-title-row">
          <div>
            <h2 id="vendor-modal-title">🏢 {txModal.companyName}</h2>
            {contract && <span className="contract-badge">계약: {contract.cycle_label ?? contract.cycle}{contract.unit_price != null ? ` · 단가 ${Number(contract.unit_price).toLocaleString('ko-KR')}원` : ''}</span>}
          </div>
          <button className="ghost icon-button" onClick={onClose} disabled={exporting} aria-label="닫기"><X size={20}/></button>
        </div>
        {unpaidAmount > 0 && <button className="overdue-badge" onClick={() => setActiveTab('settlements')}><AlertTriangle size={16}/> 미수금 {krw(unpaidAmount)} (지난 정산 미입금)</button>}
        <nav className="vendor-tabs" aria-label="업체 거래 모달 탭">
          <button className={activeTab === 'transactions' ? 'active' : ''} onClick={() => setActiveTab('transactions')}>거래내역</button>
          <button className={activeTab === 'settlements' ? 'active' : ''} onClick={() => setActiveTab('settlements')}>정산이력</button>
        </nav>
      </header>

      {activeTab === 'transactions' ? <>
        <div className="vendor-filterbar">
          <div className="range-chips">
            {[['current', '이번 달'], ['previous', '지난 달'], ['quarter', '최근 3개월'], ['custom', '직접 선택']].map(([type, label]) => <button key={type} className={range.type === type ? 'active' : ''} onClick={() => setRange((prev) => ({ ...prev, type }))}>{label}</button>)}
          </div>
          {range.type === 'custom' && <div className="date-range"><input type="date" value={range.from} onChange={(e) => setRange((prev) => ({ ...prev, from: e.target.value }))}/><span>~</span><input type="date" value={range.to} onChange={(e) => setRange((prev) => ({ ...prev, to: e.target.value }))}/></div>}
          <label className="tx-search"><Search size={16}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="직원명/사번 검색" /></label>
        </div>
        <div className="vendor-modal-body">
          {apiError && <div className="alert error">상세 API 확인 필요: {apiError}</div>}
          {loading ? <TransactionSkeleton /> : <>
            <section className="vendor-summary-grid">
              <article><span>총 이용금액</span><strong>{krw(summary.total)}</strong></article>
              <article><span>총 이용건수</span><strong>{summary.count}건 {summary.cancelCount ? `(취소 ${summary.cancelCount})` : ''}</strong></article>
              <article className="main-amount"><span>미정산 잔액</span><strong>{krw(summary.unsettled)}</strong></article>
              <article><span>다음 정산일</span><strong><CalendarDays size={18}/>{summary.nextSettlement}</strong></article>
            </section>
            {groups.length === 0 ? <p className="vendor-empty">📒 선택한 기간에 거래가 없습니다</p> : <section className="day-ledger-list">
              {groups.map((group) => <article className="day-ledger" key={group.key}>
                <button className="day-ledger-header" onClick={() => setCollapsed((prev) => ({ ...prev, [group.key]: !prev[group.key] }))}><span>{dayLabel(group.key)} — {group.items.length}건 · {krw(group.subtotal)}</span><ChevronDown className={collapsed[group.key] ? 'closed' : ''} size={18}/></button>
                {!collapsed[group.key] && <div className="table-wrap"><table><thead><tr><th>시각</th><th>직원명(사번)</th><th>메뉴/내역</th><th>결제구분</th><th>금액</th></tr></thead><tbody>{group.items.map((row) => <tr key={row.id} className={row.status === 'refund' ? 'refund-row' : ''}><td>{row.time}</td><td><strong>{row.employee_name}</strong> ({row.employee_no})</td><td>{row.menu} {row.status === 'refund' && <span className="refund-tag">환불</span>}</td><td>{row.pay_type}</td><td className="money">{krw(row.amount)}</td></tr>)}</tbody></table></div>}
              </article>)}
            </section>}
          </>}
        </div>
        <footer className="vendor-modal-footer"><button className="primary export-button" onClick={() => download('xlsx')} disabled={exporting}><Download size={17}/> 엑셀 다운로드</button><button className="primary export-button" onClick={() => download('pdf')} disabled={exporting}><FileText size={17}/> PDF 청구서</button><button className="ghost" onClick={onClose} disabled={exporting}>닫기</button></footer>
      </> : <div className="vendor-modal-body settlement-tab">
        {apiError && <div className="alert error">상세 API 확인 필요: {apiError}</div>}
        {unpaidAmount > 0 && <div className="unpaid-banner">총 미수금 {krw(unpaidAmount)} — {unpaid.length}회차 미입금</div>}
        <div className="table-wrap"><table><thead><tr><th>정산 기간</th><th>청구액</th><th>상태</th><th>입금일</th><th>액션</th></tr></thead><tbody>{settlements.map((item) => <tr key={item.id} className={item.status === '연체' ? 'overdue-row' : ''}><td>{item.period_from} ~ {item.period_to.slice(5)}</td><td className="money">{krw(item.amount)}</td><td><span className={`settlement-status ${item.status}`}>{item.status}</span></td><td>{item.paid_at || '-'}</td><td className="row-actions">{item.status !== '입금완료' && <button className="ghost" onClick={() => confirmPayment(item)}>입금확인</button>}<button className="ghost" onClick={() => download('pdf')}>청구서 다시받기</button></td></tr>)}</tbody></table></div>
      </div>}
    </section>
  </div>;
}

function TransactionSkeleton() {
  return <div className="vendor-skeleton"><div className="vendor-summary-grid">{[0, 1, 2, 3].map((n) => <article key={n} className="skeleton-card" />)}</div><div className="skeleton-lines">{[0, 1, 2, 3, 4, 5].map((n) => <span key={n}/>)}</div></div>;
}

function Dashboard({ session, onLogout }) {
  const token = session.access_token;
  const [me, setMe] = useState(null);
  const [requests, setRequests] = useState([]);
  const [settlements, setSettlements] = useState(null);
  const [products, setProducts] = useState(null);
  const [productForm, setProductForm] = useState({ name: '', price: '', category: '' });
  const [dailyMenu, setDailyMenu] = useState(null);
  const [dailyMenuForm, setDailyMenuForm] = useState({ title: '오늘의 부페 메뉴', menu_text: '' });
  const [merchantCompanies, setMerchantCompanies] = useState(null);
  const [companySearch, setCompanySearch] = useState('');
  const [companySearchResults, setCompanySearchResults] = useState([]);
  const [newCompanyForm, setNewCompanyForm] = useState({ name: '', owner_phone: '' });
  const [transactions, setTransactions] = useState(null);
  const [merchantQr, setMerchantQr] = useState(null);
  const [platformMerchants, setPlatformMerchants] = useState(null);
  const [platformMerchantForm, setPlatformMerchantForm] = useState({ name: '', owner_phone: '', category: '', avg_price: '' });
  const [platformInvitePhone, setPlatformInvitePhone] = useState({});
  const [inviteModal, setInviteModal] = useState(null);
  const [txModal, setTxModal] = useState(null);
  const [contractModal, setContractModal] = useState(null);
  const [contractForm, setContractForm] = useState({ settlement_cycle: 'month_end', settlement_day: '25', unit_price: '' });
  const [busy, setBusy] = useState(false);
  const [dashboardBooting, setDashboardBooting] = useState(true);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const isMerchantAdmin = me?.role === 'merchant_admin';
  const isPlatformAdmin = me?.role === 'platform_admin';
  const inviteLink = (invite) => invite?.token ? `${window.location.origin}/?invite=${invite.token}` : '';

  async function copyInviteLink() {
    if (!inviteModal?.link) return;
    try {
      await navigator.clipboard.writeText(inviteModal.link);
      setMessage('초대링크를 복사했어요.');
    } catch {
      setError('자동 복사가 막혔어요. 링크 입력칸을 길게 눌러 직접 복사해 주세요.');
    }
  }

  const merchantPayUrl = merchantQr?.qr_token ? `${window.location.origin}/pay?qr=${encodeURIComponent(merchantQr.qr_token)}` : '';
  const merchantQrImageUrl = merchantPayUrl ? `https://api.qrserver.com/v1/create-qr-code/?size=260x260&margin=14&data=${encodeURIComponent(merchantPayUrl)}` : '';

  async function copyMerchantPayUrl() {
    if (!merchantPayUrl) return;
    try {
      await navigator.clipboard.writeText(merchantPayUrl);
      setMessage('결제 QR 링크를 복사했어요.');
    } catch {
      setError('자동 복사가 막혔어요. QR 링크를 직접 복사해 주세요.');
    }
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
  }

  function downloadMerchantQrPdf() {
    if (!merchantPayUrl || !merchantQrImageUrl) return;
    const merchantName = escapeHtml(merchantQr?.merchant?.name ?? '그린잇 식당');
    const win = window.open('', '_blank', 'width=720,height=900');
    if (!win) {
      setError('팝업이 차단됐어요. 브라우저 팝업 허용 후 다시 눌러 주세요.');
      return;
    }
    win.document.write(`<!doctype html><html><head><title>${merchantName} 결제 QR</title><style>body{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;padding:34px;background:#f3fbf4;color:#14351f}.sheet{max-width:520px;margin:0 auto;background:white;border:2px solid #cdebd5;border-radius:28px;padding:34px;text-align:center}.brand{font-size:18px;font-weight:900;color:#2fb865;letter-spacing:.08em}.title{font-size:32px;font-weight:1000;margin:14px 0 6px}.merchant{font-size:22px;font-weight:900;margin-bottom:22px}.qr{width:300px;height:300px;border:12px solid #eaf7ec;border-radius:24px}.help{font-size:17px;font-weight:800;line-height:1.55;color:#5c7a66}.url{word-break:break-all;font-size:12px;color:#5c7a66;margin-top:18px}@media print{body{background:white}.sheet{box-shadow:none;border-color:#14351f}}</style></head><body><section class="sheet"><div class="brand">GREENEATGO PAYMENT</div><div class="title">직원 결제 QR</div><div class="merchant">${merchantName}</div><img class="qr" src="${merchantQrImageUrl}"/><p class="help">직원 앱 또는 휴대폰 카메라로 스캔해<br/>식대 상품을 선택하고 결제하세요.</p><p class="url">${merchantPayUrl}</p></section><script>window.onload=()=>setTimeout(()=>window.print(),500)</script></body></html>`);
    win.document.close();
  }
  const cards = useMemo(() => isPlatformAdmin ? [
    ['권한', '플랫폼 운영자', WalletCards, 'brown'],
    ['식당', platformMerchants ? `${platformMerchants.items.length}곳` : '조회 중', Coffee, 'green'],
  ] : isMerchantAdmin ? [
    ['권한', '관리자', WalletCards, 'brown'],
    ['상품', products ? `${products.items.filter((item) => item.is_active).length}개` : '조회 중', QrCode, 'orange'],
    ['장부업체', merchantCompanies ? `${merchantCompanies.items.length}곳` : '조회 중', Users, 'green'],
    ['거래내역', transactions ? `${transactions.items.length}건` : '조회 중', FileSpreadsheet, 'orange'],
  ] : [
    ['가입 요청', `${requests.length}명`, Users, 'orange'],
    ['직원 권한', me?.role === 'company_admin' ? '관리자' : '확인 필요', WalletCards, 'brown'],
    ['QR 결제', products ? `${products.items.filter((item) => item.is_active).length}개 상품` : '단일 식당', QrCode, 'orange'],
    ['정산 현황', settlements ? `${settlements.summary.settlement_count}건` : '조회 중', FileSpreadsheet, 'green'],
  ], [isPlatformAdmin, isMerchantAdmin, requests.length, me, settlements, products, merchantCompanies, transactions, platformMerchants]);

  async function load() {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const meData = await apiFetch('/me', token);
      let productData = null;
      let dailyMenuData = null;
      let requestData = { items: [] };
      let settlementData = null;
      let merchantCompanyData = null;
      let transactionData = null;
      let merchantQrData = null;
      let platformMerchantData = null;
      if (meData.role === 'platform_admin') {
        platformMerchantData = await apiFetch('/admin/platform/merchants', token);
      } else {
        [productData, dailyMenuData] = await Promise.all([
          apiFetch('/admin/products', token),
          apiFetch('/admin/daily-menu', token),
        ]);
        if (meData.role === 'company_admin') {
          [requestData, settlementData] = await Promise.all([
            apiFetch('/admin/join-requests', token),
            apiFetch('/admin/settlements', token),
          ]);
        }
        if (meData.role === 'merchant_admin') {
          [merchantCompanyData, transactionData, merchantQrData] = await Promise.all([
            apiFetch('/admin/merchant/companies', token),
            apiFetch('/admin/merchant/transactions', token),
            apiFetch('/admin/merchant/qr', token),
          ]);
        }
      }
      setMe(meData);
      setRequests(requestData.items ?? []);
      setSettlements(settlementData);
      setMerchantCompanies(merchantCompanyData);
      setTransactions(transactionData);
      setMerchantQr(merchantQrData);
      setPlatformMerchants(platformMerchantData);
      setProducts(productData);
      setDailyMenu(dailyMenuData);
      setDailyMenuForm({
        title: dailyMenuData?.today_menu?.title ?? '오늘의 부페 메뉴',
        menu_text: dailyMenuData?.today_menu?.menu_text ?? '',
      });
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setBusy(false);
      setDashboardBooting(false);
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


  async function createProduct(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await apiFetch('/admin/products', token, {
        method: 'POST',
        body: JSON.stringify({
          name: productForm.name.trim(),
          price: Number(productForm.price),
          category: productForm.category.trim() || null,
          sort_order: (products?.items?.length ?? 0) + 1,
        }),
      });
      setProductForm({ name: '', price: '', category: '' });
      setMessage('상품을 등록했어요. 직원 앱 상품 선택 화면에 바로 반영됩니다.');
      await load();
    } catch (productError) {
      setError(productError.message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleProduct(product) {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await apiFetch(`/admin/products/${product.id}`, token, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: !product.is_active }),
      });
      setMessage(product.is_active ? '상품을 숨겼어요.' : '상품을 다시 판매중으로 바꿨어요.');
      await load();
    } catch (productError) {
      setError(productError.message);
    } finally {
      setBusy(false);
    }
  }


  async function saveDailyMenu(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await apiFetch('/admin/daily-menu', token, {
        method: 'PUT',
        body: JSON.stringify({
          title: dailyMenuForm.title.trim() || '오늘의 부페 메뉴',
          menu_text: dailyMenuForm.menu_text.trim(),
          is_active: true,
        }),
      });
      setMessage('오늘 메뉴를 저장했어요. 직원 앱에 바로 표시됩니다.');
      await load();
    } catch (menuError) {
      setError(menuError.message);
    } finally {
      setBusy(false);
    }
  }

  async function searchCompanies(event) {
    event.preventDefault();
    if (!companySearch.trim()) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const data = await apiFetch(`/admin/merchant/companies/search?q=${encodeURIComponent(companySearch.trim())}`, token);
      setCompanySearchResults(data.items ?? []);
    } catch (searchError) {
      setError(searchError.message);
    } finally {
      setBusy(false);
    }
  }

  async function linkCompany(companyId) {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await apiFetch('/admin/merchant/companies/link', token, {
        method: 'POST',
        body: JSON.stringify({ company_id: companyId }),
      });
      setCompanySearchResults([]);
      setCompanySearch('');
      setMessage('장부업체를 연결했어요.');
      await load();
    } catch (linkError) {
      setError(linkError.message);
    } finally {
      setBusy(false);
    }
  }

  async function createAndLinkCompany(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const data = await apiFetch('/admin/merchant/companies/create-and-link', token, {
        method: 'POST',
        body: JSON.stringify({
          name: newCompanyForm.name.trim(),
          owner_phone: newCompanyForm.owner_phone.trim(),
        }),
      });
      setNewCompanyForm({ name: '', owner_phone: '' });
      setMessage(`장부업체를 만들고 초대를 생성했어요. 업체관리자 초대링크: ${inviteLink(data.invite) || '-'}`);
      await load();
    } catch (createError) {
      setError(createError.message);
    } finally {
      setBusy(false);
    }
  }

  function openContractModal(item) {
    setContractModal(item);
    setContractForm({
      settlement_cycle: item.settlement_cycle ?? item.contract?.settlement_cycle ?? 'month_end',
      settlement_day: String(item.settlement_day ?? item.contract?.settlement_day ?? 25),
      unit_price: item.unit_price == null ? '' : String(item.unit_price),
    });
  }

  async function saveContract(event) {
    event.preventDefault();
    if (!contractModal) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await apiFetch(`/admin/merchant/companies/${contractModal.company_id}/contract`, token, {
        method: 'PATCH',
        body: JSON.stringify({
          settlement_cycle: contractForm.settlement_cycle,
          settlement_day: contractForm.settlement_cycle === 'day' ? Number(contractForm.settlement_day) : null,
          unit_price: contractForm.unit_price === '' ? null : Number(contractForm.unit_price),
        }),
      });
      setContractModal(null);
      setMessage('업체 계약 정보를 저장했어요.');
      await load();
    } catch (contractError) {
      setError(contractError.message);
    } finally {
      setBusy(false);
    }
  }

  async function createPlatformMerchant(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await apiFetch('/admin/platform/merchants', token, {
        method: 'POST',
        body: JSON.stringify({
          name: platformMerchantForm.name.trim(),
          owner_phone: platformMerchantForm.owner_phone.trim() || null,
          category: platformMerchantForm.category.trim() || null,
          avg_price: platformMerchantForm.avg_price ? Number(platformMerchantForm.avg_price) : null,
        }),
      });
      setPlatformMerchantForm({ name: '', owner_phone: '', category: '', avg_price: '' });
      setMessage('식당을 등록했어요.');
      await load();
    } catch (createError) {
      setError(createError.message);
    } finally {
      setBusy(false);
    }
  }

  async function invitePlatformMerchant(merchantId) {
    const phone = (platformInvitePhone[merchantId] ?? '').trim();
    if (!phone) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const invite = await apiFetch(`/admin/platform/merchants/${merchantId}/invite`, token, {
        method: 'POST',
        body: JSON.stringify({ phone }),
      });
      setPlatformInvitePhone((form) => ({ ...form, [merchantId]: '' }));
      setMessage(`식당관리자 초대를 생성했어요. 초대 토큰: ${invite.token ?? '-'}`);
    } catch (inviteError) {
      setError(inviteError.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { load(); }, []);

  if (dashboardBooting) return <main className="loading"><BrandMark /><div className="spinner"/><p className="loading-copy">운영자 권한을 확인하고 있어요...</p></main>;

  if (!me) return <main className="loading"><BrandMark /><div className="alert error">권한 정보를 불러오지 못했어요. {error}</div><button className="ghost" onClick={onLogout}>로그아웃</button></main>;

  return <main className="shell">
    <header className="topbar">
      <div className="top-copy">
        <BrandMark />
        <span className="pill">OPERATIONS</span>
        <p>가입 승인, 직원 상태, 식당 결제와 정산 현황을 그린잇 스타일의 카드 대시보드로 확인합니다.</p>
      </div>
      <div className="top-actions">
        <button className="ghost" onClick={load} disabled={busy}><RefreshCw size={16}/> 새로고침</button>
        <button className="ghost" onClick={onLogout}><LogOut size={16}/> 로그아웃</button>
      </div>
    </header>

    {error && <div className="alert error">{error}</div>}
    {message && <div className="alert success">{message}</div>}

    {inviteModal && <div className="modal-backdrop" onClick={() => setInviteModal(null)}>
      <section className="invite-modal" onClick={(event) => event.stopPropagation()}>
        <div className="panel-title"><div><h2>업체관리자 초대링크</h2><p className="panel-note">{inviteModal.companyName} 담당자에게 아래 링크를 보내주세요.</p></div></div>
        <input value={inviteModal.link} readOnly onFocus={(event) => event.target.select()} />
        <div className="row-actions invite-modal-actions">
          <button className="primary" onClick={copyInviteLink}>복사하기</button>
          <button className="ghost" onClick={() => setInviteModal(null)}>닫기</button>
        </div>
      </section>
    </div>}

    {txModal && <VendorTransactionModal txModal={txModal} token={token} onClose={() => setTxModal(null)} />}

    {contractModal && <div className="modal-backdrop" onClick={() => setContractModal(null)}>
      <section className="invite-modal contract-modal" onClick={(event) => event.stopPropagation()}>
        <div className="panel-title">
          <div>
            <h2>계약 설정</h2>
            <p className="panel-note">{contractModal.company?.name ?? contractModal.company_id} 계약 정보를 관리합니다.</p>
          </div>
          <button className="ghost icon-button" onClick={() => setContractModal(null)} aria-label="닫기"><X size={20}/></button>
        </div>
        <div className="profile-grid contract-summary">
          <span>업체명</span><strong>{contractModal.company?.name ?? '-'}</strong>
          <span>연결일</span><strong>{contractModal.created_at ? new Date(contractModal.created_at).toLocaleString('ko-KR') : '-'}</strong>
        </div>
        <form className="contract-form" onSubmit={saveContract}>
          <label>정산일자
            <select value={contractForm.settlement_cycle} onChange={(event) => setContractForm((form) => ({ ...form, settlement_cycle: event.target.value }))}>
              <option value="month_end">월말</option>
              <option value="day">매월 특정일</option>
            </select>
          </label>
          {contractForm.settlement_cycle === 'day' && <label>특정 날짜
            <input type="number" min="1" max="31" value={contractForm.settlement_day} onChange={(event) => setContractForm((form) => ({ ...form, settlement_day: event.target.value }))} placeholder="예: 25" required />
          </label>}
          <label>단가
            <input type="number" min="0" value={contractForm.unit_price} onChange={(event) => setContractForm((form) => ({ ...form, unit_price: event.target.value }))} placeholder="예: 8000" />
          </label>
          <div className="row-actions invite-modal-actions">
            <button className="primary" disabled={busy}>저장</button>
            <button className="ghost" type="button" onClick={() => setContractModal(null)}>닫기</button>
          </div>
        </form>
      </section>
    </div>}

    <section className="grid">
      {cards.map(([label, value, Icon, tone]) => <article className={`card ${tone}`} key={label}>
        <Icon size={28}/><span>{label}</span><strong>{value}</strong>
      </article>)}
    </section>

    {isPlatformAdmin && <section className="panel">
      <div className="panel-title">
        <div><h2>플랫폼 식당 온보딩</h2><p className="panel-note">식당을 등록하고 사장님에게 식당관리자 초대를 생성합니다.</p></div>
        <span className="badge">{platformMerchants?.items?.length ?? 0}곳</span>
      </div>
      <form className="product-form" onSubmit={createPlatformMerchant}>
        <input value={platformMerchantForm.name} onChange={(event) => setPlatformMerchantForm((form) => ({ ...form, name: event.target.value }))} placeholder="식당명" required />
        <input value={platformMerchantForm.owner_phone} onChange={(event) => setPlatformMerchantForm((form) => ({ ...form, owner_phone: event.target.value }))} placeholder="사장님 연락처" />
        <input value={platformMerchantForm.category} onChange={(event) => setPlatformMerchantForm((form) => ({ ...form, category: event.target.value }))} placeholder="카테고리" />
        <input value={platformMerchantForm.avg_price} onChange={(event) => setPlatformMerchantForm((form) => ({ ...form, avg_price: event.target.value }))} placeholder="평균가" type="number" min="1" />
        <button className="primary" disabled={busy}>식당 등록</button>
      </form>
      {(platformMerchants?.items?.length ?? 0) === 0
        ? <p className="empty-state">등록된 식당이 없어요.</p>
        : <div className="product-list">{platformMerchants.items.map((merchant) => <article className="product-item" key={merchant.id}>
          <div><strong>{merchant.name}</strong><span>{merchant.category ?? '기본'} · {merchant.owner_phone ?? '연락처 없음'} · {merchant.status}</span></div>
          <div className="row-actions">
            <input value={platformInvitePhone[merchant.id] ?? ''} onChange={(event) => setPlatformInvitePhone((form) => ({ ...form, [merchant.id]: event.target.value }))} placeholder="초대 연락처" />
            <button className="ghost" onClick={() => invitePlatformMerchant(merchant.id)} disabled={busy || !(platformInvitePhone[merchant.id] ?? '').trim()}>사장님 초대</button>
          </div>
        </article>)}</div>}
    </section>}

    <section className="two-col">
      <article className="panel profile-panel">
        <div className="panel-title"><h2>로그인 정보</h2><span className="badge">secure</span></div>
        <div className="profile-grid">
          <span>이메일</span><strong>{session.user.email}</strong>
          <span>이름</span><strong>{me?.display_name ?? '-'}</strong>
          <span>권한</span><strong>{me?.role === 'merchant_admin' ? '관리자' : me?.role ?? '-'}</strong>
          <span>상태</span><strong>{me?.status ?? '-'}</strong>
        </div>
      </article>
      {isMerchantAdmin && <article className="panel merchant-qr-panel">
        <div className="panel-title"><div><h2>내 매장 결제 QR</h2><p className="panel-note">카운터에 비치할 직원 결제용 QR입니다.</p></div><QrCode size={24}/></div>
        {merchantQrImageUrl ? <div className="qr-card-body">
          <img className="merchant-qr-image" src={merchantQrImageUrl} alt="매장 결제 QR 코드" />
          <div className="qr-card-copy">
            <strong>{merchantQr?.merchant?.name ?? '내 매장'}</strong>
            <span>직원 앱 또는 휴대폰 카메라로 스캔</span>
            <input value={merchantPayUrl} readOnly onFocus={(event) => event.target.select()} />
          </div>
          <div className="row-actions qr-actions">
            <button className="primary" onClick={downloadMerchantQrPdf}>PDF 다운로드</button>
            <button className="ghost" onClick={copyMerchantPayUrl}>링크 복사</button>
          </div>
        </div> : <p className="empty-state">매장 QR 정보를 불러오고 있어요.</p>}
      </article>}
      {!isMerchantAdmin && <article className="panel menu-panel">
        <div className="panel-title"><h2>운영 식당</h2><Coffee size={22}/></div>
        <div className="menu-chips single"><span>🥗 그린잇 식당</span></div>
        <p className="panel-note">현재 파일럿은 한 식당에서만 운영합니다.</p>
      </article>}
    </section>

    {!isPlatformAdmin && isMerchantAdmin && <section className="panel">
      <div className="panel-title">
        <div><h2>장부업체 관리</h2><p className="panel-note">거래를 허용할 회사를 검색해서 연결하거나, 새 회사 담당자를 초대합니다.</p></div>
        <span className="badge">{merchantCompanies?.items?.length ?? 0}곳</span>
      </div>
      <form className="product-form" onSubmit={searchCompanies}>
        <input value={companySearch} onChange={(event) => setCompanySearch(event.target.value)} placeholder="회사명 검색" />
        <button className="primary" disabled={busy || !companySearch.trim()}>검색</button>
      </form>
      {companySearchResults.length > 0 && <div className="product-list">
        {companySearchResults.map((company) => <article className="product-item" key={company.id}>
          <div><strong>{company.name}</strong><span>{company.status} · {company.biz_reg_no ?? '사업자번호 없음'}</span></div>
          <button className="ghost" onClick={() => linkCompany(company.id)} disabled={busy}>연결</button>
        </article>)}
      </div>}
      <form className="product-form" onSubmit={createAndLinkCompany}>
        <input value={newCompanyForm.name} onChange={(event) => setNewCompanyForm((form) => ({ ...form, name: event.target.value }))} placeholder="신규 회사명" required />
        <input value={newCompanyForm.owner_phone} onChange={(event) => setNewCompanyForm((form) => ({ ...form, owner_phone: event.target.value }))} placeholder="담당자 연락처" required />
        <button className="primary" disabled={busy}>신규 생성 + 초대</button>
      </form>
      {(merchantCompanies?.items?.length ?? 0) === 0
        ? <p className="empty-state">아직 연결된 장부업체가 없어요.</p>
        : <div className="table-wrap"><table><thead><tr><th>회사명</th><th>회사상태</th><th>연결상태</th><th>거래내역</th><th>계약</th><th>초대링크</th></tr></thead><tbody>{merchantCompanies.items.map((item) => {
          const link = inviteLink(item.invite);
          const companyName = item.company?.name ?? item.company_id;
          const txItems = (transactions?.items ?? []).filter((tx) => tx.company_id === item.company_id);
          const totalAmount = txItems.reduce((sum, tx) => sum + Math.abs(Number(tx.amount ?? 0)), 0);
          return <tr key={item.id}><td>{companyName}</td><td>{item.company?.status ?? '-'}</td><td>{item.status}</td><td><button className="ghost" onClick={() => setTxModal({ companyId: item.company_id, companyName, txItems, totalAmount, contract: item.contract })}>{txItems.length}건 보기</button></td><td><button className="ghost" onClick={() => openContractModal(item)}>계약</button></td><td>{link ? <button className="ghost" onClick={() => setInviteModal({ link, companyName })}>초대링크 보기</button> : '-'}</td></tr>;
        })}</tbody></table></div>}
    </section>}


    {!isPlatformAdmin && <section className="panel daily-menu-panel">
      <div className="panel-title">
        <div><h2>오늘 부페 메뉴</h2><p className="panel-note">오늘 나오는 메뉴를 입력하면 직원 앱 상품 선택 화면 상단에 표시됩니다.</p></div>
        <span className="badge">{dailyMenu?.service_date ?? '오늘'}</span>
      </div>
      {dailyMenu?.migration_required && <div className="alert error">오늘 메뉴 DB 마이그레이션이 아직 적용되지 않아 기본 메뉴만 표시 중이에요. 0006_merchant_daily_menus.sql 적용 후 저장이 활성화됩니다.</div>}
      <form className="daily-menu-form" onSubmit={saveDailyMenu}>
        <input value={dailyMenuForm.title} onChange={(event) => setDailyMenuForm((form) => ({ ...form, title: event.target.value }))} placeholder="제목" required />
        <textarea value={dailyMenuForm.menu_text} onChange={(event) => setDailyMenuForm((form) => ({ ...form, menu_text: event.target.value }))} placeholder="예: 김치찌개, 제육볶음, 현미밥, 계절 샐러드, 반찬 4종" required rows={4} />
        <button className="primary" disabled={busy || dailyMenu?.migration_required}>오늘 메뉴 저장</button>
      </form>
    </section>}


    {!isPlatformAdmin && <section className="panel product-panel">
      <div className="panel-title">
        <div><h2>식당 상품 관리</h2><p className="panel-note">직원 앱은 금액 입력 없이 여기 등록된 상품 중 하나를 선택해 결제합니다.</p></div>
        {isMerchantAdmin ? null : <span className="badge">{products?.merchant?.name ?? '운영 식당'}</span>}
      </div>
      {products?.migration_required && <div className="alert error">상품 DB 마이그레이션이 아직 적용되지 않아 기본 상품만 표시 중이에요. 0005_merchant_products.sql 적용 후 등록/수정이 활성화됩니다.</div>}
      <form className="product-form" onSubmit={createProduct}>
        <input value={productForm.name} onChange={(event) => setProductForm((form) => ({ ...form, name: event.target.value }))} placeholder="상품명" required />
        <input value={productForm.price} onChange={(event) => setProductForm((form) => ({ ...form, price: event.target.value }))} placeholder="가격" type="number" min="1" required />
        <input value={productForm.category} onChange={(event) => setProductForm((form) => ({ ...form, category: event.target.value }))} placeholder="카테고리" />
        <button className="primary" disabled={busy || products?.migration_required}>상품 등록</button>
      </form>
      {(products?.items?.length ?? 0) === 0
        ? <p className="empty-state">등록된 상품이 없어요. 첫 상품을 등록하면 직원 앱에 표시됩니다.</p>
        : <div className="product-list">{products.items.map((product) => <article className={product.is_active ? 'product-item' : 'product-item off'} key={product.id}>
          <div><strong>{product.name}</strong><span>{product.category ?? '기본'} · {Number(product.price).toLocaleString('ko-KR')}원</span></div>
          <button className="ghost" onClick={() => toggleProduct(product)} disabled={busy || products?.migration_required}>{product.is_active ? '숨김' : '판매중'}</button>
        </article>)}</div>}
    </section>}


    {!isPlatformAdmin && !isMerchantAdmin && <section className="panel settlement-panel">
      <div className="panel-title">
        <h2>정산 현황</h2>
        <span className="badge">{settlements?.period_ym ?? '이번 달'}</span>
      </div>
      <div className="settlement-grid">
        <div><span>정산 건수</span><strong>{settlements?.summary.settlement_count ?? 0}건</strong></div>
        <div><span>결제 건수</span><strong>{settlements?.summary.tx_count ?? 0}건</strong></div>
        <div><span>정산 금액</span><strong>{(settlements?.summary.total_amount ?? 0).toLocaleString('ko-KR')}원</strong></div>
        <div><span>송금 완료</span><strong>{settlements?.summary.paid_count ?? 0}건</strong></div>
      </div>
      {(settlements?.items?.length ?? 0) === 0
        ? <p className="empty-state">아직 생성된 정산서가 없어요. 월말 정산 데이터가 생성되면 여기에서 확인합니다.</p>
        : <div className="table-wrap"><table><thead><tr><th>기간</th><th>결제건수</th><th>금액</th><th>상태</th></tr></thead><tbody>{settlements.items.map((item) => <tr key={item.id}><td>{item.period_ym}</td><td>{item.tx_count}</td><td>{Number(item.total_amount).toLocaleString('ko-KR')}원</td><td>{item.status}</td></tr>)}</tbody></table></div>}
    </section>}

    {!isPlatformAdmin && !isMerchantAdmin && <section className="panel">
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
    </section>}
  </main>;
}

function App() {
  const missingEnv = assertEnv();
  const [session, setSession] = useState(null);
  const [booting, setBooting] = useState(true);
  const inviteToken = new URLSearchParams(window.location.search).get('invite');

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
  if (inviteToken) return <InviteClaimScreen token={inviteToken} missingEnv={missingEnv} session={session} onClaimed={() => { window.history.replaceState({}, '', '/'); supabase.auth.getSession().then(({ data }) => setSession(data.session)); }} />;
  if (!session) return <LoginScreen missingEnv={missingEnv} onLogin={setSession} />;
  return <Dashboard session={session} onLogout={logout} />;
}

createRoot(document.getElementById('root')).render(<App />);
