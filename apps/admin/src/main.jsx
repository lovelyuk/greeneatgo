import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AlertTriangle, Bell, Building2, CalendarDays, CheckCircle2, ChevronDown, Coffee, Download, FileSpreadsheet, FileText, Home, LogOut, Package, QrCode, RefreshCw, Search, Send, Settings, Utensils, Users, WalletCards, X, XCircle } from 'lucide-react';
import { createClient } from '@supabase/supabase-js';
import Cropper from 'react-easy-crop';
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
  const headers = {
    Authorization: `Bearer ${token}`,
    ...(options.headers ?? {}),
  };
  if (!(options.body instanceof FormData) && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...options,
    headers,
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
    <img src="/brand/greeneat_logo.png" alt="그린잇" />
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
  const [email, setEmail] = useState('');
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
      setError(loginError.message === 'Email not confirmed' ? '이메일 인증 설정이 켜져 있어 로그인할 수 없어요. Supabase에서 Confirm email을 꺼주세요.' : loginError.message);
      return;
    }
    onLogin(data.session);
  }

  return <main className="auth-page login-page">
    <section className="login-card">
      <div className="login-brand">
        <BrandMark />
        <p className="login-tagline">건강한 한 끼, 그린잇</p>
      </div>
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
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
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
        if (data.email) setEmail(data.email);
      } catch (inviteError) {
        setError(inviteError.message);
      } finally {
        setBusy(false);
      }
    }
    loadInvite();
  }, [token]);

  async function signUpAndClaim(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setMessage('');
    try {
      if (session) await supabase.auth.signOut();
      const { data, error: signUpError } = await supabase.auth.signUp({
        email: email.trim(),
        password,
        options: {
          data: { display_name: displayName.trim() || undefined },
        },
      });
      if (signUpError) throw signUpError;
      if (!data.session) throw new Error('Supabase Email Confirm이 켜져 있어 즉시 로그인이 막혔어요. Authentication > Providers > Email에서 Confirm email을 꺼주세요.');
      const authUser = data.user;
      if (!authUser?.id) throw new Error('가입된 사용자 정보를 찾을 수 없어요');
      await publicApiFetch(`/invites/${token}/claim`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${data.session.access_token}` },
        body: JSON.stringify({ display_name: displayName.trim() || null }),
      });
      setMessage('가입과 초대 연결이 완료됐어요. 바로 관리자 화면으로 이동합니다.');
      setTimeout(onClaimed, 500);
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
        <p>이메일과 비밀번호로 가입한 뒤 식당관리자 또는 회사관리자 계정으로 연결합니다.</p>
      </div>
    </section>
    <section className="login-card">
      <p className="eyebrow">CLAIM INVITE</p>
      <h2>초대 수락</h2>
      {missingEnv.length > 0 && <div className="alert error">Vercel 환경변수 누락: {missingEnv.join(', ')}</div>}
      {session && <div className="alert warning">현재 {session.user.email} 계정으로 로그인되어 있어요. 초대 수락 시 기존 계정 덮어쓰기를 막기 위해 자동 로그아웃 후 아래 새 이메일로 가입합니다.</div>}
      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert success">{message}</div>}
      {invite && <div className="profile-grid">
        <span>권한</span><strong>{invite.role === 'merchant_admin' ? '식당관리자' : '회사관리자'}</strong>
        <span>상태</span><strong>{invite.status}</strong>
        <span>만료</span><strong>{new Date(invite.expires_at).toLocaleString('ko-KR')}</strong>
      </div>}
      <form className="form" onSubmit={signUpAndClaim}>
        <label>이메일
          <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" placeholder="owner@example.com" readOnly={!!invite?.email} required />
        </label>
        <label>비밀번호
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" placeholder="6자리 이상 비밀번호" minLength="6" required />
        </label>
        <label>이름
          <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="표시 이름" />
        </label>
        <button className="primary" disabled={busy || missingEnv.length > 0 || !invite}>새 계정으로 가입하고 초대 수락</button>
      </form>
    </section>
  </main>;
}

const krw = (value) => `₩${Number(value ?? 0).toLocaleString('ko-KR')}`;
const dateKey = (value) => value ? new Date(value).toISOString().slice(0, 10) : new Date().toISOString().slice(0, 10);
const dayLabel = (key) => new Date(`${key}T00:00:00`).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' });
const todayInput = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });

async function fileToBase64(file) {
  if (!file.type.startsWith('image/')) throw new Error('이미지 파일만 선택해 주세요.');
  if (file.size > 5 * 1024 * 1024) throw new Error('이미지는 5MB 이하여야 해요.');
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1]);
    reader.onerror = () => reject(new Error('이미지를 읽지 못했어요.'));
    reader.readAsDataURL(file);
  });
}

function validateCropSource(file) {
  const extension = file.name.split('.').pop()?.toLowerCase();
  if (!['jpg', 'jpeg', 'png', 'webp'].includes(extension) || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    throw new Error('JPG, JPEG, PNG, WEBP 이미지만 선택해 주세요.');
  }
  if (file.size > 20 * 1024 * 1024) throw new Error('원본 이미지는 20MB 이하여야 해요.');
}

function cropToWebp(sourceUrl, area, filename) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = 800;
      canvas.height = 800;
      const context = canvas.getContext('2d');
      if (!context) { reject(new Error('이미지 크롭을 처리하지 못했어요.')); return; }
      context.drawImage(image, area.x, area.y, area.width, area.height, 0, 0, 800, 800);
      canvas.toBlob((blob) => {
        if (!blob) { reject(new Error('WebP 이미지로 변환하지 못했어요.')); return; }
        resolve(new File([blob], `${filename.replace(/\.[^.]+$/, '') || 'product'}-800.webp`, { type: 'image/webp' }));
      }, 'image/webp', 0.92);
    };
    image.onerror = () => reject(new Error('선택한 이미지를 불러오지 못했어요.'));
    image.src = sourceUrl;
  });
}

function ImageCropModal({ request, onCancel, onApply }) {
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [area, setArea] = useState(null);
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    setCrop({ x: 0, y: 0 }); setZoom(1); setArea(null); setApplying(false);
  }, [request?.sourceUrl]);
  useEffect(() => {
    if (!request) return undefined;
    const closeOnEscape = (event) => { if (event.key === 'Escape' && !applying) onCancel(); };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [request, applying, onCancel]);

  if (!request) return null;
  async function apply() {
    if (!area) return;
    setApplying(true);
    try { onApply(await cropToWebp(request.sourceUrl, area, request.filename)); }
    catch (cropError) { setApplying(false); request.onError(cropError.message); }
  }
  return <div className="modal-backdrop crop-backdrop" onClick={() => !applying && onCancel()}>
    <section className="image-crop-modal" role="dialog" aria-modal="true" aria-labelledby="crop-title" onClick={(event) => event.stopPropagation()}>
      <header className="crop-header"><div><h2 id="crop-title">상품 이미지 자르기</h2><p>정사각형 안에 보일 영역을 맞춰 주세요.</p></div><button type="button" className="ghost icon-button" onClick={onCancel} disabled={applying} aria-label="닫기"><X size={20}/></button></header>
      <div className="crop-stage"><Cropper image={request.sourceUrl} crop={crop} zoom={zoom} aspect={1} minZoom={1} maxZoom={3} cropShape="rect" showGrid onCropChange={setCrop} onZoomChange={setZoom} onCropComplete={(_, pixels) => setArea(pixels)} /></div>
      <div className="crop-controls"><label>확대·축소<input type="range" min="1" max="3" step="0.01" value={zoom} onChange={(event) => setZoom(Number(event.target.value))}/></label><p>드래그·핀치·마우스 휠로 위치와 확대만 조정할 수 있어요. 최종 파일은 800×800 WebP로 저장됩니다.</p></div>
      <footer className="crop-footer"><button type="button" className="ghost" onClick={onCancel} disabled={applying}>취소</button><button type="button" className="primary" onClick={apply} disabled={!area || applying}>{applying ? '적용 중...' : '적용'}</button></footer>
    </section>
  </div>;
}

function buildTransactionRows(rawItems, range, q) {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();
  const from = new Date(`${range.from || todayInput()}T00:00:00`);
  const to = new Date(`${range.to || todayInput()}T23:59:59`);
  const query = q.trim().toLowerCase();
  const normalized = rawItems.map((tx, index) => {
    const rawAmount = Number(tx.amount ?? tx.product_price ?? 0);
    const cancelled = tx.status === 'cancelled' || tx.status === 'refund' || tx.kind === 'refund' || tx.kind === 'cancel';
    const amount = cancelled ? -Math.abs(rawAmount) : Math.abs(rawAmount);
    return {
      id: tx.id ?? `mock-${index}`,
      created_at: tx.created_at ?? new Date(y, m, Math.max(1, now.getDate() - index), 12, 10 + index).toISOString(),
      time: tx.created_at ? new Date(tx.created_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }) : '12:00',
      employee_name: tx.employee_name ?? tx.user_name ?? tx.display_name ?? '직원',
      employee_no: tx.employee_no ?? tx.user_id?.slice(0, 8) ?? '-',
      department: tx.department ?? '-',
      menu: tx.product_name ?? tx.meal_window ?? '구내식당 식권',
      pay_type: tx.pay_type === 'subsidized' ? '보조금' : tx.pay_type === 'voucher' ? '식권' : tx.pay_type === 'direct' ? '토스결제' : '장부',
      amount,
      company_subsidy_amount: tx.company_subsidy_amount,
      restaurant_subsidy_amount: tx.restaurant_subsidy_amount,
      employee_paid_amount: tx.employee_paid_amount,
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
  const [range, setRange] = useState({ from: todayInput().slice(0, 8) + '01', to: todayInput() });
  const [query, setQuery] = useState('');
  const [collapsed, setCollapsed] = useState({});
  const [apiError, setApiError] = useState('');
  const [serverSummary, setServerSummary] = useState(null);
  const [serverDays, setServerDays] = useState(null);
  const [settlements, setSettlements] = useState([]);

  useEffect(() => {
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
      document.removeEventListener('keydown', onKeyDown);
      returnFocusRef.current?.focus?.();
    };
  }, [exporting, onClose]);

  useEffect(() => {
    if (!txModal.companyId) {
      setLoading(true);
      const timer = setTimeout(() => setLoading(false), 260);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [range, query, activeTab, txModal.companyId]);

  function rangeParams() {
    return { from: range.from, to: range.to };
  }

  const invalidRange = !range.from || !range.to || range.from > range.to;

  useEffect(() => {
    if (!txModal.companyId || invalidRange) {
      if (invalidRange) setApiError('시작일은 종료일보다 늦을 수 없어요.');
      return;
    }
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
          apiFetch(`/admin/merchant/companies/${txModal.companyId}/settlements?${params}`, token),
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
    pay_type: item.pay_type === 'subsidized' ? '보조금' : item.pay_type === 'voucher' ? '식권' : item.pay_type === 'direct' ? '토스결제' : (item.pay_type ?? '장부'),
  }))) : null, [serverDays]);

  const rows = useMemo(() => serverRows ?? buildTransactionRows(txModal.txItems, range, query), [serverRows, txModal.txItems, range, query]);
  const summary = useMemo(() => {
    if (serverSummary) {
      return {
        total: serverSummary.total_amount ?? 0,
        count: serverSummary.total_count ?? 0,
        cancelCount: serverSummary.cancel_count ?? 0,
        unsettled: serverSummary.unsettled_amount ?? 0,
        selectedPeriod: `${serverSummary.period?.from ?? range.from} ~ ${serverSummary.period?.to ?? range.to}`,
      };
    }
    const total = rows.reduce((sum, row) => sum + Number(row.amount ?? 0), 0);
    const cancelCount = rows.filter((row) => row.status === 'refund').length;
    return { total, count: rows.length, cancelCount, unsettled: Math.max(0, total), selectedPeriod: `${range.from} ~ ${range.to}` };
  }, [rows, serverSummary]);
  const unpaid = settlements.filter((item) => item.status !== '입금완료');
  const unpaidAmount = unpaid.reduce((sum, item) => sum + Number(item.amount ?? 0), 0);
  const contract = serverSummary?.contract ?? txModal.contract ?? null;
  const restaurantContribution = rows.reduce((sum, row) => {
    const value = Number(row.restaurant_subsidy_amount ?? 0);
    return sum + (row.status === 'refund' ? -Math.abs(value) : Math.abs(value));
  }, 0);
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
        '날짜,시간,부서,이름,사번,메뉴/내역,금액',
        ...rows.map((row) => `${String(row.created_at ?? '').slice(0, 10)},${row.time},${row.department ?? '-'},${row.employee_name},${row.employee_no},${row.menu},${row.amount}`),
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

  async function createSettlement() {
    if (!txModal.companyId || invalidRange) return;
    setExporting(true);
    setApiError('');
    try {
      await apiFetch(`/admin/merchant/companies/${txModal.companyId}/settlements`, token, {
        method: 'POST',
        body: JSON.stringify({ period_from: range.from, period_to: range.to }),
      });
      const params = `from=${encodeURIComponent(range.from)}&to=${encodeURIComponent(range.to)}`;
      const data = await apiFetch(`/admin/merchant/companies/${txModal.companyId}/settlements?${params}`, token);
      setSettlements(data.items ?? []);
      setActiveTab('settlements');
    } catch (settlementError) {
      setApiError(settlementError.message);
    } finally {
      setExporting(false);
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
            {contract && <span className="contract-badge">계약: {contract.cycle_label ?? contract.cycle}{contract.unit_price != null ? ` · 단가 ${Number(contract.unit_price).toLocaleString('ko-KR')}원` : ''}{contract.subsidy_enabled ? ' · 보조금 계약' : ''}</span>}
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
          <div className="date-range"><input aria-label="시작일" type="date" value={range.from} onChange={(e) => setRange((prev) => ({ ...prev, from: e.target.value }))}/><span>~</span><input aria-label="종료일" type="date" value={range.to} onChange={(e) => setRange((prev) => ({ ...prev, to: e.target.value }))}/></div>
          <label className="tx-search"><Search size={16}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="부서/이름/사번 검색" /></label>
          {invalidRange && <div className="alert error">시작일은 종료일보다 늦을 수 없어요.</div>}
        </div>
        <div className="vendor-modal-body">
          {apiError && <div className="alert error">상세 API 확인 필요: {apiError}</div>}
          {loading ? <TransactionSkeleton /> : <>
            <section className="vendor-summary-grid">
              <article><span>총 이용금액</span><strong>{krw(summary.total)}</strong></article>
              <article><span>총 이용건수</span><strong>{summary.count}건 {summary.cancelCount ? `(취소 ${summary.cancelCount})` : ''}</strong></article>
              <article className="main-amount"><span>미정산 잔액</span><strong>{krw(summary.unsettled)}</strong></article>
              <article><span>선택 정산 기간</span><strong><CalendarDays size={18}/>{summary.selectedPeriod}</strong></article>
            </section>
            {restaurantContribution !== 0 && <div className="restaurant-contribution"><span>선택 기간 식당 부담금 (정산 제외)</span><strong>{krw(restaurantContribution)}</strong></div>}
            {rows.length === 0 ? <p className="vendor-empty">📒 선택한 기간에 거래가 없습니다</p> : <div className="table-wrap"><table><thead><tr><th>날짜</th><th>시간</th><th>부서</th><th>이름</th><th>사번</th><th>메뉴/내역</th><th>구분</th><th>회사 청구액</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id} className={row.status === 'refund' ? 'refund-row' : ''}><td>{String(row.created_at ?? '').slice(0, 10)}</td><td>{row.time}</td><td>{row.department ?? '-'}</td><td>{row.employee_name}</td><td>{row.employee_no}</td><td>{row.menu} {row.status === 'refund' && <span className="refund-tag">환불</span>}</td><td><span className={`pay-type-badge ${row.pay_type === '보조금' ? 'subsidized' : ''}`}>{row.pay_type}</span></td><td className="money">{krw(row.amount)}{row.pay_type === '보조금' && <small className="subsidy-breakdown">총 {krw(Number(row.employee_paid_amount ?? 0) + Number(row.company_subsidy_amount ?? 0) + Number(row.restaurant_subsidy_amount ?? 0))} · 직원 {krw(row.employee_paid_amount ?? 0)} · 식당 {krw(row.restaurant_subsidy_amount ?? 0)}</small>}</td></tr>)}</tbody></table></div>}
          </>}
        </div>
        <footer className="vendor-modal-footer"><button className="primary export-button" onClick={createSettlement} disabled={exporting || invalidRange}>선택 기간 정산 생성</button><button className="primary export-button" onClick={() => download('xlsx')} disabled={exporting || invalidRange}><Download size={17}/> 엑셀 다운로드</button><button className="primary export-button" onClick={() => download('pdf')} disabled={exporting || invalidRange}><FileText size={17}/> PDF 청구서</button><button className="ghost" onClick={onClose} disabled={exporting}>닫기</button></footer>
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

function VoucherProductsPanel({ items, migrationRequired, token, busy, cropImage, uploadImage, deleteImage, onChanged, setBusy, setError, setMessage }) {
  const blank = { name: '', voucher_count: '0', bonus_count: '0', unit_price: '', discount_rate: '0', status: 'active', display_order: '0', image_url: '', is_event: false, event_start_at: '', event_end_at: '' };
  const [form, setForm] = useState(blank);
  const [editingId, setEditingId] = useState(null);
  const [pendingImage, setPendingImage] = useState(null);
  const [pendingPreview, setPendingPreview] = useState('');
  const count = Number(form.voucher_count || 0);
  const bonus = Number(form.bonus_count || 0);
  const discount = Number(form.discount_rate || 0);
  const salePrice = Math.round(Number(form.unit_price || 0) * count * (100 - discount) / 100 * 100) / 100;

  function dateTimeInput(value) {
    if (!value) return '';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return '';
    return new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  }
  function displayEventPeriod(item) {
    if (!item.is_event) return '';
    const start = new Date(item.event_start_at).toLocaleString('ko-KR');
    const end = new Date(item.event_end_at).toLocaleString('ko-KR');
    return `${start} ~ ${end}`;
  }
  function resetPendingImage() {
    if (pendingPreview) URL.revokeObjectURL(pendingPreview);
    setPendingImage(null); setPendingPreview('');
  }
  function edit(item) {
    resetPendingImage();
    setEditingId(item.id);
    setForm({
      ...blank,
      ...Object.fromEntries(Object.entries(item).filter(([key]) => !['is_event', 'event_start_at', 'event_end_at'].includes(key)).map(([key, value]) => [key, value == null ? '' : String(value)])),
      is_event: !!item.is_event,
      event_start_at: dateTimeInput(item.event_start_at),
      event_end_at: dateTimeInput(item.event_end_at),
    });
  }
  async function chooseImage(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    const cropped = await cropImage(file);
    if (!cropped) return;
    resetPendingImage();
    setPendingImage(cropped);
    setPendingPreview(URL.createObjectURL(cropped));
  }
  async function save(event) {
    event.preventDefault();
    if (bonus > 0 && discount > 0 && !window.confirm('보너스와 할인을 동시에 적용하시겠어요?')) return;
    if (form.is_event && (!form.event_start_at || !form.event_end_at)) { setError('이벤트 시작일시와 종료일시를 모두 입력해 주세요.'); return; }
    if (form.is_event && new Date(form.event_end_at) <= new Date(form.event_start_at)) { setError('이벤트 종료일시는 시작일시보다 늦어야 해요.'); return; }
    let uploadedImageUrl = '';
    let persisted = false;
    setBusy(true); setError('');
    try {
      if (pendingImage) uploadedImageUrl = await uploadImage(pendingImage);
      const body = {
        name: form.name.trim(), voucher_count: count, bonus_count: bonus,
        unit_price: Number(form.unit_price), discount_rate: discount, status: form.status,
        display_order: Number(form.display_order || 0), image_url: uploadedImageUrl || form.image_url || null,
        ...(!migrationRequired ? {
          is_event: !!form.is_event,
          event_start_at: form.is_event ? new Date(form.event_start_at).toISOString() : null,
          event_end_at: form.is_event ? new Date(form.event_end_at).toISOString() : null,
        } : {}),
      };
      await apiFetch(`/admin/voucher-products${editingId ? `/${editingId}` : ''}`, token, { method: editingId ? 'PATCH' : 'POST', body: JSON.stringify(body) });
      persisted = true;
      setMessage(editingId ? '식권 패키지를 수정했어요.' : '식권 패키지를 등록했어요.');
      setEditingId(null); setForm(blank); resetPendingImage(); await onChanged();
    } catch (saveError) {
      if (uploadedImageUrl && !persisted) await deleteImage(uploadedImageUrl);
      setError(saveError.message);
    } finally { setBusy(false); }
  }
  async function toggle(item) {
    setBusy(true); setError('');
    try {
      await apiFetch(`/admin/voucher-products/${item.id}`, token, { method: 'PATCH', body: JSON.stringify({ status: item.status === 'active' ? 'inactive' : 'active' }) });
      setMessage(item.status === 'active' ? '식권 패키지를 숨겼어요.' : '식권 패키지 판매를 재개했어요.'); await onChanged();
    } catch (toggleError) { setError(toggleError.message); } finally { setBusy(false); }
  }
  return <section className="panel voucher-panel">
    <div className="panel-title"><div><h2>판매 상품(일반)</h2><p className="panel-note">삭제하지 않고 숨김/판매 재개합니다. 이벤트 상품은 설정 기간에만 자동 노출됩니다.</p></div><span className="badge">{items.length}개</span></div>
    {migrationRequired && <div className="alert error">이벤트 상품 DB 마이그레이션이 아직 적용되지 않았어요. 0020_voucher_product_events.sql 적용 후 이벤트 등록이 활성화됩니다.</div>}
    <form className="voucher-form" onSubmit={save}>
      <input value={form.name} onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} placeholder="패키지명" required />
      <label>기본 장수<input type="number" min="1" max="1000" value={form.voucher_count} onChange={(e) => setForm((p) => ({ ...p, voucher_count: e.target.value }))} required /></label>
      <div className="quick-buttons">{[1, 5, 10].map((n) => <button type="button" className="ghost" key={n} onClick={() => setForm((p) => ({ ...p, voucher_count: String(Math.min(1000, Math.max(0, Number(p.voucher_count) || 0) + n)) }))}>+{n}장</button>)}</div>
      <label>보너스 장수<input type="number" min="0" max="1000" value={form.bonus_count} onChange={(e) => setForm((p) => ({ ...p, bonus_count: e.target.value }))} /></label>
      <label>장당 정가<input type="number" min="1" step="0.01" value={form.unit_price} onChange={(e) => setForm((p) => ({ ...p, unit_price: e.target.value }))} required /></label>
      <label>할인율(%)<input type="number" min="0" max="99.99" step="0.01" value={form.discount_rate} onChange={(e) => setForm((p) => ({ ...p, discount_rate: e.target.value }))} /></label>
      <label>상태<select value={form.status} onChange={(e) => setForm((p) => ({ ...p, status: e.target.value }))}><option value="active">판매중</option><option value="inactive">숨김</option></select></label>
      <label>노출순서<input type="number" value={form.display_order} onChange={(e) => setForm((p) => ({ ...p, display_order: e.target.value }))} /></label>
      <label className="event-toggle"><input type="checkbox" checked={form.is_event} onChange={(e) => setForm((p) => ({ ...p, is_event: e.target.checked }))} disabled={migrationRequired}/> 🎉 이벤트 상품으로 등록</label>
      {form.is_event && <>
        <label>이벤트 시작일시<input type="datetime-local" value={form.event_start_at} onChange={(e) => setForm((p) => ({ ...p, event_start_at: e.target.value }))} required /></label>
        <label>이벤트 종료일시<input type="datetime-local" min={form.event_start_at} value={form.event_end_at} onChange={(e) => setForm((p) => ({ ...p, event_end_at: e.target.value }))} required /></label>
      </>}
      <label className="image-picker compact">패키지 이미지<input type="file" accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp" onChange={chooseImage} disabled={busy}/></label>
      <div className="voucher-preview">미리보기 <strong>{count + bonus}장 · {krw(salePrice)}</strong><span>장당 {krw((count + bonus) ? salePrice / (count + bonus) : 0)}</span>{form.is_event && <span>🎉 노출 기간: {form.event_start_at || '시작일시'} ~ {form.event_end_at || '종료일시'} · 종료 후 자동 숨김</span>}{(pendingPreview || form.image_url) && <img src={pendingPreview || form.image_url} alt="식권 패키지 미리보기"/>}</div>
      {bonus > 0 && discount > 0 && <div className="alert warning">보너스와 할인율이 동시에 적용됩니다. 판매가와 총 장수를 다시 확인하세요.</div>}
      <div className="row-actions"><button className="primary" disabled={busy}>{editingId ? '수정 저장' : '상품 등록'}</button>{editingId && <button type="button" className="ghost" onClick={() => { setEditingId(null); setForm(blank); resetPendingImage(); }}>취소</button>}</div>
    </form>
    <div className="product-list">{items.map((item) => <article className={item.status === 'active' ? 'product-item' : 'product-item off'} key={item.id}>{item.image_url ? <img className="product-image-preview" src={item.image_url} alt=""/> : <div className="product-image-placeholder">이미지 없음</div>}<div className="product-copy"><strong>{item.name}</strong><span>{item.voucher_count}+{item.bonus_count}장 · 판매가 {krw(item.sale_price)} · 순서 {item.display_order}</span><span className={`exposure-status ${item.exposure_status}`}>{item.exposure_label}</span>{item.is_event && <span className="event-period">{displayEventPeriod(item)}</span>}</div><div className="row-actions"><button className="ghost" onClick={() => edit(item)}>수정</button><button className="ghost" onClick={() => toggle(item)}>{item.status === 'active' ? '숨김' : '판매 재개'}</button></div></article>)}</div>
  </section>;
}

function NotificationPanel({ token, history, migrationRequired, onSent, setMessage }) {
  const [form, setForm] = useState({ target_type: 'all', title: '', body: '' });
  const [audience, setAudience] = useState(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const submitLock = useRef(false);
  const idempotencyKey = useRef(null);
  const confirmationResolver = useRef(null);
  const [confirmation, setConfirmation] = useState(null);

  function requestConfirmation(audienceInfo) {
    setConfirmation(audienceInfo);
    return new Promise((resolve) => { confirmationResolver.current = resolve; });
  }

  function closeConfirmation(confirmed) {
    const resolve = confirmationResolver.current;
    confirmationResolver.current = null;
    setConfirmation(null);
    resolve?.(confirmed);
  }

  function updateForm(field, value) {
    idempotencyKey.current = null;
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function loadAudience(targetType = form.target_type) {
    if (migrationRequired) return null;
    try {
      const data = await apiFetch(`/admin/notifications/audience?target_type=${targetType}`, token);
      setAudience(data); setError(''); return data;
    } catch (audienceError) { setAudience(null); setError(audienceError.message); return null; }
  }

  useEffect(() => { loadAudience(form.target_type); }, [form.target_type, migrationRequired]);

  async function send(event) {
    event.preventDefault();
    if (submitLock.current) return;
    const title = form.title.trim();
    const body = form.body.trim();
    if (!title || !body) { setError('공지 제목과 내용을 입력해 주세요.'); return; }
    submitLock.current = true;
    setSending(true); setError('');
    try {
      const latestAudience = await loadAudience();
      if (!latestAudience) return;
      if (!latestAudience.target_count) { setError('발송 대상이 없습니다. 앱에서 알림을 허용한 사용자가 있는지 확인해 주세요.'); return; }
      const confirmed = await requestConfirmation(latestAudience);
      if (!confirmed) return;
      idempotencyKey.current ??= crypto.randomUUID();
      const result = await apiFetch('/admin/notifications', token, {
        method: 'POST', body: JSON.stringify({
          title, body, target_type: form.target_type,
          idempotency_key: idempotencyKey.current,
          expected_target_count: latestAudience.target_count,
          expected_device_count: latestAudience.device_count,
        }),
      });
      idempotencyKey.current = null;
      setForm((current) => ({ ...current, title: '', body: '' }));
      setPreviewOpen(false);
      await onSent();
      setMessage(`${result.target_count}명에게 발송을 시도해 ${result.success_count}명에게 FCM이 접수됐어요.`);
    } catch (sendError) { setError(sendError.message); }
    finally { submitLock.current = false; setSending(false); }
  }

  return <section className="panel notification-panel">
    <div className="panel-title"><div><h2>알림 발송</h2><p className="panel-note">장부직원과 일반사용자 앱으로 공지·이벤트 알림을 수동 발송합니다.</p></div><button type="button" className="ghost notification-history-button" onClick={() => setHistoryOpen(true)}><CalendarDays size={18}/> 발송 이력</button></div>
    {migrationRequired && <div className="alert error">0022_push_notifications.sql 적용 후 공지 발송을 사용할 수 있어요.</div>}
    {error && <div className="alert error">{error}</div>}
    <form className="notification-form" onSubmit={send}>
      <fieldset disabled={sending || migrationRequired}>
        <legend>발송 대상</legend>
        <label><input type="radio" name="notification-target" value="all" checked={form.target_type === 'all'} onChange={(event) => updateForm('target_type', event.target.value)}/> 전체 사용자 <small>장부직원 + 일반사용자</small></label>
        <label><input type="radio" name="notification-target" value="voucher_only" checked={form.target_type === 'voucher_only'} onChange={(event) => updateForm('target_type', event.target.value)}/> 일반 사용자만 <small>개인 식권 구매자</small></label>
      </fieldset>
      <div className="notification-audience">{audience ? <><strong>발송 가능 {audience.target_count}명</strong><span>등록 기기 {audience.device_count}대 · 전체 조건 대상 {audience.eligible_count}명</span></> : <span>대상 인원을 확인하고 있어요.</span>}</div>
      <label>제목<input value={form.title} maxLength="120" onChange={(event) => updateForm('title', event.target.value)} placeholder="예: 임시 휴무 안내" disabled={sending || migrationRequired} required/></label>
      <label>내용<textarea value={form.body} maxLength="1000" rows="5" onChange={(event) => updateForm('body', event.target.value)} placeholder="앱 알림에 표시할 내용을 입력해 주세요." disabled={sending || migrationRequired} required/><small>{form.body.length}/1000</small></label>
      {previewOpen && <div className="notification-preview"><span>앱 알림 미리보기</span><strong>{form.title.trim() || '공지 제목'}</strong><p>{form.body.trim() || '공지 내용이 여기에 표시됩니다.'}</p></div>}
      <div className="row-actions"><button type="button" className="ghost" onClick={() => setPreviewOpen((open) => !open)} disabled={migrationRequired}>{previewOpen ? '미리보기 닫기' : '미리보기'}</button><button className="primary" disabled={sending || migrationRequired || !audience?.target_count}><Send size={17}/>{sending ? '발송 중...' : '발송하기'}</button></div>
    </form>
    {historyOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setHistoryOpen(false); }}>
      <div className="modal-card notification-history-modal" role="dialog" aria-modal="true" aria-labelledby="notification-history-title">
        <button type="button" className="modal-close" aria-label="닫기" onClick={() => setHistoryOpen(false)}><X size={20}/></button>
        <div className="notification-history-heading">
          <div className="notification-history-icon"><CalendarDays size={24}/></div>
          <div><span className="eyebrow">공지 관리</span><h2 id="notification-history-title">발송 이력</h2><p>최근 공지의 대상과 FCM 접수 결과를 확인할 수 있어요.</p></div>
        </div>
        {(history?.length ?? 0) === 0 ? <p className="empty-state">아직 발송한 공지가 없어요.</p> : <div className="table-wrap notification-history-table"><table><thead><tr><th>날짜</th><th>대상</th><th>제목·내용</th><th>사용자 접수</th><th>기기 성공/실패</th></tr></thead><tbody>{history.map((item) => <tr key={item.id}><td>{new Date(item.sent_at).toLocaleString('ko-KR')}</td><td><span className="history-target-badge">{item.target_type === 'voucher_only' ? '일반사용자' : '전체'}</span></td><td><strong>{item.title}</strong><small>{item.body}</small></td><td>{item.success_count}/{item.target_count}명</td><td><strong className={item.failure_device_count ? 'history-partial' : 'history-success'}>{item.success_device_count}대</strong> / {item.failure_device_count}대</td></tr>)}</tbody></table></div>}
        <p className="panel-note">성공 수는 사용자가 알림을 열었는지가 아니라 FCM 서버가 접수한 기준입니다.</p>
        <div className="modal-actions"><button type="button" className="primary" onClick={() => setHistoryOpen(false)}>확인</button></div>
      </div>
    </div>}
    {confirmation && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeConfirmation(false); }}>
      <div className="modal-card notification-confirm-modal" role="dialog" aria-modal="true" aria-labelledby="notification-confirm-title">
        <button type="button" className="modal-close" aria-label="닫기" onClick={() => closeConfirmation(false)}><X size={20}/></button>
        <div className="notification-confirm-icon"><Send size={28}/></div>
        <div className="notification-confirm-copy">
          <span className="eyebrow">공지 발송 확인</span>
          <h2 id="notification-confirm-title">이 공지를 발송할까요?</h2>
          <p>발송이 시작되면 취소할 수 없어요. 대상과 내용을 마지막으로 확인해 주세요.</p>
        </div>
        <div className="notification-confirm-stats">
          <div><span>발송 대상</span><strong>{confirmation.target_count}명</strong></div>
          <div><span>등록 기기</span><strong>{confirmation.device_count}대</strong></div>
        </div>
        <div className="notification-confirm-preview">
          <span>{form.target_type === 'voucher_only' ? '일반 사용자' : '전체 사용자'}</span>
          <strong>{form.title.trim()}</strong>
          <p>{form.body.trim()}</p>
        </div>
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={() => closeConfirmation(false)}>다시 확인</button>
          <button type="button" className="primary" onClick={() => closeConfirmation(true)}><Send size={17}/> 공지 발송</button>
        </div>
      </div>
    </div>}
  </section>;
}

function EmployeeBulkModal({ token, onClose, onConfirmed }) {
  const inputRef = useRef(null);
  const [preview, setPreview] = useState(null);
  const [fileName, setFileName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function downloadTemplate() {
    setError('');
    try {
      const response = await fetch(`${apiBaseUrl}/admin/employees/template`, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) throw new Error('양식을 다운로드하지 못했어요.');
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url; link.download = '직원_일괄등록_양식.xlsx'; link.click();
      URL.revokeObjectURL(url);
    } catch (downloadError) { setError(downloadError.message); }
  }

  async function parseFile(file) {
    if (!file) return;
    if (!/\.(xlsx|csv)$/i.test(file.name)) { setError('.xlsx 또는 .csv 파일만 선택해 주세요.'); return; }
    setBusy(true); setError(''); setPreview(null); setFileName(file.name);
    const formData = new FormData(); formData.append('file', file);
    try {
      setPreview(await apiFetch('/admin/employees/bulk-upload/parse', token, { method: 'POST', body: formData }));
    } catch (parseError) { setError(parseError.message); }
    finally { setBusy(false); }
  }

  function downloadErrors() {
    const safeCell = (value) => {
      const text = String(value ?? '');
      return /^[=+\-@]/.test(text) ? `'${text}` : text;
    };
    const escape = (value) => `"${safeCell(value).replaceAll('"', '""')}"`;
    const lines = ['행,부서,이름,사번,전화번호,오류', ...(preview?.errors ?? []).map((row) =>
      [row.row, row.department, row.name, row.employee_no, row.phone, row.reason].map(escape).join(','))];
    const url = URL.createObjectURL(new Blob(['\ufeff', lines.join('\r\n')], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = '직원_일괄등록_오류.csv'; link.click();
    URL.revokeObjectURL(url);
  }

  async function confirm() {
    if (!preview?.valid?.length) return;
    setBusy(true); setError('');
    try {
      const data = await apiFetch('/admin/employees/bulk-upload/confirm', token, {
        method: 'POST', body: JSON.stringify({ valid_rows: preview.valid }),
      });
      await onConfirmed(data.created_count);
    } catch (confirmError) { setError(confirmError.message); }
    finally { setBusy(false); }
  }

  return <div className="modal-backdrop bulk-backdrop" onClick={() => !busy && onClose()}>
    <section className={`employee-bulk-modal ${preview ? 'preview' : ''}`} role="dialog" aria-modal="true" aria-labelledby="bulk-title" onClick={(event) => event.stopPropagation()}>
      <header className="bulk-header"><div><h2 id="bulk-title">{preview ? '업로드 결과 확인' : '직원 일괄등록'}</h2>{fileName && <p>{fileName}</p>}</div><button className="ghost icon-button" onClick={onClose} disabled={busy} aria-label="닫기"><X size={20}/></button></header>
      {!preview ? <div className="bulk-body">
        <section className="bulk-step"><strong>Step 1. 양식 다운로드</strong><p>헤더 순서를 바꾸지 말고 최대 500명까지 작성해 주세요.</p><button className="ghost" onClick={downloadTemplate}><Download size={17}/> 엑셀 양식 다운로드</button></section>
        <section className="bulk-step"><strong>Step 2. 작성한 파일 업로드</strong>
          <div className="bulk-dropzone" role="button" tabIndex={0} onClick={() => inputRef.current?.click()} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') inputRef.current?.click(); }} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); parseFile(event.dataTransfer.files?.[0]); }}>
            <FileSpreadsheet size={38}/><b>{busy ? '파일 확인 중...' : '파일을 드래그하거나 클릭해서 선택'}</b><span>.xlsx, .csv 지원 · 최대 500행</span>
            <input ref={inputRef} hidden type="file" accept=".xlsx,.csv" onChange={(event) => parseFile(event.target.files?.[0])}/>
          </div>
        </section>
      </div> : <div className="bulk-body preview-body">
        <div className="bulk-counts"><strong className="valid-count">✅ 정상 {preview.valid.length}건</strong><strong className="error-count">⚠️ 에러 {preview.errors.length}건</strong></div>
        <section><h3>정상 {preview.valid.length}건</h3>{preview.valid.length === 0 ? <p className="empty-state">등록 가능한 행이 없어요.</p> : <div className="table-wrap bulk-valid-table"><table><thead><tr><th>부서</th><th>이름</th><th>사번</th><th>전화번호</th></tr></thead><tbody>{preview.valid.map((row) => <tr key={row.row}><td>{row.department || '-'}</td><td>{row.name}</td><td>{row.employee_no}{row.auto_generated && <small> 자동</small>}</td><td>{row.phone}</td></tr>)}</tbody></table></div>}</section>
        {preview.errors.length > 0 && <section className="bulk-errors"><div className="bulk-error-title"><h3>에러 {preview.errors.length}건</h3><button className="ghost" onClick={downloadErrors}><Download size={16}/> 에러 목록 다운로드</button></div>{preview.errors.map((row) => <div className="bulk-error-row" key={`${row.row}-${row.reason}`}><strong>{row.row}행: {row.reason}</strong><span>{row.name || '이름 없음'} · {row.phone || '전화번호 없음'}</span></div>)}</section>}
      </div>}
      {error && <div className="alert error bulk-alert">{error}</div>}
      <footer className="bulk-footer">{preview ? <button className="ghost" onClick={() => { setPreview(null); setError(''); }} disabled={busy}>이전</button> : <button className="ghost" onClick={onClose} disabled={busy}>닫기</button>}<button className="primary" onClick={confirm} disabled={!preview?.valid?.length || busy}>{busy && preview ? '등록 중...' : `정상 ${preview?.valid?.length ?? 0}건만 등록 확정`}</button></footer>
    </section>
  </div>;
}

function AnnouncementReviewPanel({ token, section }) {
  const [data, setData] = useState({ items: [] });
  const [error, setError] = useState('');
  const [form, setForm] = useState({ title: '', content: '', pinned: false, send_push: false });
  const [sort, setSort] = useState('latest');
  const load = async () => { try { setData(await apiFetch(section === 'announcements' ? '/admin/announcements' : `/admin/reviews?sort=${sort}`, token)); setError(''); } catch (e) { setError(e.message); } };
  useEffect(() => { load(); }, [section, sort]);
  async function publish(e) { e.preventDefault(); try { await apiFetch('/admin/announcements', token, { method: 'POST', body: JSON.stringify(form) }); setForm({ title: '', content: '', pinned: false, send_push: false }); await load(); } catch (ex) { setError(ex.message); } }
  async function patchItem(id, values) { try { await apiFetch(`/admin/${section}/${id}`, token, { method: 'PATCH', body: JSON.stringify(values) }); await load(); } catch (ex) { setError(ex.message); } }
  if (section === 'announcements') return <section className="panel"><div className="panel-title"><div><h2>공지사항 관리</h2><p className="panel-note">앱에 계속 노출할 소식을 작성하고 관리합니다.</p></div></div>{error && <div className="alert error">{error}</div>}<form className="form" onSubmit={publish}><label>제목<input value={form.title} maxLength="120" onChange={e=>setForm({...form,title:e.target.value})} required/></label><label>내용<textarea rows="5" value={form.content} onChange={e=>setForm({...form,content:e.target.value})} required/></label><label className="checkbox"><input type="checkbox" checked={form.pinned} onChange={e=>setForm({...form,pinned:e.target.checked})}/> 상단 고정</label><label className="checkbox"><input type="checkbox" checked={form.send_push} onChange={e=>setForm({...form,send_push:e.target.checked})}/> 푸시 알림도 함께 발송</label><button className="primary">게시하기</button></form><div className="list">{data.items.map(item=><article className={`card ${item.status === 'hidden' ? 'muted' : ''}`} key={item.id}><h3>{item.pinned && '📌 '}{item.title} {item.status === 'hidden' && '(숨김)'}</h3><p>{item.content}</p><small>{new Date(item.created_at).toLocaleString('ko-KR')}</small><div className="actions"><button className="ghost" onClick={()=>patchItem(item.id,{pinned:!item.pinned})}>{item.pinned?'고정 해제':'상단 고정'}</button><button className="ghost" onClick={()=>patchItem(item.id,{status:item.status==='hidden'?'published':'hidden'})}>{item.status==='hidden'?'노출로 복원':'숨김'}</button></div></article>)}</div></section>;
  return <section className="panel"><div className="panel-title"><div><h2>리뷰 관리</h2><p className="panel-note">평균 별점 ⭐ {data.average_rating ?? 0} ({data.review_count ?? 0}개)</p></div><select value={sort} onChange={e=>setSort(e.target.value)}><option value="latest">최신순</option><option value="rating_asc">낮은 별점순</option></select></div>{error && <div className="alert error">{error}</div>}<div className="list">{data.items.map(item=><article className={`card ${item.status==='hidden'?'muted':''}`} key={item.id}><h3>{item.author_name} {'⭐'.repeat(item.rating)} {item.status==='hidden'&&'(숨김)'}</h3><p>{item.content || '내용 없이 별점만 남긴 리뷰예요.'}</p>{item.image_urls?.length>0&&<div className="review-images">{item.image_urls.map(url=><img src={url} key={url} alt="리뷰"/>)}</div>}<label>사장님 답글<textarea defaultValue={item.owner_reply ?? ''} id={`reply-${item.id}`}/></label><div className="actions"><button className="primary" onClick={()=>patchItem(item.id,{owner_reply:document.getElementById(`reply-${item.id}`).value})}>답글 저장</button><button className="ghost" onClick={()=>patchItem(item.id,{status:item.status==='hidden'?'visible':'hidden'})}>{item.status==='hidden'?'노출로 복원':'숨김 처리'}</button></div></article>)}</div></section>;
}

function Dashboard({ session, onLogout }) {
  const token = session.access_token;
  const [me, setMe] = useState(null);
  const [accountSettingsOpen, setAccountSettingsOpen] = useState(false);
  const [accountSettingsForm, setAccountSettingsForm] = useState({ display_name: '', password: '', password_confirm: '' });
  const [requests, setRequests] = useState([]);
  const [settlements, setSettlements] = useState(null);
  const [products, setProducts] = useState(null);
  const [voucherProducts, setVoucherProducts] = useState([]);
  const [voucherProductsMigrationRequired, setVoucherProductsMigrationRequired] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [notificationsMigrationRequired, setNotificationsMigrationRequired] = useState(false);
  const [paymentAlertDay, setPaymentAlertDay] = useState(todayInput());
  const [unreadPaymentCount, setUnreadPaymentCount] = useState(0);
  const paymentAudioContextRef = useRef(null);
  const merchantSectionRef = useRef('main');
  const transactionRefreshVersionRef = useRef(0);
  const [productForm, setProductForm] = useState({ name: '', price: '', category: '' });
  const [productImageFile, setProductImageFile] = useState(null);
  const [productImagePreview, setProductImagePreview] = useState('');
  const [cropRequest, setCropRequest] = useState(null);
  const [dailyMenu, setDailyMenu] = useState(null);
  const [dailyMenuForm, setDailyMenuForm] = useState({ service_date: todayInput(), title: '오늘 뷔페 메뉴', menu_text: '', image_url: '' });
  const [merchantCompanies, setMerchantCompanies] = useState(null);
  const [merchantSection, setMerchantSection] = useState('main');
  const [newCompanyForm, setNewCompanyForm] = useState({ name: '', contact_email: '', contact_phone: '' });
  const [transactions, setTransactions] = useState(null);
  const [employees, setEmployees] = useState(null);
  const [mealPolicy, setMealPolicy] = useState(null);
  const [mealPolicyForm, setMealPolicyForm] = useState({ enabled: false, lunch_start: '11:00', lunch_end: '14:00', dinner_start: '17:30', dinner_end: '20:30' });
  const [employeeTxModal, setEmployeeTxModal] = useState(null);
  const [employeeBulkOpen, setEmployeeBulkOpen] = useState(false);
  const [employeeManageModal, setEmployeeManageModal] = useState(null);
  const [employeeManageForm, setEmployeeManageForm] = useState({ department: '', display_name: '', employee_no: '', phone: '', charge_amount: '', target_balance: '' });
  const [merchantQr, setMerchantQr] = useState(null);
  const [platformMerchants, setPlatformMerchants] = useState(null);
  const [platformMerchantForm, setPlatformMerchantForm] = useState({ name: '', owner_phone: '', category: '', avg_price: '' });
  const [platformInvitePhone, setPlatformInvitePhone] = useState({});
  const [inviteModal, setInviteModal] = useState(null);
  const [txModal, setTxModal] = useState(null);
  const [contractModal, setContractModal] = useState(null);
  const [contractForm, setContractForm] = useState({ settlement_cycle: 'month_end', settlement_day: '25', unit_price: '', subsidy_enabled: false, company_subsidy_amount: '0', restaurant_subsidy_amount: '0' });
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

  function playPaymentChime() {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;
    const context = paymentAudioContextRef.current ?? new AudioContextClass();
    paymentAudioContextRef.current = context;
    const play = () => {
      const start = context.currentTime;
      const gain = context.createGain();
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.24, start + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.58);
      gain.connect(context.destination);
      [[880, 0], [1174.66, 0.16]].forEach(([frequency, delay]) => {
        const oscillator = context.createOscillator();
        oscillator.type = 'sine';
        oscillator.frequency.setValueAtTime(frequency, start + delay);
        oscillator.connect(gain);
        oscillator.start(start + delay);
        oscillator.stop(start + delay + 0.34);
      });
    };
    if (context.state === 'suspended') context.resume().then(play).catch(() => {});
    else play();
  }

  async function copyMerchantPayUrl() {
    if (!merchantPayUrl) return;
    try {
      await navigator.clipboard.writeText(merchantPayUrl);
      setMessage('결제 QR 링크를 복사했어요.');
    } catch {
      setError('자동 복사가 막혔어요. QR 링크를 직접 복사해 주세요.');
    }
  }

  function openAccountSettings() {
    setAccountSettingsForm({ display_name: me?.display_name ?? '', password: '', password_confirm: '' });
    setError('');
    setAccountSettingsOpen(true);
  }

  async function saveAccountSettings(event) {
    event.preventDefault();
    const displayName = accountSettingsForm.display_name.trim();
    const password = accountSettingsForm.password;
    if (!displayName) { setError('관리자 이름을 입력해 주세요.'); return; }
    if (password && password.length < 6) { setError('새 비밀번호는 6자 이상 입력해 주세요.'); return; }
    if (password !== accountSettingsForm.password_confirm) { setError('새 비밀번호 확인이 일치하지 않아요.'); return; }
    setBusy(true); setError(''); setMessage('');
    try {
      if (displayName !== me?.display_name) {
        const updated = await apiFetch('/me', token, {
          method: 'PATCH', body: JSON.stringify({ display_name: displayName }),
        });
        setMe((current) => ({ ...current, display_name: updated.display_name }));
      }
      if (password) {
        const { error: passwordError } = await supabase.auth.updateUser({ password });
        if (passwordError) throw passwordError;
      }
      setAccountSettingsOpen(false);
      setMessage(password ? '관리자 정보와 비밀번호를 변경했어요.' : '관리자 정보를 변경했어요.');
    } catch (settingsError) { setError(settingsError.message); }
    finally { setBusy(false); }
  }

  async function copyCompanyInviteCode() {
    if (!me?.invite_code) return;
    try {
      await navigator.clipboard.writeText(me.invite_code);
      setMessage('초대코드를 복사했어요.');
    } catch {
      setError('자동 복사가 막혔어요. 초대코드를 직접 복사해 주세요.');
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
    ['거래내역', transactions ? `${transactions.total_count ?? transactions.items.length}건` : '조회 중', FileSpreadsheet, 'orange'],
  ] : [
    ['가입 요청', `${requests.length}명`, Users, 'orange'],
    ['직원', employees ? `${employees.items.length}명` : '조회 중', WalletCards, 'brown'],
  ], [isPlatformAdmin, isMerchantAdmin, requests.length, products, merchantCompanies, transactions, platformMerchants, employees]);

  const recentPaymentAlerts = useMemo(() => (transactions?.items ?? [])
    .filter((item) => !['refund', 'cancel'].includes(item.kind) && item.created_at && new Date(item.created_at).toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' }) === paymentAlertDay)
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
    .slice(0, 10), [transactions, paymentAlertDay]);

  async function load() {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const meData = await apiFetch('/me', token);
      let productData = null;
      let dailyMenuData = null;
      let requestData = { items: [] };
      let employeeData = null;
      let mealPolicyData = null;
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
          [requestData, settlementData, employeeData, mealPolicyData] = await Promise.all([
            apiFetch('/admin/join-requests', token),
            apiFetch('/admin/settlements', token),
            apiFetch('/admin/employees', token),
            apiFetch('/admin/meal-policy', token),
          ]);
        }
        if (meData.role === 'merchant_admin') {
          let voucherData;
          let notificationData;
          [merchantCompanyData, transactionData, merchantQrData, voucherData, notificationData] = await Promise.all([
            apiFetch('/admin/merchant/companies', token),
            apiFetch('/admin/merchant/transactions', token),
            apiFetch('/admin/merchant/qr', token),
            apiFetch('/admin/voucher-products', token),
            apiFetch('/admin/notifications', token),
          ]);
          setVoucherProducts(voucherData.items ?? []);
          setVoucherProductsMigrationRequired(!!voucherData.migration_required);
          setNotifications(notificationData.items ?? []);
          setNotificationsMigrationRequired(!!notificationData.migration_required);
        }
      }
      setMe(meData);
      setRequests(requestData.items ?? []);
      setEmployees(employeeData);
      setMealPolicy(mealPolicyData);
      if (mealPolicyData) setMealPolicyForm({
        enabled: !!mealPolicyData.enabled,
        lunch_start: mealPolicyData.lunch_start ?? '11:00',
        lunch_end: mealPolicyData.lunch_end ?? '14:00',
        dinner_start: mealPolicyData.dinner_start ?? '17:30',
        dinner_end: mealPolicyData.dinner_end ?? '20:30',
      });
      setSettlements(settlementData);
      setMerchantCompanies(merchantCompanyData);
      setTransactions(transactionData);
      setMerchantQr(merchantQrData);
      setPlatformMerchants(platformMerchantData);
      setProducts(productData);
      setDailyMenu(dailyMenuData);
      setDailyMenuForm({
        service_date: dailyMenuData?.service_date ?? todayInput(),
        title: dailyMenuData?.today_menu?.title ?? '오늘 뷔페 메뉴',
        menu_text: dailyMenuData?.today_menu?.menu_text ?? '',
        image_url: dailyMenuData?.today_menu?.image_url ?? '',
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

  async function openEmployeeTransactions(employee) {
    setBusy(true);
    setError('');
    try {
      const [usageData, pointData] = await Promise.all([
        apiFetch(`/admin/employees/${employee.id}/transactions`, token),
        apiFetch(`/admin/employees/${employee.id}/points`, token),
      ]);
      setEmployeeTxModal({ employee, items: usageData.items ?? [], pointItems: pointData.items ?? [] });
    } catch (txError) {
      setError(txError.message);
    } finally {
      setBusy(false);
    }
  }

  function openEmployeeManage(employee) {
    setEmployeeManageModal(employee);
    setEmployeeManageForm({ department: employee.department ?? '', display_name: employee.display_name ?? '', employee_no: employee.employee_no ?? '', phone: employee.phone ?? '', charge_amount: '', target_balance: '' });
  }

  async function saveEmployeeManage(event) {
    event.preventDefault();
    if (!employeeManageModal) return;
    const chargeAmount = employeeManageForm.charge_amount === '' ? null : Number(employeeManageForm.charge_amount);
    const targetBalance = employeeManageForm.target_balance === '' ? null : Number(employeeManageForm.target_balance);
    if (chargeAmount !== null && (!Number.isInteger(chargeAmount) || chargeAmount <= 0)) { setError('충전 금액을 올바르게 입력해 주세요.'); return; }
    if (targetBalance !== null && (!Number.isInteger(targetBalance) || targetBalance < 0)) { setError('목표 잔액을 올바르게 입력해 주세요.'); return; }
    setBusy(true); setError(''); setMessage('');
    try {
      await apiFetch(`/admin/employees/${employeeManageModal.id}`, token, { method: 'PATCH', body: JSON.stringify({ department: employeeManageForm.department.trim() || null, display_name: employeeManageForm.display_name.trim(), employee_no: employeeManageForm.employee_no.trim() || null, phone: employeeManageForm.phone.trim() || null }) });
      if (chargeAmount !== null) await apiFetch(`/admin/employees/${employeeManageModal.id}/points/charge`, token, { method: 'POST', body: JSON.stringify({ amount: chargeAmount }) });
      if (targetBalance !== null) await apiFetch(`/admin/employees/${employeeManageModal.id}/points/adjust`, token, { method: 'POST', body: JSON.stringify({ target_balance: targetBalance }) });
      setEmployeeManageModal(null);
      setMessage('직원 정보를 저장하고 포인트 변경을 반영했어요.');
      await load();
    } catch (employeeError) { setError(employeeError.message); } finally { setBusy(false); }
  }

  async function saveMealPolicy(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await apiFetch('/admin/meal-policy', token, {
        method: 'PUT',
        body: JSON.stringify(mealPolicyForm),
      });
      setMessage(mealPolicyForm.enabled ? '식대 사용시간 제한을 저장했어요.' : '식대 사용시간 제한을 해제했어요.');
      await load();
    } catch (policyError) {
      setError(policyError.message);
    } finally {
      setBusy(false);
    }
  }

  function requestImageCrop(file) {
    try { validateCropSource(file); }
    catch (validationError) { setError(validationError.message); return Promise.resolve(null); }
    setError('');
    return new Promise((resolve) => {
      setCropRequest({
        sourceUrl: URL.createObjectURL(file), filename: file.name, resolve,
        onError: (message) => setError(message),
      });
    });
  }

  function finishImageCrop(file) {
    if (!cropRequest) return;
    URL.revokeObjectURL(cropRequest.sourceUrl);
    cropRequest.resolve(file);
    setCropRequest(null);
  }

  function setPendingProductImage(file) {
    if (productImagePreview) URL.revokeObjectURL(productImagePreview);
    setProductImageFile(file);
    setProductImagePreview(file ? URL.createObjectURL(file) : '');
  }

  async function uploadImage(file) {
    const dataBase64 = await fileToBase64(file);
    const data = await apiFetch('/admin/images', token, {
      method: 'POST',
      body: JSON.stringify({ filename: file.name, content_type: file.type, data_base64: dataBase64 }),
    });
    return data.image_url;
  }

  async function uploadProductImage(file) {
    const dataBase64 = await fileToBase64(file);
    return (await apiFetch('/admin/product-images', token, {
      method: 'POST',
      body: JSON.stringify({ filename: file.name, content_type: file.type, data_base64: dataBase64 }),
    })).image_url;
  }

  async function deleteProductImage(imageUrl) {
    if (!imageUrl) return;
    try {
      await apiFetch('/admin/product-images', token, {
        method: 'DELETE', body: JSON.stringify({ image_url: imageUrl }),
      });
    } catch { /* best-effort cleanup after a failed product save */ }
  }

  async function selectNewProductImage(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    const cropped = await requestImageCrop(file);
    if (cropped) setPendingProductImage(cropped);
  }

  async function selectDailyMenuImage(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true); setError('');
    try {
      const imageUrl = await uploadImage(file);
      setDailyMenuForm((form) => ({ ...form, image_url: imageUrl }));
    } catch (uploadError) { setError(uploadError.message); }
    finally { setBusy(false); event.target.value = ''; }
  }

  async function updateProductImage(product, event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    const cropped = await requestImageCrop(file);
    if (!cropped) return;
    let imageUrl = '';
    setBusy(true); setError('');
    try {
      imageUrl = await uploadProductImage(cropped);
      await apiFetch(`/admin/products/${product.id}`, token, { method: 'PATCH', body: JSON.stringify({ image_url: imageUrl }) });
      setMessage(`${product.name} 이미지를 800×800 WebP로 교체했어요.`);
      await load();
    } catch (uploadError) {
      if (imageUrl) await deleteProductImage(imageUrl);
      setError(uploadError.message);
    } finally { setBusy(false); }
  }

  async function createProduct(event) {
    event.preventDefault();
    let uploadedImageUrl = '';
    setBusy(true);
    setError('');
    setMessage('');
    try {
      if (productImageFile) uploadedImageUrl = await uploadProductImage(productImageFile);
      await apiFetch('/admin/products', token, {
        method: 'POST',
        body: JSON.stringify({
          name: productForm.name.trim(),
          price: Number(productForm.price),
          category: productForm.category.trim() || null,
          image_url: uploadedImageUrl || null,
          sort_order: (products?.items?.length ?? 0) + 1,
        }),
      });
      setProductForm({ name: '', price: '', category: '' });
      setPendingProductImage(null);
      setMessage('상품을 등록했어요. 직원 앱 상품 선택 화면에 바로 반영됩니다.');
      await load();
    } catch (productError) {
      if (uploadedImageUrl) await deleteProductImage(uploadedImageUrl);
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
      const saved = await apiFetch('/admin/daily-menu', token, {
        method: 'PUT',
        body: JSON.stringify({
          service_date: dailyMenuForm.service_date,
          title: dailyMenuForm.title.trim() || '오늘 뷔페 메뉴',
          menu_text: dailyMenuForm.menu_text.trim(),
          image_url: dailyMenuForm.image_url || null,
          is_active: true,
        }),
      });
      const refreshed = await apiFetch('/admin/daily-menu', token);
      setDailyMenu(refreshed);
      setDailyMenuForm({
        service_date: saved.service_date,
        title: saved.title,
        menu_text: saved.menu_text,
        image_url: saved.image_url ?? '',
      });
      setMessage(`${saved.service_date} 뷔페 메뉴를 저장했어요.`);
    } catch (menuError) {
      setError(menuError.message);
    } finally {
      setBusy(false);
    }
  }

  function selectDailyMenuDate(serviceDate) {
    const saved = (dailyMenu?.menus ?? []).find((item) => item.service_date === serviceDate);
    setDailyMenuForm({
      service_date: serviceDate,
      title: saved?.title ?? '오늘 뷔페 메뉴',
      menu_text: saved?.menu_text ?? '',
      image_url: saved?.image_url ?? '',
    });
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
          contact_email: newCompanyForm.contact_email.trim(),
          contact_phone: newCompanyForm.contact_phone.trim() || null,
        }),
      });
      setNewCompanyForm({ name: '', contact_email: '', contact_phone: '' });
      setMessage(data.invite.email_send_status === 'sent' ? '장부업체를 만들고 초대 이메일을 보냈어요.' : `장부업체는 만들었지만 이메일 전송에 실패했어요: ${data.invite.email_error || '전송 설정을 확인해 주세요.'}`);
      await load();
    } catch (createError) {
      setError(createError.message);
    } finally {
      setBusy(false);
    }
  }

  async function resendCompanyInvite(companyId) {
    setBusy(true); setError(''); setMessage('');
    try {
      const data = await apiFetch(`/admin/merchant/companies/${companyId}/invite/resend`, token, { method: 'POST' });
      setMessage(data.invite.email_send_status === 'sent' ? '초대 이메일을 다시 보냈어요.' : `재전송에 실패했어요: ${data.invite.email_error || '-'}`);
      await load();
    } catch (resendError) { setError(resendError.message); } finally { setBusy(false); }
  }

  function openContractModal(item) {
    setContractModal(item);
    setContractForm({
      settlement_cycle: item.settlement_cycle ?? item.contract?.settlement_cycle ?? 'month_end',
      settlement_day: String(item.settlement_day ?? item.contract?.settlement_day ?? 25),
      unit_price: item.unit_price == null ? '' : String(item.unit_price),
      subsidy_enabled: !!(item.subsidy_enabled ?? item.contract?.subsidy_enabled),
      company_subsidy_amount: String(item.company_subsidy_amount ?? item.contract?.company_subsidy_amount ?? 0),
      restaurant_subsidy_amount: String(item.restaurant_subsidy_amount ?? item.contract?.restaurant_subsidy_amount ?? 0),
    });
  }

  async function saveContract(event) {
    event.preventDefault();
    if (!contractModal) return;
    const unitPrice = Number(contractForm.unit_price);
    const companySubsidy = Number(contractForm.company_subsidy_amount);
    const restaurantSubsidy = Number(contractForm.restaurant_subsidy_amount);
    if (contractForm.subsidy_enabled && (!contractForm.unit_price || unitPrice <= 0)) { setError('보조금 계약은 0원보다 큰 단가가 필요해요.'); return; }
    if (contractForm.subsidy_enabled && (companySubsidy < 0 || restaurantSubsidy < 0 || companySubsidy + restaurantSubsidy > unitPrice)) { setError('회사 부담액과 식당 부담액의 합계는 단가를 초과할 수 없어요.'); return; }
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
          subsidy_enabled: contractForm.subsidy_enabled,
          company_subsidy_amount: contractForm.subsidy_enabled ? companySubsidy : 0,
          restaurant_subsidy_amount: contractForm.subsidy_enabled ? restaurantSubsidy : 0,
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

  useEffect(() => {
    const now = new Date();
    const kstNow = new Date(now.getTime() + (9 * 60 * 60 * 1000));
    const nextKstMidnight = Date.UTC(kstNow.getUTCFullYear(), kstNow.getUTCMonth(), kstNow.getUTCDate() + 1) - (9 * 60 * 60 * 1000);
    const timer = window.setTimeout(() => setPaymentAlertDay(todayInput()), Math.max(1000, nextKstMidnight - now.getTime() + 100));
    return () => window.clearTimeout(timer);
  }, [paymentAlertDay]);

  useEffect(() => {
    merchantSectionRef.current = merchantSection;
    if (merchantSection === 'main') setUnreadPaymentCount(0);
  }, [merchantSection]);

  useEffect(() => {
    if (!isMerchantAdmin) return undefined;
    const unlockPaymentSound = () => {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) return;
      const context = paymentAudioContextRef.current ?? new AudioContextClass();
      paymentAudioContextRef.current = context;
      if (context.state === 'suspended') context.resume().catch(() => {});
    };
    unlockPaymentSound();
    window.addEventListener('pointerdown', unlockPaymentSound, { once: true, capture: true });
    window.addEventListener('keydown', unlockPaymentSound, { once: true, capture: true });
    return () => {
      window.removeEventListener('pointerdown', unlockPaymentSound, { capture: true });
      window.removeEventListener('keydown', unlockPaymentSound, { capture: true });
    };
  }, [isMerchantAdmin]);

  useEffect(() => {
    const merchantId = merchantQr?.merchant?.id;
    if (!supabase || !isMerchantAdmin || !merchantId) return undefined;
    const channel = supabase.channel(`merchant-payments-${merchantId}`)
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'meal_transactions', filter: `merchant_id=eq.${merchantId}` }, async (event) => {
        if (!['refund', 'cancel'].includes(event.new.kind)) {
          playPaymentChime();
          if (merchantSectionRef.current !== 'main') setUnreadPaymentCount((count) => count + 1);
        }
        const refreshVersion = ++transactionRefreshVersionRef.current;
        try {
          const list = await apiFetch('/admin/merchant/transactions', token);
          if (refreshVersion === transactionRefreshVersionRef.current) setTransactions(list);
        } catch (noticeError) { setError(`결제 알림 확인 실패: ${noticeError.message}`); }
      }).subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [isMerchantAdmin, merchantQr?.merchant?.id, token]);

  if (dashboardBooting) return <main className="loading"><BrandMark /><div className="spinner"/><p className="loading-copy">운영자 권한을 확인하고 있어요...</p></main>;

  if (!me) return <main className="loading"><BrandMark /><div className="alert error">권한 정보를 불러오지 못했어요. {error}</div><button className="ghost" onClick={onLogout}>로그아웃</button></main>;

  const merchantNavItems = [
    ['main', '메인', Home],
    ['companies', '업체 관리', Building2],
    ['vouchers', '판매 상품(일반)', Package],
    ['products', '식당 상품(장부)', Utensils],
    ['notifications', '알림', Bell],
    ['announcements', '공지사항', FileText],
    ['reviews', '리뷰', CheckCircle2],
    ['daily-menu', '오늘 뷔페 메뉴', Coffee],
  ];

  return <main className={`shell${isMerchantAdmin ? ' merchant-shell' : ''}`}>
    <ImageCropModal request={cropRequest} onCancel={() => finishImageCrop(null)} onApply={finishImageCrop} />
    <header className={`topbar${isMerchantAdmin ? ' merchant-topbar' : ''}`}>
      <div className="top-copy">
        <div className="brand-row">
          <BrandMark />
          <span className="pill">OPERATIONS</span>
        </div>
        <p>가입 승인, 직원 상태, 식당 결제와 정산 현황을 그린잇 스타일의 카드 대시보드로 확인합니다.</p>
      </div>
      <div className="top-actions">
        <button className="ghost" onClick={load} disabled={busy}><RefreshCw size={16}/> 새로고침</button>
        <button className="ghost" onClick={onLogout}><LogOut size={16}/> 로그아웃</button>
      </div>
    </header>

    {isMerchantAdmin && <nav className="merchant-tabs" aria-label="식당 관리자 메뉴">
      {merchantNavItems.map(([id, label, Icon]) => <button key={id} type="button" className={merchantSection === id ? 'active' : ''} onClick={() => setMerchantSection(id)} aria-current={merchantSection === id ? 'page' : undefined}><Icon size={20}/><span>{label}</span>{id === 'main' && unreadPaymentCount > 0 && <span className="merchant-nav-badge" aria-label={`새 결제 ${unreadPaymentCount}건`}>{unreadPaymentCount > 99 ? '99+' : unreadPaymentCount}</span>}</button>)}
    </nav>}

    {isMerchantAdmin && <div className="merchant-account-corner">
      <span>{session.user.email}</span>
      <button type="button" className="account-settings-button" onClick={openAccountSettings} aria-label="관리자 정보 설정" title="관리자 정보 설정"><Settings size={20}/></button>
    </div>}

    <div className={isMerchantAdmin ? 'merchant-content' : undefined}>
    {isMerchantAdmin && ['announcements', 'reviews'].includes(merchantSection) && <AnnouncementReviewPanel token={token} section={merchantSection}/>}

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

    {employeeBulkOpen && <EmployeeBulkModal token={token} onClose={() => setEmployeeBulkOpen(false)} onConfirmed={async (count) => { setEmployeeBulkOpen(false); setMessage(`직원 ${count}명의 초대를 등록했어요.`); await load(); }} />}

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
          <label className="subsidy-toggle"><input type="checkbox" checked={contractForm.subsidy_enabled} onChange={(event) => setContractForm((form) => ({ ...form, subsidy_enabled: event.target.checked }))} /> 보조금 계약</label>
          {contractForm.subsidy_enabled && <div className="subsidy-fields">
            <label>회사 부담액<input type="number" min="0" step="1" value={contractForm.company_subsidy_amount} onChange={(event) => setContractForm((form) => ({ ...form, company_subsidy_amount: event.target.value }))} required /></label>
            <label>식당 부담액<input type="number" min="0" step="1" value={contractForm.restaurant_subsidy_amount} onChange={(event) => setContractForm((form) => ({ ...form, restaurant_subsidy_amount: event.target.value }))} required /></label>
            <div className={`employee-pay-preview ${Number(contractForm.company_subsidy_amount || 0) + Number(contractForm.restaurant_subsidy_amount || 0) > Number(contractForm.unit_price || 0) ? 'invalid' : ''}`}><span>직원 실부담액</span><strong>{krw(Math.max(0, Number(contractForm.unit_price || 0) - Number(contractForm.company_subsidy_amount || 0) - Number(contractForm.restaurant_subsidy_amount || 0)))}</strong></div>
            {Number(contractForm.company_subsidy_amount || 0) + Number(contractForm.restaurant_subsidy_amount || 0) > Number(contractForm.unit_price || 0) && <div className="alert error subsidy-validation">회사 부담액과 식당 부담액의 합계는 단가를 초과할 수 없어요.</div>}
          </div>}
          <div className="row-actions invite-modal-actions">
            <button className="primary" disabled={busy || (contractForm.subsidy_enabled && Number(contractForm.company_subsidy_amount || 0) + Number(contractForm.restaurant_subsidy_amount || 0) > Number(contractForm.unit_price || 0))}>저장</button>
            <button className="ghost" type="button" onClick={() => setContractModal(null)}>닫기</button>
          </div>
        </form>
      </section>
    </div>}

    {employeeManageModal && <div className="modal-backdrop" onClick={() => setEmployeeManageModal(null)}>
      <section className="invite-modal contract-modal" onClick={(event) => event.stopPropagation()}>
        <div className="panel-title"><div><h2>직원 관리</h2><p className="panel-note">직원 정보와 포인트를 한 번에 변경합니다.</p></div><button className="ghost icon-button" onClick={() => setEmployeeManageModal(null)} aria-label="닫기"><X size={20}/></button></div>
        <form className="contract-form" onSubmit={saveEmployeeManage}>
          <label>부서<input value={employeeManageForm.department} maxLength="120" onChange={(event) => setEmployeeManageForm((form) => ({ ...form, department: event.target.value }))} /></label>
          <label>이름<input value={employeeManageForm.display_name} maxLength="80" required onChange={(event) => setEmployeeManageForm((form) => ({ ...form, display_name: event.target.value }))} /></label>
          <label>사번<input value={employeeManageForm.employee_no} maxLength="40" onChange={(event) => setEmployeeManageForm((form) => ({ ...form, employee_no: event.target.value }))} /></label>
          <label>전화번호<input value={employeeManageForm.phone} maxLength="40" onChange={(event) => setEmployeeManageForm((form) => ({ ...form, phone: event.target.value }))} /></label>
          <label>즉시 포인트 충전<input type="number" min="1" step="1" value={employeeManageForm.charge_amount} placeholder="충전하지 않으면 비워두세요" onChange={(event) => setEmployeeManageForm((form) => ({ ...form, charge_amount: event.target.value }))} /></label>
          <label>조정 후 목표 잔액<input type="number" min="0" step="1" value={employeeManageForm.target_balance} placeholder={`현재 ${Number(employeeManageModal.point_balance ?? 0).toLocaleString()} P · 조정하지 않으면 비워두세요`} onChange={(event) => setEmployeeManageForm((form) => ({ ...form, target_balance: event.target.value }))} /></label>
          <div className="row-actions invite-modal-actions"><button className="primary" disabled={busy}>저장</button><button className="ghost" type="button" onClick={() => setEmployeeManageModal(null)}>닫기</button></div>
        </form>
      </section>
    </div>}

    {employeeTxModal && <div className="modal-backdrop" onClick={() => setEmployeeTxModal(null)}>
      <section className="invite-modal employee-history-modal" onClick={(event) => event.stopPropagation()}>
        <div className="panel-title"><div><h2>직원 이용내역</h2><p className="panel-note">{employeeTxModal.employee.display_name ?? '직원'}님의 최근 이용내역입니다.</p></div><button className="ghost icon-button" onClick={() => setEmployeeTxModal(null)} aria-label="닫기"><X size={20}/></button></div>
        <h3>식대 이용내역</h3>
        {(employeeTxModal.items?.length ?? 0) === 0 ? <p className="empty-state">아직 이용내역이 없어요.</p> : <div className="table-wrap"><table><thead><tr><th>일시</th><th>식당</th><th>내역</th><th>구분</th><th>금액</th></tr></thead><tbody>{employeeTxModal.items.map((item) => <tr key={item.id}><td>{item.created_at ? new Date(item.created_at).toLocaleString('ko-KR') : '-'}</td><td>{item.merchant_name ?? '-'}</td><td>{item.product_name ?? item.tx_code ?? '-'}</td><td>{item.kind}</td><td>{krw(Math.abs(Number(item.amount ?? 0)))}</td></tr>)}</tbody></table></div>}
        <h3>포인트 내역</h3>
        {(employeeTxModal.pointItems?.length ?? 0) === 0 ? <p className="empty-state">아직 포인트 내역이 없어요.</p> : <div className="table-wrap"><table><thead><tr><th>일시</th><th>구분</th><th>금액</th><th>변경 후 잔액</th></tr></thead><tbody>{employeeTxModal.pointItems.map((item) => <tr key={item.id}><td>{item.created_at ? new Date(item.created_at).toLocaleString('ko-KR') : '-'}</td><td>{item.type === 'charge' ? '충전' : item.type === 'use' ? '사용' : '조정'}</td><td>{`${Number(item.amount ?? 0) > 0 ? '+' : ''}${Number(item.amount ?? 0).toLocaleString()} P`}</td><td>{`${Number(item.balance_after ?? 0).toLocaleString()} P`}</td></tr>)}</tbody></table></div>}
      </section>
    </div>}

    {(!isMerchantAdmin || merchantSection === 'main') && <section className={`grid${isMerchantAdmin ? ' merchant-kpi-grid' : ''}`}>
      {cards.map(([label, value, Icon, tone]) => <article className={`card ${tone}${isMerchantAdmin ? ' merchant-kpi-card' : ''}`} key={label}>
        <Icon size={28}/><span>{label}</span><strong>{value}</strong>
      </article>)}
    </section>}

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

    {isMerchantAdmin && merchantSection === 'main' && <section className="two-col merchant-main-panels">
      <article className="panel payment-alert-panel">
        <div className="panel-title payment-alert-heading"><div><h2><Bell size={21}/> 오늘의 결제 알림</h2><p className="panel-note">오늘 승인된 최근 결제 10건을 실시간으로 표시합니다.</p></div><span className="badge">{recentPaymentAlerts.length}건</span></div>
        {recentPaymentAlerts.length === 0 ? <p className="empty-state">오늘 들어온 결제가 아직 없어요.</p> : <div className="payment-alert-list">
          {recentPaymentAlerts.map((item) => {
            const paymentType = item.pay_type === 'voucher' ? '식권' : item.pay_type === 'subsidized' ? '보조금' : '장부';
            return <div className="payment-alert-row" key={item.id}>
              <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false })}</time>
              <strong>{item.employee_name ?? '직원'}</strong>
              <span className={`payment-type-badge ${item.pay_type ?? 'ledger'}`}>{paymentType}</span>
              <b>{krw(Math.abs(Number(item.amount ?? 0)))}</b>
            </div>;
          })}
        </div>}
      </article>
      <article className="panel merchant-qr-panel">
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
      </article>
    </section>}

    {!isMerchantAdmin && <section className="two-col">
      <article className="panel profile-panel">
        <div className="panel-title"><h2>로그인 정보</h2><span className="badge">secure</span></div>
        <div className="profile-grid">
          <span>이메일</span><strong>{session.user.email}</strong>
          <span>{['company_admin', 'merchant_admin'].includes(me?.role) ? '관리자 이름' : '이름'}</span>
          {me?.role === 'company_admin'
            ? <div className="profile-name-value"><strong>{me?.display_name ?? '-'}</strong><button type="button" className="account-settings-button" onClick={openAccountSettings} aria-label="관리자 정보 설정" title="관리자 정보 설정"><Settings size={20}/></button></div>
            : <strong>{me?.display_name ?? '-'}</strong>}
          {me?.role !== 'company_admin' && <><span>권한</span><strong>{me?.role === 'merchant_admin' ? '관리자' : me?.role ?? '-'}</strong><span>상태</span><strong>{me?.status ?? '-'}</strong></>}
        </div>
      </article>
      <article className="panel menu-panel restaurant-card">
        <div className="restaurant-card-head"><Coffee size={24}/><strong>돈토 식당</strong></div>
        <div className="invite-code-box">
          <span>초대코드</span>
          <strong>{me?.invite_code ?? '-'}</strong>
          <button className="ghost" onClick={copyCompanyInviteCode} disabled={!me?.invite_code}>복사</button>
        </div>
      </article>
    </section>}

    {!isPlatformAdmin && !isMerchantAdmin && <section className="panel meal-policy-panel">
      <div className="panel-title">
        <div><h2>식대 사용시간 설정</h2><p className="panel-note">기본은 사용제한없음입니다. 제한을 켜면 중식/석식 시간에만 결제됩니다.</p></div>
        <span className="badge">{mealPolicyForm.enabled ? '제한 사용' : '제한없음'}</span>
      </div>
      <form className="meal-policy-form" onSubmit={saveMealPolicy}>
        <label className="policy-toggle"><input type="checkbox" checked={mealPolicyForm.enabled} onChange={(event) => setMealPolicyForm((form) => ({ ...form, enabled: event.target.checked }))} /> 사용시간 제한 켜기</label>
        <div className="time-window-grid">
          <label>중식 시작<input type="time" value={mealPolicyForm.lunch_start} disabled={!mealPolicyForm.enabled} onChange={(event) => setMealPolicyForm((form) => ({ ...form, lunch_start: event.target.value }))} /></label>
          <label>중식 종료<input type="time" value={mealPolicyForm.lunch_end} disabled={!mealPolicyForm.enabled} onChange={(event) => setMealPolicyForm((form) => ({ ...form, lunch_end: event.target.value }))} /></label>
          <label>석식 시작<input type="time" value={mealPolicyForm.dinner_start} disabled={!mealPolicyForm.enabled} onChange={(event) => setMealPolicyForm((form) => ({ ...form, dinner_start: event.target.value }))} /></label>
          <label>석식 종료<input type="time" value={mealPolicyForm.dinner_end} disabled={!mealPolicyForm.enabled} onChange={(event) => setMealPolicyForm((form) => ({ ...form, dinner_end: event.target.value }))} /></label>
        </div>
        <button className="primary" disabled={busy}>식대 사용시간 저장</button>
      </form>
    </section>}

    {!isPlatformAdmin && !isMerchantAdmin && <section className="panel employee-panel">
      <div className="panel-title">
        <div><h2>등록된 직원목록</h2><p className="panel-note">직원 정보, 포인트 잔액과 이번 달 이용 현황을 확인합니다.</p></div>
        <div className="employee-panel-actions"><button className="primary bulk-open-button" onClick={() => setEmployeeBulkOpen(true)} disabled={employees?.bulk_migration_required}>+ 직원 일괄등록</button><span className="badge">{employees?.items?.length ?? 0}명</span></div>
      </div>
      {employees?.bulk_migration_required && <div className="alert error">0017_employee_bulk_invites.sql 적용 후 직원 일괄등록을 사용할 수 있어요.</div>}
      {(employees?.items?.length ?? 0) === 0 ? <p className="empty-state">등록된 직원이 없어요. 일괄등록하거나 직원이 초대코드로 가입하면 여기에 표시됩니다.</p> : <div className="table-wrap"><table><thead><tr><th>상태</th><th>부서</th><th>이름</th><th>사번</th><th>전화번호</th><th>포인트 잔액</th><th>이번 달 이용액</th><th>최근 이용일</th><th>이용내역</th><th>관리</th></tr></thead><tbody>{employees.items.map((employee) => <tr key={employee.id}><td><span className="badge">{employee.is_staged ? '초대대기' : employee.status === 'active' ? '사용중' : employee.status}</span></td><td>{employee.department || '-'}</td><td><strong>{employee.display_name || '이름 없음'}</strong></td><td>{employee.employee_no || '-'}</td><td>{employee.phone || '-'}</td><td>{employee.is_staged ? '-' : `${Number(employee.point_balance ?? 0).toLocaleString()} P`}</td><td>{employee.is_staged ? '-' : krw(employee.month_used ?? 0)}</td><td>{employee.recent_used_at ? new Date(employee.recent_used_at).toLocaleDateString('ko-KR') : '-'}</td><td>{employee.is_staged ? '-' : <button className="ghost" onClick={() => openEmployeeTransactions(employee)}>이용내역</button>}</td><td>{employee.is_staged ? <span className="muted">최초 가입 대기</span> : <button className="ghost icon-button" disabled={busy} onClick={() => openEmployeeManage(employee)} aria-label={`${employee.display_name ?? '직원'} 관리`} title="직원 관리"><Settings size={18}/></button>}</td></tr>)}</tbody></table></div>}
    </section>}

    {!isPlatformAdmin && isMerchantAdmin && merchantSection === 'companies' && <section className="panel">
      <div className="panel-title">
        <div><h2>업체 관리</h2><p className="panel-note">현재 연결된 회사를 관리하거나, 새 회사 담당자를 초대합니다.</p></div>
        <span className="badge">{merchantCompanies?.items?.length ?? 0}곳</span>
      </div>
      <form className="product-form" onSubmit={createAndLinkCompany}>
        <input value={newCompanyForm.name} onChange={(event) => setNewCompanyForm((form) => ({ ...form, name: event.target.value }))} placeholder="신규 회사명" required />
        <input type="email" value={newCompanyForm.contact_email} onChange={(event) => setNewCompanyForm((form) => ({ ...form, contact_email: event.target.value }))} placeholder="담당자 이메일 (필수)" required />
        <input value={newCompanyForm.contact_phone} onChange={(event) => setNewCompanyForm((form) => ({ ...form, contact_phone: event.target.value }))} placeholder="담당자 연락처 (선택)" />
        <button className="primary" disabled={busy}>신규 생성 + 이메일 초대</button>
      </form>
      {(merchantCompanies?.items?.length ?? 0) === 0
        ? <p className="empty-state">아직 연결된 장부업체가 없어요.</p>
        : <div className="table-wrap"><table><thead><tr><th>회사명</th><th>담당자 이메일</th><th>회사상태</th><th>연결상태</th><th>거래내역</th><th>계약</th><th>초대 상태</th><th>이메일 전송</th></tr></thead><tbody>{merchantCompanies.items.map((item) => {
          const link = inviteLink(item.invite);
          const companyName = item.company?.name ?? item.company_id;
          const txItems = (transactions?.items ?? []).filter((tx) => tx.company_id === item.company_id);
          const totalAmount = txItems.reduce((sum, tx) => sum + Math.abs(Number(tx.amount ?? 0)), 0);
          return <tr key={item.id}><td>{companyName}</td><td>{item.company?.contact_email ?? item.invite?.email ?? '-'}</td><td>{item.company?.status ?? '-'}</td><td>{item.status}</td><td><button className="ghost" onClick={() => setTxModal({ companyId: item.company_id, companyName, txItems, totalAmount, contract: item.contract })}>{txItems.length}건 보기</button></td><td><button className="ghost" onClick={() => openContractModal(item)}>상세보기</button></td><td><span className="badge">{item.invite?.status === 'pending' ? '대기중' : item.invite?.status === 'accepted' || item.invite?.status === 'claimed' ? '수락완료' : item.invite?.status || '-'}</span>{link && item.invite?.status === 'pending' && <button className="ghost" onClick={() => setInviteModal({ link, companyName })}>링크</button>}</td><td>{item.invite?.email_send_status === 'sent' ? '전송완료' : item.invite?.email_send_status === 'failed' ? '전송실패' : '-'} {item.invite?.status === 'pending' && <button className="ghost" disabled={busy} onClick={() => resendCompanyInvite(item.company_id)}>재전송</button>}</td></tr>;
        })}</tbody></table></div>}
    </section>}


    {isMerchantAdmin && merchantSection === 'vouchers' && <VoucherProductsPanel items={voucherProducts} migrationRequired={voucherProductsMigrationRequired} token={token} busy={busy} cropImage={requestImageCrop} uploadImage={uploadProductImage} deleteImage={deleteProductImage} onChanged={load} setBusy={setBusy} setError={setError} setMessage={setMessage} />}

    {isMerchantAdmin && merchantSection === 'notifications' && <NotificationPanel token={token} history={notifications} migrationRequired={notificationsMigrationRequired} onSent={load} setMessage={setMessage} />}

    {isMerchantAdmin && merchantSection === 'daily-menu' && <section className="panel daily-menu-panel">
      <div className="panel-title">
        <div><h2>오늘 뷔페 메뉴</h2><p className="panel-note">날짜를 선택해 오늘과 이후의 뷔페 메뉴를 미리 저장할 수 있어요.</p></div>
        <span className="badge">{dailyMenuForm.service_date}</span>
      </div>
      {dailyMenu?.migration_required && <div className="alert error">오늘 메뉴 DB 마이그레이션이 아직 적용되지 않아 기본 메뉴만 표시 중이에요. 0006_merchant_daily_menus.sql 적용 후 저장이 활성화됩니다.</div>}
      <form className="daily-menu-form" onSubmit={saveDailyMenu}>
        <label>메뉴 날짜<input type="date" min={todayInput()} value={dailyMenuForm.service_date} onChange={(event) => selectDailyMenuDate(event.target.value)} required /></label>
        <input value={dailyMenuForm.title} onChange={(event) => setDailyMenuForm((form) => ({ ...form, title: event.target.value }))} placeholder="제목" required />
        <textarea value={dailyMenuForm.menu_text} onChange={(event) => setDailyMenuForm((form) => ({ ...form, menu_text: event.target.value }))} placeholder="예: 김치찌개, 제육볶음, 현미밥, 계절 샐러드, 반찬 4종" required rows={4} />
        <label className="image-picker">오늘 메뉴 이미지 (최대 5MB)<input type="file" accept="image/jpeg,image/png,image/webp,image/gif" onChange={selectDailyMenuImage} disabled={busy}/></label>
        {dailyMenuForm.image_url && <img className="menu-image-preview" src={dailyMenuForm.image_url} alt="오늘 메뉴 미리보기" />}
        <button className="primary" disabled={busy || dailyMenu?.migration_required}>선택 날짜 메뉴 저장</button>
      </form>
      <div className="daily-menu-schedule">
        <h3>저장된 메뉴 일정</h3>
        {(dailyMenu?.menus?.length ?? 0) === 0
          ? <p className="empty-state">오늘 이후에 저장된 메뉴가 없어요.</p>
          : <div className="product-list">{dailyMenu.menus.map((menu) => <article className="product-item" key={menu.id}>
              {menu.image_url ? <img className="product-image-preview" src={menu.image_url} alt="" /> : <div className="product-image-placeholder">이미지 없음</div>}
              <div className="product-copy"><strong>{menu.service_date} · {menu.title}</strong><span>{menu.menu_text}</span></div>
              <button type="button" className="ghost" onClick={() => selectDailyMenuDate(menu.service_date)}>수정</button>
            </article>)}</div>}
      </div>
    </section>}


    {isMerchantAdmin && merchantSection === 'products' && <section className="panel product-panel">
      <div className="panel-title">
        <div><h2>식당 상품 관리</h2><p className="panel-note">직원 앱은 금액 입력 없이 여기 등록된 상품 중 하나를 선택해 결제합니다.</p></div>
      </div>
      {products?.migration_required && <div className="alert error">상품 DB 마이그레이션이 아직 적용되지 않아 기본 상품만 표시 중이에요. 0005_merchant_products.sql 적용 후 등록/수정이 활성화됩니다.</div>}
      <form className="product-form product-register-form" onSubmit={createProduct}>
        <input value={productForm.name} onChange={(event) => setProductForm((form) => ({ ...form, name: event.target.value }))} placeholder="상품명" required />
        <input value={productForm.price} onChange={(event) => setProductForm((form) => ({ ...form, price: event.target.value }))} placeholder="가격" type="number" min="1" required />
        <input value={productForm.category} onChange={(event) => setProductForm((form) => ({ ...form, category: event.target.value }))} placeholder="카테고리" />
        <label className="image-picker compact">상품 이미지<input type="file" accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp" onChange={selectNewProductImage} disabled={busy}/></label>
        {productImagePreview && <img className="product-image-preview" src={productImagePreview} alt="새 상품 미리보기" />}
        <button className="primary" disabled={busy || products?.migration_required}>상품 등록</button>
      </form>
      {(products?.items?.length ?? 0) === 0
        ? <p className="empty-state">등록된 상품이 없어요. 첫 상품을 등록하면 직원 앱에 표시됩니다.</p>
        : <div className="product-list">{products.items.map((product) => <article className={product.is_active ? 'product-item' : 'product-item off'} key={product.id}>
          {product.image_url ? <img className="product-image-preview" src={product.image_url} alt={`${product.name} 이미지`} /> : <div className="product-image-placeholder">이미지 없음</div>}
          <div className="product-copy"><strong>{product.name}</strong><span>{product.category ?? '기본'} · {Number(product.price).toLocaleString('ko-KR')}원</span></div>
          <div className="row-actions"><label className="ghost image-change">이미지 변경<input type="file" accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp" onChange={(event) => updateProductImage(product, event)} disabled={busy || products?.migration_required}/></label><button className="ghost" onClick={() => toggleProduct(product)} disabled={busy || products?.migration_required}>{product.is_active ? '숨김' : '판매중'}</button></div>
        </article>)}</div>}
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
    {(isMerchantAdmin || me?.role === 'company_admin') && accountSettingsOpen && <div className="modal-backdrop account-settings-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setAccountSettingsOpen(false); }}>
      <section className="invite-modal account-settings-modal" role="dialog" aria-modal="true" aria-labelledby="account-settings-title">
        <div className="panel-title"><div><span className="eyebrow">ACCOUNT</span><h2 id="account-settings-title">관리자 정보 설정</h2><p className="panel-note">관리자 이름과 로그인 비밀번호를 변경할 수 있어요.</p></div><button type="button" className="icon-button" onClick={() => setAccountSettingsOpen(false)} disabled={busy} aria-label="닫기"><X size={20}/></button></div>
        {error && <div className="alert error">{error}</div>}
        <form className="account-settings-form" onSubmit={saveAccountSettings}>
          <label>로그인 이메일<input type="email" value={session.user.email ?? ''} disabled/></label>
          <label>관리자 이름<input value={accountSettingsForm.display_name} maxLength="80" onChange={(event) => setAccountSettingsForm((form) => ({ ...form, display_name: event.target.value }))} required autoFocus/></label>
          <label>새 비밀번호<input type="password" value={accountSettingsForm.password} minLength="6" autoComplete="new-password" placeholder="변경할 때만 입력 (6자 이상)" onChange={(event) => setAccountSettingsForm((form) => ({ ...form, password: event.target.value }))}/></label>
          <label>새 비밀번호 확인<input type="password" value={accountSettingsForm.password_confirm} minLength="6" autoComplete="new-password" placeholder="새 비밀번호를 다시 입력" onChange={(event) => setAccountSettingsForm((form) => ({ ...form, password_confirm: event.target.value }))}/></label>
          <div className="row-actions"><button type="button" className="ghost" onClick={() => setAccountSettingsOpen(false)} disabled={busy}>취소</button><button className="primary" disabled={busy}>{busy ? '저장 중...' : '변경사항 저장'}</button></div>
        </form>
      </section>
    </div>}
    </div>
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
