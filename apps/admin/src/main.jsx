import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AlertTriangle, BarChart3, Bell, Building2, CalendarDays, CheckCircle2, ChevronDown, Coffee, CreditCard, Download, FileSpreadsheet, FileText, Home, LogOut, Package, QrCode, RefreshCw, RotateCcw, Search, Send, Settings, Users, WalletCards, X, XCircle } from 'lucide-react';
import { createClient } from '@supabase/supabase-js';
import Cropper from 'react-easy-crop';
import './style.css';
import { PaymentHistoryDashboard, RefundModal } from './PaymentFeatures.jsx';
import { contractFormFromItem, subsidyContractInvalid } from './contractForm.js';
import { captureGeneration, generationIsCurrent } from './generationGuard.js';
import {
  PILOT_COMPANY_SCOPE_ID,
  canConfirmAndRequest,
  canMerchantIssue,
  canMerchantMarkPaid,
  isBusinessPartyComplete,
  loadSettlementMockRows,
  saveSettlementMockRows,
  transitionSettlementMockRow,
} from './settlementMock.js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL;

const supabase = supabaseUrl && supabaseAnonKey ? createClient(supabaseUrl, supabaseAnonKey) : null;

const paymentSuccessAudioUrl = '/audio/payment-success.mp3';
let paymentSuccessAudio = null;
let paymentAudioUnlocked = false;

function getPaymentSuccessAudio() {
  if (typeof Audio === 'undefined') return null;
  paymentSuccessAudio ??= new Audio(paymentSuccessAudioUrl);
  paymentSuccessAudio.preload = 'auto';
  return paymentSuccessAudio;
}

function unlockPaymentAudio() {
  if (paymentAudioUnlocked) return;
  const audio = getPaymentSuccessAudio();
  if (!audio) return;
  audio.volume = 0;
  const attempt = audio.play();
  if (!attempt) return;
  attempt.then(() => {
    audio.pause();
    audio.currentTime = 0;
    audio.volume = 1;
    paymentAudioUnlocked = true;
  }).catch(() => { audio.volume = 1; });
}

function merchantMealPaymentIds(list) {
  return (list?.items ?? [])
    .filter((item) => item.source !== 'payment' && !['refund', 'cancel'].includes(item.kind))
    .map((item) => String(item.id));
}

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
    const error = new Error(detail.message || detail.code || `API 오류 (${response.status})`);
    error.code = detail.code || payload.code;
    error.status = response.status;
    error.payload = payload;
    throw error;
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

function LegalLinks({ consent = false }) {
  return <div className="legal-links">
    {consent && <span>가입하면 아래 문서에 동의한 것으로 봅니다.</span>}
    <nav aria-label="법적 고지">
      <a href="/terms.html" target="_blank" rel="noreferrer">이용약관</a>
      <span aria-hidden="true">·</span>
      <a href="/privacy.html" target="_blank" rel="noreferrer">개인정보 처리방침</a>
    </nav>
  </div>;
}

function LoginScreen({ missingEnv, onLogin }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(event) {
    event.preventDefault();
    unlockPaymentAudio();
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
      <LegalLinks />
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
      <LegalLinks consent />
    </section>
  </main>;
}

const krw = (value) => `₩${Number(value ?? 0).toLocaleString('ko-KR')}`;
const TAX_TYPE_META = {
  taxable: { label: '과세', tone: 'taxable' },
  tax_free: { label: '면세', tone: 'tax-free' },
  unclassified: { label: '미분류 · 결제 차단', tone: 'unclassified' },
};
const taxTypeMeta = (value) => TAX_TYPE_META[value] ?? TAX_TYPE_META.unclassified;
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
      pay_type: tx.pay_type === 'subsidized' ? '보조금' : tx.pay_type === 'voucher' ? '식권' : tx.pay_type === 'direct' ? '키움페이결제' : '장부',
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
    pay_type: item.pay_type === 'subsidized' ? '보조금' : item.pay_type === 'voucher' ? '식권' : item.pay_type === 'direct' ? '키움페이결제' : (item.pay_type ?? '장부'),
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
  const blank = { name: '', voucher_count: '0', bonus_count: '0', unit_price: '', discount_rate: '0', status: 'active', display_order: '0', kiwoom_pay_method: 'TOTAL', image_url: '', is_event: false, event_start_at: '', event_end_at: '', tax_type: 'unclassified' };
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
        unit_price: Number(form.unit_price), discount_rate: discount, status: form.status, tax_type: form.tax_type,
        display_order: Number(form.display_order || 0), image_url: uploadedImageUrl || form.image_url || null,
        ...(!migrationRequired ? {
          kiwoom_pay_method: form.kiwoom_pay_method,
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
    <div className="panel-title"><div><p className="panel-note titleless-guidance">삭제하지 않고 숨김/판매 재개합니다. 이벤트 상품은 설정 기간에만 자동 노출됩니다.</p></div><span className="badge">{items.length}개</span></div>
    {migrationRequired && <div className="alert error">상품 DB 마이그레이션이 아직 적용되지 않았어요. 0020과 0030 마이그레이션 적용 후 이벤트·결제방식 설정이 활성화됩니다.</div>}
    <form className="voucher-form" onSubmit={save}>
      <input value={form.name} onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} placeholder="패키지명" required />
      <label>기본 장수<input type="number" min="1" max="1000" value={form.voucher_count} onChange={(e) => setForm((p) => ({ ...p, voucher_count: e.target.value }))} required /></label>
      <div className="quick-buttons">{[1, 5, 10].map((n) => <button type="button" className="ghost" key={n} onClick={() => setForm((p) => ({ ...p, voucher_count: String(Math.min(1000, Math.max(0, Number(p.voucher_count) || 0) + n)) }))}>+{n}장</button>)}</div>
      <label>보너스 장수<input type="number" min="0" max="1000" value={form.bonus_count} onChange={(e) => setForm((p) => ({ ...p, bonus_count: e.target.value }))} /></label>
      <label>장당 정가<input type="number" min="1" step="0.01" value={form.unit_price} onChange={(e) => setForm((p) => ({ ...p, unit_price: e.target.value }))} required /></label>
      <label>할인율(%)<input type="number" min="0" max="99.99" step="0.01" value={form.discount_rate} onChange={(e) => setForm((p) => ({ ...p, discount_rate: e.target.value }))} /></label>
      <label>상태<select value={form.status} onChange={(e) => setForm((p) => ({ ...p, status: e.target.value }))}><option value="active">판매중</option><option value="inactive">숨김</option></select></label>
      <label>과세 유형<select value={form.tax_type} onChange={(e) => setForm((p) => ({ ...p, tax_type: e.target.value }))}><option value="unclassified">미분류(결제 차단)</option><option value="taxable">과세</option><option value="tax_free">면세</option></select></label>
      <label>결제 방식<select value={form.kiwoom_pay_method} onChange={(e) => setForm((p) => ({ ...p, kiwoom_pay_method: e.target.value }))} disabled={migrationRequired}><option value="TOTAL">통합결제창</option><option value="BANK">계좌이체 전용</option></select></label>
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
    <div className="product-list">{items.map((item) => { const tax = taxTypeMeta(item.tax_type); return <article className={item.status === 'active' ? 'product-item' : 'product-item off'} key={item.id}>{item.image_url ? <img className="product-image-preview" src={item.image_url} alt=""/> : <div className="product-image-placeholder">이미지 없음</div>}<div className="product-copy"><strong>{item.name}</strong><span>{item.voucher_count}장{Number(item.bonus_count) > 0 ? ` + ${item.bonus_count}장` : ''} · 판매가 {krw(item.sale_price)} · 순서 {item.display_order}</span><span className={`tax-type-badge ${tax.tone}`}>{tax.label}</span><span className="badge">{item.kiwoom_pay_method === 'BANK' ? '계좌이체 전용' : '통합결제창'}</span><span className={`exposure-status ${item.exposure_status}`}>{item.exposure_label}</span>{item.is_event && <span className="event-period">{displayEventPeriod(item)}</span>}</div><div className="row-actions"><button className="ghost" onClick={() => edit(item)}>수정</button><button className="ghost" onClick={() => toggle(item)}>{item.status === 'active' ? '숨김' : '판매 재개'}</button></div></article>; })}</div>
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
    <div className="panel-title"><div><p className="panel-note titleless-guidance">장부직원과 일반사용자 앱으로 공지·이벤트 알림을 수동 발송합니다.</p></div><button type="button" className="ghost notification-history-button" onClick={() => setHistoryOpen(true)}><CalendarDays size={18}/> 발송 이력</button></div>
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
  if (section === 'announcements') return <section className="panel"><div className="panel-title"><div><p className="panel-note titleless-guidance">앱에 계속 노출할 소식을 작성하고 관리합니다.</p></div></div>{error && <div className="alert error">{error}</div>}<form className="form" onSubmit={publish}><label>제목<input value={form.title} maxLength="120" onChange={e=>setForm({...form,title:e.target.value})} required/></label><label>내용<textarea rows="5" value={form.content} onChange={e=>setForm({...form,content:e.target.value})} required/></label><label className="checkbox"><input type="checkbox" checked={form.pinned} onChange={e=>setForm({...form,pinned:e.target.checked})}/> 상단 고정</label><label className="checkbox"><input type="checkbox" checked={form.send_push} onChange={e=>setForm({...form,send_push:e.target.checked})}/> 푸시 알림도 함께 발송</label><button className="primary">게시하기</button></form><div className="list">{data.items.map(item=><article className={`card ${item.status === 'hidden' ? 'muted' : ''}`} key={item.id}><h3>{item.pinned && '📌 '}{item.title} {item.status === 'hidden' && '(숨김)'}</h3><p>{item.content}</p><small>{new Date(item.created_at).toLocaleString('ko-KR')}</small><div className="actions"><button className="ghost" onClick={()=>patchItem(item.id,{pinned:!item.pinned})}>{item.pinned?'고정 해제':'상단 고정'}</button><button className="ghost" onClick={()=>patchItem(item.id,{status:item.status==='hidden'?'published':'hidden'})}>{item.status==='hidden'?'노출로 복원':'숨김'}</button></div></article>)}</div></section>;
  return <section className="panel"><div className="panel-title"><div><p className="panel-note titleless-guidance">평균 별점 ⭐️ {data.average_rating ?? 0} ({data.review_count ?? 0}개)</p></div><select value={sort} onChange={e=>setSort(e.target.value)}><option value="latest">최신순</option><option value="rating_asc">낮은 별점순</option></select></div>{error && <div className="alert error">{error}</div>}<div className="list">{data.items.map(item=><article className={`card ${item.status==='hidden'?'muted':''}`} key={item.id}><h3>{item.author_name} {'⭐'.repeat(item.rating)} {item.status==='hidden'&&'(숨김)'}</h3><p>{item.content || '내용 없이 별점만 남긴 리뷰예요.'}</p>{item.image_urls?.length>0&&<div className="review-images">{item.image_urls.map(url=><img src={url} key={url} alt="리뷰"/>)}</div>}<label>사장님 답글<textarea defaultValue={item.owner_reply ?? ''} id={`reply-${item.id}`}/></label><div className="actions"><button className="primary" onClick={()=>patchItem(item.id,{owner_reply:document.getElementById(`reply-${item.id}`).value})}>답글 저장</button><button className="ghost" onClick={()=>patchItem(item.id,{status:item.status==='hidden'?'visible':'hidden'})}>{item.status==='hidden'?'노출로 복원':'숨김 처리'}</button></div></article>)}</div></section>;
}

function AdminMockPage({ title, description, children, actions = null, preview = true, showHeader = true, className = '' }) {
  return <section className={`admin-mock-page${className ? ` ${className}` : ''}`}>
    {showHeader && <div className="panel-title admin-mock-page-title"><div>{preview && <span className="eyebrow">PREVIEW</span>}{title && <h2>{title}</h2>}<p className={`panel-note${!title ? ' titleless-guidance' : ''}`}>{description}</p></div><div className="admin-page-actions">{actions}{preview && <span className="badge">목업</span>}</div></div>}
    {children ?? <article className="panel"><p className="empty-state">화면 구성을 준비 중입니다.</p></article>}
  </section>;
}


const SETTLEMENT_STATUS = {
  pending: '정산 확인 대기', confirmed: '정산 확정', finalized: '정산 마감', completed: '정산 완료', cancelled: '정산 취소',
};
const TAX_INVOICE_STATUS = {
  not_requested: '미요청', requested: '발급 요청', issuing: '발행 처리 중', issued: '발행 완료',
  nts_sending: '국세청 전송 중', nts_accepted: '국세청 접수 완료', failed: '발행 실패', cancelled: '발행 취소',
};
const PAYMENT_STATUS = { unpaid: '입금 대기', scheduled: '입금 예정', paid: '입금 완료', overdue: '입금 지연' };

const SETTLEMENT_V2_PARTIES = {
  supplier: { name: 'GreenEat', biz_reg_no: '123-45-67890', branch_no: null, representative_name: '이용욱', address: '서울특별시 강남구 테헤란로 1', business_type: '음식점업', business_item: '단체급식', tax_invoice_email: 'tax@greeneat.example', contact_name: '이용욱', contact_phone: '02-1000-1000' },
  gaon: { name: '가온테크 주식회사', biz_reg_no: '214-86-12345', branch_no: null, representative_name: '김가온', address: '서울특별시 강남구 테헤란로 123', business_type: '서비스업', business_item: '소프트웨어 개발', tax_invoice_email: 'tax@gaon.example', contact_name: '김담당', contact_phone: '02-2000-1000' },
  moa: { name: '모아산업', biz_reg_no: '220-88-45678', branch_no: null, representative_name: '박모아', address: '경기도 성남시 분당구 판교로 45', business_type: '제조업', business_item: '산업용 기기', tax_invoice_email: 'tax@moa.example', contact_name: '박담당', contact_phone: '031-2000-2000' },
  saebom: { name: '새봄복지관', biz_reg_no: '110-82-98765', branch_no: null, representative_name: '최새봄', address: '서울특별시 마포구 월드컵로 88', business_type: '사회복지서비스업', business_item: '복지시설 운영', tax_invoice_email: 'tax@saebom.example', contact_name: '최담당', contact_phone: '02-3000-3000' },
};

function settlementSeed({ id, companyId, merchantId = 'merchant-greeneat', periodStart, periodEnd, total, supply, vat, recipient, settlementStatus, taxStatus, paymentStatus, dueDate, issuedAt = null, paidAt = null, failedReason = null }) {
  const now = `${periodEnd}T09:00:00+09:00`;
  return {
    id, company_id: companyId, merchant_id: merchantId, period_start: periodStart, period_end: periodEnd,
    total_amount: total, supply_amount: supply, vat_amount: vat,
    settlement_status: settlementStatus, tax_invoice_status: taxStatus, payment_status: paymentStatus,
    due_date: dueDate, created_at: now, updated_at: now,
    confirmed_at: settlementStatus === 'confirmed' ? now : null,
    tax_invoice_requested_at: taxStatus === 'not_requested' ? null : now,
    supplier: { ...SETTLEMENT_V2_PARTIES.supplier }, recipient: { ...recipient },
    invoice: taxStatus === 'not_requested' ? null : {
      id: `mock-invoice-${id}`, provider: 'local_mock', approval_number: null, external_url: null, pdf_url: null,
      written_at: periodEnd, issued_at: issuedAt, nts_sent_at: taxStatus === 'nts_sending' || taxStatus === 'nts_accepted' ? issuedAt : null,
      nts_accepted_at: taxStatus === 'nts_accepted' ? issuedAt : null, failed_reason: failedReason,
    },
    payment: { bank_name: null, account_number: null, account_holder: null, scheduled_at: dueDate, paid_at: paidAt, amount: paidAt ? total : 0, memo: paidAt ? `${periodStart.slice(0, 7)} 식대 정산` : null },
  };
}

const SETTLEMENT_V2_SEED = [
  settlementSeed({ id: 'stl-2026-07-gaon', companyId: 'company-gaon', periodStart: '2026-07-01', periodEnd: '2026-07-31', total: 4812000, supply: 4374545, vat: 437455, recipient: SETTLEMENT_V2_PARTIES.gaon, settlementStatus: 'pending', taxStatus: 'not_requested', paymentStatus: 'unpaid', dueDate: '2026-08-14' }),
  settlementSeed({ id: 'stl-2026-07-moa', companyId: 'company-moa', periodStart: '2026-07-01', periodEnd: '2026-07-31', total: 2640000, supply: 2400000, vat: 240000, recipient: SETTLEMENT_V2_PARTIES.moa, settlementStatus: 'confirmed', taxStatus: 'requested', paymentStatus: 'unpaid', dueDate: '2026-08-14' }),
  settlementSeed({ id: 'stl-2026-06-gaon', companyId: 'company-gaon', periodStart: '2026-06-01', periodEnd: '2026-06-30', total: 4532000, supply: 4120000, vat: 412000, recipient: SETTLEMENT_V2_PARTIES.gaon, settlementStatus: 'confirmed', taxStatus: 'nts_accepted', paymentStatus: 'paid', dueDate: '2026-07-14', issuedAt: '2026-07-02T10:20:00+09:00', paidAt: '2026-07-14T10:30:00+09:00' }),
  settlementSeed({ id: 'stl-2026-05-saebom', companyId: 'company-saebom', periodStart: '2026-05-01', periodEnd: '2026-05-31', total: 4380000, supply: 3981818, vat: 398182, recipient: SETTLEMENT_V2_PARTIES.saebom, settlementStatus: 'confirmed', taxStatus: 'nts_sending', paymentStatus: 'scheduled', dueDate: '2026-06-14', issuedAt: '2026-06-02T09:10:00+09:00' }),
  settlementSeed({ id: 'stl-2026-04-moa', companyId: 'company-moa', periodStart: '2026-04-01', periodEnd: '2026-04-30', total: 4632000, supply: 4210909, vat: 421091, recipient: SETTLEMENT_V2_PARTIES.moa, settlementStatus: 'confirmed', taxStatus: 'failed', paymentStatus: 'overdue', dueDate: '2026-05-14', failedReason: '로컬 목업: 필수 수신 정보 확인 필요' }),
  settlementSeed({ id: 'stl-2026-03-gaon', companyId: 'company-gaon', periodStart: '2026-03-01', periodEnd: '2026-03-31', total: 4120000, supply: 3745455, vat: 374545, recipient: SETTLEMENT_V2_PARTIES.gaon, settlementStatus: 'cancelled', taxStatus: 'cancelled', paymentStatus: 'unpaid', dueDate: '2026-04-14' }),
  settlementSeed({ id: 'stl-2026-02-moa', companyId: 'company-moa', periodStart: '2026-02-01', periodEnd: '2026-02-28', total: 3300000, supply: 3000000, vat: 300000, recipient: SETTLEMENT_V2_PARTIES.moa, settlementStatus: 'confirmed', taxStatus: 'issuing', paymentStatus: 'unpaid', dueDate: '2026-03-14' }),
  settlementSeed({ id: 'stl-2026-01-saebom', companyId: 'company-saebom', periodStart: '2026-01-01', periodEnd: '2026-01-31', total: 2200000, supply: 2000000, vat: 200000, recipient: SETTLEMENT_V2_PARTIES.saebom, settlementStatus: 'confirmed', taxStatus: 'issued', paymentStatus: 'scheduled', dueDate: '2026-02-14', issuedAt: '2026-02-02T11:00:00+09:00' }),
];

function loadSettlementV2Rows() {
  return loadSettlementMockRows(settlementLocalStorage(), SETTLEMENT_V2_SEED);
}

function settlementLocalStorage() {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

function useSettlementV2Rows() {
  const [rows, setRowsState] = useState(loadSettlementV2Rows);
  const setRows = (updater) => setRowsState((current) => {
    const next = typeof updater === 'function' ? updater(current) : updater;
    saveSettlementMockRows(settlementLocalStorage(), next);
    return next;
  });
  return [rows, setRows];
}

function formatKoreanTimestamp(value) {
  if (!value) return '미확정';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '미확정';
  return new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function settlementV2Evidence(row, recipient = row.recipient) {
  return { id: `ev-${row.id}`, kind: '매출', item: `${row.period_start.slice(0, 7)} 식대(월합계)`, type: '세금계산서', recipient: recipient.name, bizNo: recipient.biz_reg_no, supply: row.supply_amount, vat: row.vat_amount, total: row.total_amount, writtenAt: row.invoice?.written_at ?? '미확정', approvalNo: row.invoice?.approval_number ?? '미수신 (로컬 목업)', approvedAt: formatKoreanTimestamp(row.invoice?.issued_at) };
}

function SettlementV2Status({ type = 'generic', value }) {
  const labels = type === 'settlement' ? SETTLEMENT_STATUS : type === 'invoice' ? TAX_INVOICE_STATUS : type === 'payment' ? PAYMENT_STATUS : null;
  return <span className={`settlement-v2-status ${value}`}>{labels?.[value] ?? value}</span>;
}

function SettlementV2Empty({ text = '내역이 없습니다' }) {
  return <div className="settlement-v2-empty" role="status"><FileText size={32}/><strong>{text}</strong></div>;
}

function SettlementV2Screen({ viewer, companyProfile = null, onCompanyInfo = null }) {
  // TODO: settlements·증빙·입금 데이터와 팝빌 발행/발급요청 API로 교체합니다.
  const isMerchant = viewer === 'merchant';
  const [allRows, setRows] = useSettlementV2Rows();
  // Pilot data is authorized by a stable mock scope. The live profile only overlays display fields.
  const rows = isMerchant ? allRows : allRows.filter((row) => row.company_id === PILOT_COMPANY_SCOPE_ID);
  const [year, setYear] = useState(2026);
  const [month, setMonth] = useState('all');
  const [selectedId, setSelectedId] = useState(null);
  const [detailTab, setDetailTab] = useState('transactions');
  const [rangeMode, setRangeMode] = useState('all');
  const [rangeFrom, setRangeFrom] = useState('2026-01-01');
  const [rangeTo, setRangeTo] = useState('2026-12-31');
  const [offsetOption, setOffsetOption] = useState(false);
  const [evidenceMethod, setEvidenceMethod] = useState('service');
  const [dialog, setDialog] = useState(null);
  const [notice, setNotice] = useState('');
  const [actionError, setActionError] = useState('');
  const [confirmChecks, setConfirmChecks] = useState([false, false, false]);
  const actionButtonRef = useRef(null);
  const backButtonRef = useRef(null);
  const dialogRef = useRef(null);
  const dialogReturnRef = useRef(null);
  useEffect(() => {
    if (dialog || !dialogReturnRef.current) return undefined;
    const target = dialogReturnRef.current;
    dialogReturnRef.current = null;
    const frame = window.requestAnimationFrame(() => target.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [dialog]);
  const selected = rows.find((row) => row.id === selectedId) ?? null;
  const recipientFor = (row) => companyProfile && row && !isMerchant && canConfirmAndRequest(row) ? {
    ...row.recipient,
    id: companyProfile.id ?? row.recipient.id,
    name: companyProfile.name ?? '',
    biz_reg_no: companyProfile.biz_reg_no ?? '',
    representative_name: companyProfile.representative_name ?? '',
    address: companyProfile.address ?? '',
    business_type: companyProfile.business_type ?? '',
    business_item: companyProfile.business_item ?? '',
    tax_invoice_email: companyProfile.tax_invoice_email ?? companyProfile.contact_email ?? '',
    contact_name: companyProfile.contact_name ?? '',
    contact_phone: companyProfile.contact_phone ?? '',
  } : row?.recipient;
  const profileRecipient = recipientFor(selected);
  const recipientReady = isBusinessPartyComplete(profileRecipient);
  const selectedYear = (row) => Number(row.period_start.slice(0, 4));
  const selectedMonth = (row) => Number(row.period_start.slice(5, 7));
  const availableMonths = new Set(rows.filter((row) => selectedYear(row) === year).map(selectedMonth));
  const visibleRows = rows.filter((row) => selectedYear(row) === year && (month === 'all' || selectedMonth(row) === month));

  const transactions = selected && selectedMonth(selected) !== 3 ? [
    [formatKoreanTimestamp(`${selected.period_start}T11:42:00+09:00`), profileRecipient.name, '김민지', 9000, 9000, '완료'],
    [formatKoreanTimestamp(`${selected.period_start.slice(0, 8)}15T12:06:00+09:00`), profileRecipient.name, '박준호', 9000, 9000, '완료'],
    [formatKoreanTimestamp(`${selected.period_end}T18:21:00+09:00`), profileRecipient.name, '이서연', 9000, 9000, '완료'],
  ] : [];
  const evidenceRecord = selected && ['issued', 'nts_sending', 'nts_accepted'].includes(selected.tax_invoice_status) ? settlementV2Evidence(selected, profileRecipient) : null;
  const evidenceRows = evidenceRecord ? [[
    evidenceRecord.type, evidenceRecord.item, selected.supplier.name, selected.supplier.representative_name, selected.supplier.biz_reg_no,
    evidenceRecord.writtenAt, evidenceRecord.supply, evidenceRecord.vat, evidenceRecord.total,
    evidenceRecord.approvalNo, evidenceRecord.approvedAt, selected.tax_invoice_status,
  ]] : [];
  const depositRows = selected?.payment_status === 'paid' ? [[formatKoreanTimestamp(selected.payment.paid_at), selected.payment.amount, selected.payment.memo]] : [];

  function openSettlement(row) {
    setSelectedId(row.id);
    setDetailTab('transactions');
    setRangeMode('all');
    setRangeFrom(row.period_start);
    setRangeTo(row.period_end);
    setNotice('');
    setActionError('');
  }

  function closeDialog() {
    setDialog(null);
  }

  function handleDialogKeyDown(event) {
    if (event.key === 'Escape') {
      closeDialog();
      return;
    }
    if (event.key !== 'Tab' || !dialogRef.current) return;
    const focusable = [...dialogRef.current.querySelectorAll('button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])')];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  function confirmInvoiceAction() {
    if (!selected) return;
    const now = new Date().toISOString();
    const action = isMerchant ? 'merchant_issue' : 'confirm_and_request';
    if (!isMerchant && (!recipientReady || !confirmChecks.every(Boolean))) {
      setActionError('회사 정보의 필수 공급받는자 정보를 모두 입력하고 확인 항목에 동의해 주세요.');
      return;
    }
    const changed = transitionSettlementMockRow(selected, action, now, isMerchant ? null : profileRecipient);
    if (!changed) {
      setActionError('현재 정산 상태에서는 요청을 처리할 수 없습니다. 새로고침 후 상태를 확인해 주세요.');
      return;
    }
    setRows((current) => current.map((row) => row.id === selected.id ? changed : row));
    setActionError('');
    setNotice(isMerchant
      ? '로컬 목업에서 세금계산서를 발행 완료 상태로 변경했습니다. Popbill 전송은 실행되지 않았습니다.'
      : '정산 확정과 세금계산서 발급 요청을 한 번에 저장한 로컬 목업 상태입니다.');
    dialogReturnRef.current = backButtonRef.current;
    setDialog(null);
  }

  function simulatePayment() {
    if (!selected || !isMerchant) return;
    const now = new Date().toISOString();
    const changed = transitionSettlementMockRow(selected, 'merchant_mark_paid', now);
    if (!changed) {
      setActionError('현재 정산·세금계산서 상태에서는 입금 완료로 변경할 수 없습니다.');
      return;
    }
    setRows((current) => current.map((row) => row.id === selected.id ? changed : row));
    setActionError('');
    setNotice('로컬 목업에서 입금 완료 상태로 변경했습니다. 실제 입금 또는 은행 조회는 실행되지 않았습니다.');
  }

  if (!selected) return <AdminMockPage title="매출 정산" description={isMerchant ? '업체별 월 정산과 증빙·입금 처리 현황을 확인합니다.' : '우리 회사의 월별 청구와 세금계산서 처리 현황을 확인합니다.'} showHeader={false} preview={false} className="merchant-regular-weight merchant-open-table">
    <div className="alert warning settlement-mock-notice" role="status">데모용 로컬 목업 데이터입니다. 실제 청구·세금계산서·입금 정보가 아니며 외부 기관으로 전송되지 않습니다.</div>
    {notice && <div className="alert success" role="status" aria-live="polite">{notice}</div>}
    <div className="settlement-v2-title-actions"><span className="badge">월별 정산 목록</span></div>
    <div className="settlement-v2-periodbar"><div className="settlement-v2-months" role="tablist" aria-label="정산월"><button id="settlement-month-all-tab" type="button" role="tab" aria-selected={month === 'all'} aria-controls="settlement-month-panel" className={month === 'all' ? 'active' : ''} onClick={() => setMonth('all')}>전체</button>{Array.from({ length: 12 }, (_, index) => index + 1).map((value) => <button id={`settlement-month-${value}-tab`} type="button" role="tab" aria-selected={month === value} aria-controls="settlement-month-panel" key={value} className={month === value ? 'active' : ''} disabled={!availableMonths.has(value)} onClick={() => setMonth(value)}>{value}월</button>)}</div><div className="settlement-v2-year-control" aria-label="정산 연도"><button type="button" className="ghost" onClick={() => { setYear((value) => value - 1); setMonth('all'); }} aria-label="이전 연도">‹</button><strong>{year}</strong><button type="button" className="ghost" onClick={() => { setYear((value) => value + 1); setMonth('all'); }} aria-label="다음 연도">›</button></div></div>
    <div className="settlement-v2-guide"><span>· 매출 금액은 매일 1회 업데이트됩니다.</span><span>· 고객사와 직접거래가 있는 경우 정산금액에서 제외되어 노출됩니다.</span></div>
    <article id="settlement-month-panel" aria-labelledby={month === 'all' ? 'settlement-month-all-tab' : `settlement-month-${month}-tab`} className="panel settlement-v2-list-panel" role="tabpanel"><div className="table-wrap"><table className="settlement-v2-table"><thead><tr><th>정산월</th><th>{isMerchant ? '업체명' : '공급자'}</th><th className="money">정산금액</th><th>정산</th><th>세금계산서</th><th>입금</th><th>주요 액션</th></tr></thead><tbody>{visibleRows.map((row) => { const displayRecipient = recipientFor(row); return <tr key={row.id} className="settlement-v2-clickable-row" onClick={() => openSettlement(row)}><td><button type="button" className="settlement-v2-row-link" aria-label={`${row.period_start.slice(0, 7)} ${displayRecipient.name} 정산서 상세 보기`} onClick={(event) => { event.stopPropagation(); openSettlement(row); }}>{row.period_start.slice(0, 7)} <small className="mock-row-label">목업</small></button></td><td>{isMerchant ? displayRecipient.name : row.supplier.name}</td><td className="money">{krw(row.total_amount)}</td><td><SettlementV2Status type="settlement" value={row.settlement_status}/></td><td><SettlementV2Status type="invoice" value={row.tax_invoice_status}/></td><td><SettlementV2Status type="payment" value={row.payment_status}/></td><td><button type="button" className="ghost settlement-v2-inline-action" onClick={(event) => { event.stopPropagation(); openSettlement(row); }}>{!isMerchant && canConfirmAndRequest(row) ? '확정 및 발급 요청' : '상세 보기'}</button></td></tr>; })}</tbody></table></div>{visibleRows.length === 0 && <SettlementV2Empty />}</article>
  </AdminMockPage>;

  const invoiceAvailable = ['issued', 'nts_sending', 'nts_accepted'].includes(selected.tax_invoice_status);
  const companyCanRequest = !isMerchant && canConfirmAndRequest(selected);
  const merchantCanIssue = isMerchant && canMerchantIssue(selected);
  const merchantCanMarkPaid = isMerchant && canMerchantMarkPaid(selected);
  return <AdminMockPage title={null} description="" showHeader={false} preview={false} className="merchant-regular-weight merchant-open-table">
    <div className="alert warning settlement-mock-notice" role="status">이 정산서와 거래 행은 합성된 로컬 목업 데이터입니다. 실제 청구·발행·입금 처리가 아닙니다.</div>
    {actionError && <div className="alert error" role="alert" aria-live="assertive">{actionError}</div>}
    {notice && <div className="alert success" role="status" aria-live="polite">{notice}</div>}
    <div className="settlement-v2-detailbar"><button ref={backButtonRef} type="button" className="ghost" onClick={() => { setSelectedId(null); setNotice(''); setActionError(''); }}>‹ 뒤로</button><div className="settlement-v2-detail-actions"><button type="button" className="ghost" onClick={() => setNotice(`${selected.period_start.slice(0, 7)} 정산자료 엑셀 다운로드는 실제 API 연동 단계에서 제공됩니다.`)}><Download size={16}/> 엑셀 다운로드</button>{invoiceAvailable && <><button type="button" className="ghost" onClick={() => setNotice('보기 기능은 로컬 목업입니다. 실제 Popbill 문서 URL이 없어 외부 문서를 열지 않았습니다.')}><FileText size={16}/> 보기 (목업)</button><button type="button" className="ghost" onClick={() => setNotice('PDF는 실제 Popbill 연동 후 제공됩니다. 로컬 목업 파일을 생성하지 않았습니다.')}><Download size={16}/> PDF 미제공</button></>}{merchantCanIssue && <button ref={actionButtonRef} type="button" className="primary" onClick={() => { setConfirmChecks([false, false, false]); dialogReturnRef.current = actionButtonRef.current; setDialog('issue'); }}>세금계산서 발행 시뮬레이션</button>}{companyCanRequest && <button ref={actionButtonRef} type="button" className="primary" disabled={!recipientReady} onClick={() => { setConfirmChecks([false, false, false]); dialogReturnRef.current = actionButtonRef.current; setDialog('request'); }}>정산 확정 및 발급 요청</button>}{merchantCanMarkPaid && <button type="button" className="ghost" onClick={simulatePayment}>입금 완료 시뮬레이션</button>}</div></div>
    {!isMerchant && !recipientReady && <div className="alert warning" role="alert">정산 확정에 필요한 회사 정보(사업자 정보, 세금계산서 이메일, 담당자명·연락처)가 미완성입니다. <button type="button" className="ghost" onClick={onCompanyInfo}>회사 정보에서 입력하기</button></div>}
    <article className="panel settlement-v2-overview">
      <div className="settlement-v2-overview-row"><span>정산 요약</span><div className="settlement-v2-summary-grid"><div><small>공급자</small><strong>{selected.supplier.name}</strong></div><div><small>정산금액</small><strong className="money">{krw(selected.total_amount)}</strong></div><div><small>정산</small><SettlementV2Status type="settlement" value={selected.settlement_status}/></div><div><small>세금계산서</small><SettlementV2Status type="invoice" value={selected.tax_invoice_status}/></div><div><small>입금</small><SettlementV2Status type="payment" value={selected.payment_status}/></div></div></div>
      <div className="settlement-v2-overview-row"><span>정산 기간</span><strong>{selected.period_start} ~ {selected.period_end}</strong></div>
      <div className="settlement-v2-overview-row"><span>금액 구성</span><div className="settlement-v2-amounts"><div><small>공급가액</small><strong className="money">{krw(selected.supply_amount)}</strong></div><div><small>부가세</small><strong className="money">{krw(selected.vat_amount)}</strong></div><div><small>합계</small><strong className="money">{krw(selected.total_amount)}</strong></div></div></div>
      <div className="settlement-v2-overview-row"><span>입금 정보</span><div className="settlement-v2-account-summary"><span>은행 <strong>{selected.payment.bank_name || '미설정/확인 필요'}</strong></span><span>계좌번호 <strong>{selected.payment.account_number || '미설정/확인 필요'}</strong></span><span>예금주 <strong>{selected.payment.account_holder || '미설정/확인 필요'}</strong></span><span>입금 예정일 <strong>{selected.due_date || '확인 필요'}</strong></span>{!isMerchant && <small>회사에서는 입금 정보를 조회만 할 수 있습니다.</small>}</div></div>
      <div className="settlement-v2-overview-row"><span>정산 옵션</span><div className="settlement-v2-options"><div><small>적격증빙 상계 여부</small><button type="button" aria-pressed={offsetOption} className={offsetOption ? 'selected' : ''} onClick={() => setOffsetOption((value) => !value)}>{offsetOption ? '상계' : '별도'}</button></div><div><small>매출 증빙 방식</small>{[['direct', '공급자직접발행'], ['service', '서비스 내 증빙발행'], ['paper', '종이세금계산서']].map(([id, label]) => <button type="button" aria-pressed={evidenceMethod === id} key={id} className={evidenceMethod === id ? 'selected' : ''} onClick={() => setEvidenceMethod(id)}>{label}</button>)}</div></div></div>
      <div className="settlement-v2-overview-row"><span>공급받는자 정보</span><dl className="settlement-v2-business"><div><dt>상호</dt><dd>{profileRecipient.name || '확인 필요'}</dd></div><div><dt>사업자번호</dt><dd>{profileRecipient.biz_reg_no || '확인 필요'}</dd></div><div><dt>종사업장번호</dt><dd>{profileRecipient.branch_no || '해당 없음'}</dd></div><div><dt>대표자명</dt><dd>{profileRecipient.representative_name || '확인 필요'}</dd></div><div><dt>주소</dt><dd>{profileRecipient.address || '확인 필요'}</dd></div><div><dt>업태</dt><dd>{profileRecipient.business_type || '확인 필요'}</dd></div><div><dt>종목</dt><dd>{profileRecipient.business_item || '확인 필요'}</dd></div><div><dt>세금계산서 이메일</dt><dd>{profileRecipient.tax_invoice_email || '확인 필요'}</dd></div></dl></div>
      {invoiceAvailable && <div className="settlement-v2-overview-row"><span>세금계산서 메타데이터</span><dl className="settlement-v2-business"><div><dt>로컬 목업 ID</dt><dd>{selected.invoice?.id}</dd></div><div><dt>작성일자</dt><dd>{selected.invoice?.written_at || '미확정'}</dd></div><div><dt>발행일시</dt><dd>{formatKoreanTimestamp(selected.invoice?.issued_at)}</dd></div><div><dt>승인번호</dt><dd>{selected.invoice?.approval_number || '미수신 (로컬 목업)'}</dd></div></dl></div>}
      {selected.tax_invoice_status === 'failed' && <div className="settlement-v2-overview-row"><span>실패 사유</span><strong className="settlement-v2-error-text">{selected.invoice?.failed_reason || '확인 필요'}</strong></div>}
    </article>
    <div className="settlement-v2-tabs" role="tablist" aria-label="정산서 상세"><button id="settlement-transactions-tab" type="button" role="tab" aria-selected={detailTab === 'transactions'} aria-controls="settlement-transactions-panel" className={detailTab === 'transactions' ? 'active' : ''} onClick={() => setDetailTab('transactions')}>거래 내역</button><button id="settlement-evidence-tab" type="button" role="tab" aria-selected={detailTab === 'evidence'} aria-controls="settlement-evidence-panel" className={detailTab === 'evidence' ? 'active' : ''} onClick={() => setDetailTab('evidence')}>증빙 내역</button><button id="settlement-deposits-tab" type="button" role="tab" aria-selected={detailTab === 'deposits'} aria-controls="settlement-deposits-panel" className={detailTab === 'deposits' ? 'active' : ''} onClick={() => setDetailTab('deposits')}>입금/이체 내역</button></div>
    {detailTab === 'transactions' && <article id="settlement-transactions-panel" aria-labelledby="settlement-transactions-tab" role="tabpanel" className="panel"><div className="settlement-v2-filterbar"><div className="mock-segmented"><button type="button" aria-pressed={rangeMode === 'all'} className={rangeMode === 'all' ? 'active' : ''} onClick={() => setRangeMode('all')}>전체</button><button type="button" aria-pressed={rangeMode === 'range'} className={rangeMode === 'range' ? 'active' : ''} onClick={() => setRangeMode('range')}>기간검색</button></div>{rangeMode === 'range' && <><input type="date" aria-label="조회 시작일" value={rangeFrom} onChange={(event) => setRangeFrom(event.target.value)}/><span>~</span><input type="date" aria-label="조회 종료일" value={rangeTo} onChange={(event) => setRangeTo(event.target.value)}/></>}<button type="button" className="ghost" onClick={() => setNotice('')}>조회</button></div><p className="panel-note">합성된 목업 거래 행입니다. 취소·이월·보상 등으로 매출과 정산금액이 다를 수 있습니다.</p><div className="table-wrap"><table><thead><tr><th>거래일시</th><th>업체명</th><th>사용자명</th><th className="money">결제금액</th><th className="money">정산(예정)금액</th><th>상태</th></tr></thead><tbody>{transactions.map((row) => <tr key={row[0]}><td>{row[0]}</td><td>{row[1]} <small className="mock-row-label">목업</small></td><td>{row[2]}</td><td className="money">{krw(row[3])}</td><td className="money">{krw(row[4])}</td><td><SettlementV2Status value={row[5]}/></td></tr>)}</tbody></table></div>{transactions.length === 0 && <SettlementV2Empty />}</article>}
    {detailTab === 'evidence' && <article id="settlement-evidence-panel" aria-labelledby="settlement-evidence-tab" role="tabpanel" className="panel"><div className="panel-title"><div><h3>매출(거래 금액) 증빙 내역</h3><p className="panel-note">식당이 업체에 발행한 매출증빙입니다.</p></div></div><div className="table-wrap"><table><thead><tr><th>증빙유형</th><th>품목</th><th>공급하는자</th><th>대표자명</th><th>사업자번호</th><th>작성일자</th><th className="money">공급가액</th><th className="money">부가세액</th><th className="money">총액</th><th>승인번호</th><th>승인일자</th><th>상태</th></tr></thead><tbody>{evidenceRows.map((row) => <tr key={`${selected.id}-${row[0]}`}>{row.slice(0, 6).map((value, index) => <td key={index}>{value}</td>)}<td className="money">{krw(row[6])}</td><td className="money">{krw(row[7])}</td><td className="money">{krw(row[8])}</td><td>{row[9]}</td><td>{row[10]}</td><td><SettlementV2Status type="invoice" value={row[11]}/></td></tr>)}</tbody></table></div>{evidenceRows.length === 0 && <SettlementV2Empty />}<div className="settlement-v2-attachments"><strong>첨부 자료</strong><span>등록된 첨부 자료가 없습니다.</span></div></article>}
    {detailTab === 'deposits' && <article id="settlement-deposits-panel" aria-labelledby="settlement-deposits-tab" role="tabpanel" className="panel"><div className="panel-title"><div><h3>입금 내역 (금액: {depositRows.length ? krw(selected.total_amount) : '0원'})</h3><p className="panel-note">입금 계좌와 이체 내역입니다.{!isMerchant && ' 회사 관리자는 조회만 할 수 있습니다.'}</p></div></div><div className="settlement-v2-account"><span>은행 <strong>{selected.payment.bank_name || '미설정/확인 필요'}</strong></span><span>계좌번호 <strong>{selected.payment.account_number || '미설정/확인 필요'}</strong></span><span>예금주 <strong>{selected.payment.account_holder || '미설정/확인 필요'}</strong></span><span>입금 예정일 <strong>{selected.due_date || '확인 필요'}</strong></span></div><div className="table-wrap"><table><thead><tr><th>거래 일시</th><th className="money">입금액(원)</th><th>적요</th></tr></thead><tbody>{depositRows.map((row) => <tr key={row[0]}><td>{row[0]}</td><td className="money">{krw(row[1])}</td><td>{row[2]}</td></tr>)}</tbody></table></div>{depositRows.length === 0 && <SettlementV2Empty />}</article>}
    {dialog && <div className="modal-backdrop" onClick={closeDialog}><section ref={dialogRef} className="invite-modal mock-tax-modal" role="dialog" aria-modal="true" aria-labelledby="settlement-v2-dialog-title" onClick={(event) => event.stopPropagation()} onKeyDown={handleDialogKeyDown}><div className="modal-head"><div><span className="eyebrow">TAX INVOICE · LOCAL MOCK</span><h2 id="settlement-v2-dialog-title">{isMerchant ? '세금계산서 발행 시뮬레이션' : '정산 확정 및 발급 요청'}</h2></div><button type="button" className="ghost" aria-label="닫기" onClick={closeDialog} autoFocus><X size={18}/></button></div><div className="alert warning">이 화면은 로컬 상태 목업입니다. Popbill 또는 국세청으로 데이터를 전송하지 않습니다.</div><div className="mock-invoice-parties"><article><span>공급자</span><strong>{selected.supplier.name}</strong><small>{selected.supplier.biz_reg_no || '사업자번호 확인 필요'} · {selected.supplier.representative_name || '대표자 확인 필요'}</small></article><article><span>공급받는자</span><strong>{profileRecipient.name || '확인 필요'}</strong><small>{profileRecipient.biz_reg_no || '사업자번호 확인 필요'} · {profileRecipient.representative_name || '대표자 확인 필요'}</small></article></div><dl className="settlement-v2-business settlement-v2-dialog-business"><div><dt>상호</dt><dd>{profileRecipient.name || '확인 필요'}</dd></div><div><dt>사업자등록번호</dt><dd>{profileRecipient.biz_reg_no || '확인 필요'}</dd></div><div><dt>종사업장번호</dt><dd>{profileRecipient.branch_no || '해당 없음'}</dd></div><div><dt>대표자</dt><dd>{profileRecipient.representative_name || '확인 필요'}</dd></div><div><dt>사업장 주소</dt><dd>{profileRecipient.address || '확인 필요'}</dd></div><div><dt>업태</dt><dd>{profileRecipient.business_type || '확인 필요'}</dd></div><div><dt>종목</dt><dd>{profileRecipient.business_item || '확인 필요'}</dd></div><div><dt>수신 이메일</dt><dd>{profileRecipient.tax_invoice_email || '확인 필요'}</dd></div></dl><div className="table-wrap"><table><thead><tr><th>품목</th><th className="money">공급가액</th><th className="money">부가세</th><th className="money">합계</th><th>작성일자</th></tr></thead><tbody><tr><td>{selected.period_start.slice(0, 7)} 식대(월합계)</td><td className="money">{krw(selected.supply_amount)}</td><td className="money">{krw(selected.vat_amount)}</td><td className="money">{krw(selected.total_amount)}</td><td>{selected.period_end || '미확정'}</td></tr></tbody></table></div>{!isMerchant && <fieldset className="settlement-v2-confirmations"><legend>확정 전 필수 확인</legend>{['정산 기간과 정산금액을 확인했습니다.', '공급받는자 사업자 정보와 수신 이메일을 확인했습니다.', '정산 확정과 세금계산서 발급 요청이 동시에 처리됨에 동의합니다.'].map((label, index) => <label key={label}><input type="checkbox" checked={confirmChecks[index]} onChange={(event) => setConfirmChecks((current) => current.map((value, currentIndex) => currentIndex === index ? event.target.checked : value))}/><span>{label}</span></label>)}</fieldset>}<div className="modal-actions"><button type="button" className="ghost" onClick={closeDialog}>닫기</button><button type="button" className="primary" onClick={confirmInvoiceAction} disabled={!isMerchant && (!recipientReady || !confirmChecks.every(Boolean))}>{isMerchant ? '발행 완료로 변경' : '정산 확정 및 발급 요청'}</button></div></section></div>}
  </AdminMockPage>;
}

function MerchantSettlementV2Mock() {
  return <SettlementV2Screen viewer="merchant" />;
}

function CompanySettlementV2Mock({ company, onCompanyInfo }) {
  return <SettlementV2Screen viewer="company" companyProfile={company} onCompanyInfo={onCompanyInfo} />;
}

function SettlementEvidenceV2Mock() {
  // TODO: 팝빌 발행 증빙 통합 조회와 실제 엑셀 다운로드 API로 교체합니다.
  const [settlementRows] = useSettlementV2Rows();
  const [year, setYear] = useState('2026');
  const [kind, setKind] = useState('전체');
  const [type, setType] = useState('전체');
  const [notice, setNotice] = useState('');
  const evidenceRecords = settlementRows.filter((row) => ['issued', 'nts_sending', 'nts_accepted'].includes(row.tax_invoice_status)).map(settlementV2Evidence);
  const rows = evidenceRecords.filter((row) => row.writtenAt.startsWith(year) && (kind === '전체' || row.kind === kind) && (type === '전체' || row.type === type));
  return <AdminMockPage title="증빙 내역" description="전 기간·모든 업체의 매출증빙을 통합 조회합니다." showHeader={false} className="merchant-regular-weight merchant-open-table">
    {notice && <div className="alert success">{notice}</div>}
    <article className="panel"><div className="settlement-v2-evidence-head"><div className="settlement-v2-evidence-filters"><label>조회기간<select value={year} onChange={(event) => setYear(event.target.value)}><option>2026</option><option>2025</option></select></label><label>증빙 구분<select value={kind} onChange={(event) => setKind(event.target.value)}><option>전체</option><option>매출</option><option>매입</option></select></label><label>증빙 유형<select value={type} onChange={(event) => setType(event.target.value)}><option>전체</option><option>세금계산서</option><option>현금영수증</option><option>카드</option></select></label></div><button type="button" className="primary" onClick={() => setNotice('실제 엑셀 다운로드는 증빙 데이터 연동 후 제공됩니다.')}><Download size={16}/> 부가가치세 신고 참고자료 엑셀 다운로드</button></div><div className="settlement-v2-guide"><span>· 조회기간은 각 증빙의 작성일자 기준입니다.</span><span>· 국세청 부가가치세 신고 참고자료로써 증빙내역을 표시합니다. 상세는 매출 정산에서 확인해 주세요.</span></div><div className="table-wrap"><table><thead><tr><th>증빙 구분</th><th>품목명</th><th>증빙 유형</th><th>공급받는자</th><th>발급수단(사업자)번호</th><th className="money">공급가액</th><th className="money">부가세</th><th className="money">총액</th><th>작성일자</th><th>승인번호</th><th>승인일자</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td><SettlementV2Status value={row.kind}/></td><td>{row.item}</td><td>{row.type}</td><td>{row.recipient}</td><td>{row.bizNo}</td><td className="money">{krw(row.supply)}</td><td className="money">{krw(row.vat)}</td><td className="money">{krw(row.total)}</td><td>{row.writtenAt}</td><td>{row.approvalNo}</td><td>{row.approvedAt}</td></tr>)}</tbody></table></div>{rows.length === 0 && <SettlementV2Empty text="No data"/>}</article>
  </AdminMockPage>;
}

function MerchantSettlementMock() {
  // TODO: settlements와 create_merchant_settlement RPC 연동으로 교체합니다.
  const rows = [['가온테크', 2400000, 240000, 2640000, '입금대기'], ['모아산업', 1350000, 135000, 1485000, '입금완료'], ['새봄복지관', 1120000, 112000, 1232000, '연체']];
  const totals = rows.reduce((sum, row) => sum.map((value, index) => value + row[index + 1]), [0, 0, 0]);
  return <AdminMockPage title="업체별 정산" description="업체별 공급가액과 미정산 잔액을 집계합니다.">
    <section className="grid mock-kpi-grid"><article className="card"><span>이번달 누적</span><strong className="money">18,400,000원</strong></article><article className="card"><span>미정산 잔액</span><strong className="money">5,357,000원</strong></article><article className="card"><span>발행 대기</span><strong className="money">3건</strong></article><article className="card"><span>발행 기한</span><strong className="money">D-16</strong></article></section>
    <article className="panel"><div className="table-wrap"><table><thead><tr><th>업체명</th><th className="money">공급가액</th><th className="money">부가세</th><th className="money">합계</th><th>상태</th></tr></thead><tbody>{rows.map((row) => <tr key={row[0]}><td><strong>{row[0]}</strong></td><td className="money">{krw(row[1])}</td><td className="money">{krw(row[2])}</td><td className="money">{krw(row[3])}</td><td><span className={`settlement-status ${row[4]}`}>{row[4]}</span></td></tr>)}<tr className="mock-total-row"><td>합계</td>{totals.map((value) => <td className="money" key={value}>{krw(value)}</td>)}<td>3개 업체</td></tr></tbody></table></div></article>
  </AdminMockPage>;
}
function MerchantTaxInvoiceMock() {
  // TODO: 팝빌 registIssue API 연동은 별도 단계에서 구현합니다.
  const [items, setItems] = useSettlementV2Rows();
  const [notice, setNotice] = useState('');
  const [issueError, setIssueError] = useState('');
  const issue = (id) => {
    const now = new Date().toISOString();
    const source = items.find((item) => item.id === id);
    const changed = transitionSettlementMockRow(source, 'merchant_issue', now);
    if (!changed) {
      setNotice('');
      setIssueError('현재 상태에서는 선택한 세금계산서를 발행 완료로 변경할 수 없습니다.');
      return;
    }
    setItems((current) => current.map((item) => item.id === id ? changed : item));
    setIssueError('');
    setNotice('선택한 행을 로컬 목업 발행 완료 상태로 변경했습니다. 외부 전송은 실행하지 않았습니다.');
  };
  const issueAll = () => {
    const now = new Date().toISOString();
    const next = items.map((item) => transitionSettlementMockRow(item, 'merchant_issue', now) ?? item);
    if (!next.some((item, index) => item !== items[index])) {
      setNotice('');
      setIssueError('현재 발행 가능한 세금계산서가 없습니다.');
      return;
    }
    setItems(next);
    setIssueError('');
    setNotice('법적 목업 전이 조건을 충족한 행만 발행 완료 상태로 변경했습니다. 외부 전송은 실행하지 않았습니다.');
  };
  return <AdminMockPage title="세금계산서" description="월 합계 세금계산서 발행 대상을 검토합니다." showHeader={false} className="merchant-regular-weight merchant-open-table">
    <div className="alert warning settlement-mock-notice" role="status">버전 관리되는 정산 로컬 목업 상태입니다. 실제 세금계산서 발행 또는 국세청 전송이 아닙니다.</div>
    {issueError && <div className="alert error" role="alert">{issueError}</div>}
    {notice && <div className="alert success" role="status" aria-live="polite">{notice}</div>}
    <div className="mock-page-actions"><button type="button" className="primary" disabled={!items.some(canMerchantIssue)} onClick={issueAll}>발행 가능 건 일괄 시뮬레이션</button></div>
    <article className="panel"><div className="table-wrap"><table><thead><tr><th>정산월</th><th>업체명</th><th className="money">공급가액</th><th className="money">부가세</th><th>상태</th><th>처리</th></tr></thead><tbody>{items.map((item) => { const legal = canMerchantIssue(item); return <tr key={item.id}><td>{item.period_start.slice(0, 7)} <small className="mock-row-label">목업</small></td><td><strong>{item.recipient.name}</strong></td><td className="money">{krw(item.supply_amount)}</td><td className="money">{krw(item.vat_amount)}</td><td><SettlementV2Status type="invoice" value={item.tax_invoice_status}/></td><td>{legal ? <button type="button" className="ghost" onClick={() => issue(item.id)}>발행 시뮬레이션</button> : <span className="panel-note">처리 불가</span>}</td></tr>; })}</tbody></table></div></article>
  </AdminMockPage>;
}
function MerchantPrepurchaseMock() {
  // TODO: voucher 배치 테이블 존재를 확인한 뒤 실제 잔량 조회로 교체합니다.
  const batches = [{ company: '모아산업', bought: '2026.07.01', quantity: 500, used: 382, price: 8000, expires: '2026.12.31' }, { company: '가온테크', bought: '2026.06.15', quantity: 300, used: 214, price: 8500, expires: '2026.11.30' }, { company: '한결디자인', bought: '2026.07.20', quantity: 120, used: 28, price: 9000, expires: '2027.01.19' }];
  return <AdminMockPage title="선구매 관리" description="선구매 배치 잔량과 미사용 부채를 확인합니다." showHeader={false} className="merchant-regular-weight">
    <section className="grid mock-kpi-grid three"><article className="card"><span>누적 판매</span><strong className="money">920매</strong></article><article className="card"><span>사용 완료</span><strong className="money">624매</strong></article><article className="card warning-card"><span>미사용 · 부채</span><strong className="money">296매 · 2,503,000원</strong></article></section>
    <article className="panel"><div className="panel-title"><div><h3>배치별 현황</h3><p className="panel-note">미사용 잔량은 식당의 이행 의무인 부채로 표시합니다.</p></div></div><div className="mock-batch-list">{batches.map((batch) => { const remain = batch.quantity - batch.used; return <article className="card" key={`${batch.company}-${batch.bought}`}><div className="mock-batch-head"><strong>{batch.company}</strong><span className="badge">잔여 {remain}매</span></div><dl><div><dt>구매일</dt><dd>{batch.bought}</dd></div><div><dt>구매수량</dt><dd className="money">{batch.quantity}매</dd></div><div><dt>단가</dt><dd className="money">{krw(batch.price)}</dd></div><div><dt>사용량</dt><dd className="money">{batch.used}매</dd></div><div><dt>유효기간</dt><dd>{batch.expires}</dd></div><div><dt>미사용 부채</dt><dd className="money">{krw(remain * batch.price)}</dd></div></dl></article>; })}</div></article>
  </AdminMockPage>;
}
function MerchantCompanyListScreen({ items, onDetail }) {
  return <AdminMockPage title={null} description="연결 업체의 회사정보와 계약설정을 확인합니다." preview={false} className="company-list-page merchant-regular-weight merchant-open-table">
    <article className="panel">{items.length === 0 ? <p className="empty-state">연결된 업체가 없어요.</p> : <div className="table-wrap"><table><thead><tr><th>업체명</th><th>사업자등록번호</th><th>계약 유형</th><th>담당자 이메일</th><th>연락처</th><th>관리</th></tr></thead><tbody>{items.map((item) => {
      const company = item.company ?? {};
      const subsidy = item.contract?.subsidy_enabled;
      return <tr key={item.id}><td><strong>{company.name ?? '-'}</strong></td><td>{company.biz_reg_no ?? '-'}</td><td><span className={`payment-type-badge ${subsidy ? 'subsidized' : 'ledger'}`}>{subsidy ? '보조금' : '후불'}</span></td><td>{company.contact_email ?? item.invite?.email ?? '-'}</td><td>{company.contact_phone ?? '-'}</td><td><button type="button" className="ghost" onClick={() => onDetail(item)}>상세</button></td></tr>;
    })}</tbody></table></div>}</article>
  </AdminMockPage>;
}
function MerchantProductTaxPanel({ token }) {
  const empty = { name: '', price: '', tax_type: 'unclassified' };
  const [items, setItems] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [form, setForm] = useState(empty);
  const [busyId, setBusyId] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const requestGeneration = useRef(0);
  const sessionGeneration = useRef(0);
  const identityRef = useRef(token);
  const mutationControllers = useRef(new Set());
  identityRef.current = token;
  const current = (capture) => generationIsCurrent(capture, sessionGeneration.current, identityRef.current);
  function mutationCapture() {
    const controller = new AbortController();
    mutationControllers.current.add(controller);
    return { controller, capture: captureGeneration(sessionGeneration.current, token, controller.signal) };
  }

  async function loadProducts(signal) {
    const generation = ++requestGeneration.current;
    const capture = captureGeneration(sessionGeneration.current, token, signal);
    setError(''); setNotice(''); setItems(null); setDrafts({});
    try {
      const data = await apiFetch('/admin/merchant/products', token, { signal });
      if (!current(capture) || generation !== requestGeneration.current) return;
      const products = data?.items ?? [];
      setItems(products);
      setDrafts(Object.fromEntries(products.map((item) => [item.id, item.tax_type ?? 'unclassified'])));
    } catch (loadError) {
      if (!current(capture) || loadError.name === 'AbortError' || generation !== requestGeneration.current) return;
      setError(loadError.message); setItems([]);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    loadProducts(controller.signal);
    return () => {
      controller.abort(); requestGeneration.current += 1; sessionGeneration.current += 1;
      mutationControllers.current.forEach((item) => item.abort()); mutationControllers.current.clear();
    };
  }, [token]);

  async function createProduct(event) {
    event.preventDefault();
    const { controller, capture } = mutationCapture();
    setBusyId('create'); setError(''); setNotice('');
    try {
      await apiFetch('/admin/merchant/products', token, {
        method: 'POST',
        body: JSON.stringify({ name: form.name.trim(), price: Number(form.price), tax_type: form.tax_type }),
        signal: controller.signal,
      });
      if (!current(capture)) return;
      setForm(empty);
      setNotice('상품을 등록했어요. 과세 유형에 따라 결제 가능 여부가 즉시 반영됩니다.');
      await loadProducts(controller.signal);
    } catch (saveError) {
      if (current(capture) && saveError.name !== 'AbortError') setError(saveError.message);
    } finally {
      mutationControllers.current.delete(controller); if (current(capture)) setBusyId('');
    }
  }

  async function updateTaxType(item) {
    const taxType = drafts[item.id] ?? 'unclassified';
    const { controller, capture } = mutationCapture();
    setBusyId(item.id); setError(''); setNotice('');
    try {
      const updated = await apiFetch(`/admin/merchant/products/${item.id}`, token, {
        method: 'PATCH', body: JSON.stringify({ tax_type: taxType }), signal: controller.signal,
      });
      if (!current(capture)) return;
      setItems((rows) => rows.map((row) => row.id === item.id ? { ...row, ...updated, tax_type: taxType } : row));
      setNotice(`${item.name} 상품의 과세 유형을 저장했어요.`);
    } catch (saveError) {
      if (current(capture) && saveError.name !== 'AbortError') setError(saveError.message);
    } finally {
      mutationControllers.current.delete(controller); if (current(capture)) setBusyId('');
    }
  }

  const blocked = (items ?? []).filter((item) => (item.tax_type ?? 'unclassified') === 'unclassified').length;
  return <section className="panel merchant-product-tax-panel" aria-labelledby="merchant-product-tax-title">
    <div className="panel-title"><div><h3 id="merchant-product-tax-title">일반 상품 과세 유형</h3><p className="panel-note">직접 결제 상품은 과세 또는 면세로 분류해야 결제할 수 있습니다.</p></div><span className="badge">{items?.length ?? 0}개</span></div>
    {error && <div className="alert error" role="alert">{error} <button type="button" className="ghost" onClick={() => loadProducts()} disabled={!!busyId}>다시 시도</button></div>}
    {notice && <div className="alert success" role="status">{notice}</div>}
    {blocked > 0 && <div className="alert warning" role="alert">미분류 상품 {blocked}개는 결제가 차단됩니다. 과세 유형을 저장해 주세요.</div>}
    <form className="merchant-product-create-form" onSubmit={createProduct}>
      <label>상품명<input value={form.name} maxLength="120" onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} disabled={!!busyId} required/></label>
      <label>가격<input type="number" min="1" step="1" value={form.price} onChange={(event) => setForm((current) => ({ ...current, price: event.target.value }))} disabled={!!busyId} required/></label>
      <label>과세 유형<select value={form.tax_type} onChange={(event) => setForm((current) => ({ ...current, tax_type: event.target.value }))} disabled={!!busyId}><option value="unclassified">미분류(결제 차단)</option><option value="taxable">과세</option><option value="tax_free">면세</option></select></label>
      <button type="submit" className="primary" disabled={!!busyId}>{busyId === 'create' ? '등록 중...' : '상품 등록'}</button>
    </form>
    {items === null ? <p className="empty-state" role="status" aria-live="polite">상품을 불러오는 중...</p> : !error && items.length === 0 ? <p className="empty-state" role="status">등록된 일반 상품이 없습니다. 위 입력란에서 첫 상품을 등록해 주세요.</p> : <div className="merchant-product-tax-list">{items.map((item) => { const tax = taxTypeMeta(item.tax_type); return <article className="merchant-product-tax-row" key={item.id}>
      <div><strong>{item.name}</strong><span>{krw(item.price)}</span><span className={`tax-type-badge ${tax.tone}`}>{tax.label}</span></div>
      <label>과세 유형<select aria-label={`${item.name} 과세 유형`} value={drafts[item.id] ?? 'unclassified'} onChange={(event) => setDrafts((current) => ({ ...current, [item.id]: event.target.value }))} disabled={!!busyId}><option value="unclassified">미분류(결제 차단)</option><option value="taxable">과세</option><option value="tax_free">면세</option></select></label>
      <button type="button" className="ghost" onClick={() => updateTaxType(item)} disabled={!!busyId || drafts[item.id] === (item.tax_type ?? 'unclassified')}>{busyId === item.id ? '저장 중...' : '저장'}</button>
    </article>; })}</div>}
  </section>;
}

function LegacyTaxReviewPanel({ token }) {
  const pageSize = 50;
  const [items, setItems] = useState(null);
  const [error, setError] = useState('');
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState({ total: 0, has_more: false });
  const readGeneration = useRef(0);
  const sessionGeneration = useRef(0);
  const identityRef = useRef(token);
  identityRef.current = token;
  const current = (capture) => generationIsCurrent(capture, sessionGeneration.current, identityRef.current);

  async function loadReviews(signal, requestedOffset = offset) {
    const generation = ++readGeneration.current;
    const capture = captureGeneration(sessionGeneration.current, token, signal);
    setItems(null); setError('');
    try {
      const data = await apiFetch(`/admin/merchant/legacy-tax-reviews?limit=${pageSize}&offset=${requestedOffset}`, token, { signal });
      if (!current(capture) || generation !== readGeneration.current) return;
      setItems(data?.items ?? []);
      setPage({ total: Number(data?.total ?? 0), has_more: Boolean(data?.has_more) });
    } catch (loadError) {
      if (!current(capture) || loadError.name === 'AbortError' || generation !== readGeneration.current) return;
      setError(loadError.message); setItems([]); setPage({ total: 0, has_more: false });
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    loadReviews(controller.signal, offset);
    return () => { controller.abort(); readGeneration.current += 1; sessionGeneration.current += 1; };
  }, [token, offset]);
  useEffect(() => { setOffset(0); setItems(null); setPage({ total: 0, has_more: false }); setError(''); }, [token]);

  const pageNumber = Math.floor(offset / pageSize) + 1;
  const pageCount = Math.max(1, Math.ceil(page.total / pageSize));
  return <section className="panel merchant-product-tax-panel" aria-labelledby="legacy-tax-review-title">
    <div className="panel-title"><div><h3 id="legacy-tax-review-title">기존 결제 과세 검토</h3><p className="panel-note">읽기 전용 목록입니다. 동일한 결제 결과 알림이 재전송되면 서버가 상품·계약 분류를 검증해 원자적으로 완료합니다.</p></div><span className="badge">총 {page.total}건</span></div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {items === null ? <p className="empty-state" role="status">검토 목록을 불러오는 중...</p> : items.length === 0 ? <p className="empty-state" role="status">대기 중인 기존 결제가 없습니다.</p> : <div className="merchant-product-tax-list">{items.map((item) => <article className="merchant-product-tax-row" key={item.inbox_id}>
      <div><strong>{item.product_name || item.provider_order_id}</strong><span>{item.provider_order_id} · {krw(item.amount)} · {item.payment_method}</span><span>현재 상품·계약 분류: {taxTypeMeta(item.suggested_tax_type).label}</span></div>
    </article>)}</div>}
    <nav className="pagination-controls" aria-label="기존 결제 검토 페이지"><button type="button" className="ghost" disabled={offset === 0 || items === null} onClick={() => setOffset((value) => Math.max(0, value - pageSize))}>이전</button><span>{pageNumber} / {pageCount} 페이지</span><button type="button" className="ghost" disabled={!page.has_more || items === null} onClick={() => setOffset((value) => value + pageSize)}>다음</button></nav>
  </section>;
}

function LegacyVoucherTaxPanel({ token }) {
  const [items, setItems] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [busyId, setBusyId] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const readGeneration = useRef(0);
  const sessionGeneration = useRef(0);
  const identityRef = useRef(token);
  const mutationControllers = useRef(new Set());
  identityRef.current = token;
  const current = (capture) => generationIsCurrent(capture, sessionGeneration.current, identityRef.current);

  async function loadVouchers(signal) {
    const generation = ++readGeneration.current;
    const capture = captureGeneration(sessionGeneration.current, token, signal);
    setItems(null); setDrafts({}); setError(''); setNotice('');
    try {
      const data = await apiFetch('/admin/merchant/legacy-vouchers?limit=50&offset=0', token, { signal });
      if (!current(capture) || generation !== readGeneration.current) return;
      setItems(data?.items ?? []);
    } catch (loadError) {
      if (!current(capture) || loadError.name === 'AbortError' || generation !== readGeneration.current) return;
      setError(loadError.message); setItems([]);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    loadVouchers(controller.signal);
    return () => {
      controller.abort(); readGeneration.current += 1; sessionGeneration.current += 1;
      mutationControllers.current.forEach((item) => item.abort()); mutationControllers.current.clear();
    };
  }, [token]);

  async function classify(item) {
    const draft = drafts[item.id] ?? {};
    if (!['taxable', 'tax_free'].includes(draft.tax_type) || (draft.reason ?? '').trim().length < 3) {
      setNotice(''); setError('과세 또는 면세를 직접 선택하고 3자 이상의 분류 사유를 입력해 주세요.'); return;
    }
    const controller = new AbortController();
    mutationControllers.current.add(controller);
    const capture = captureGeneration(sessionGeneration.current, token, controller.signal);
    setBusyId(item.id); setError(''); setNotice('');
    try {
      const result = await apiFetch(`/admin/merchant/legacy-vouchers/${item.id}/classify`, token, {
        method: 'POST', body: JSON.stringify({ tax_type: draft.tax_type, reason: draft.reason.trim() }), signal: controller.signal,
      });
      if (!current(capture)) return;
      setItems((rows) => (rows ?? []).filter((row) => row.id !== item.id));
      setNotice(result?.duplicate ? '이미 같은 과세 유형으로 분류된 식권입니다.' : '기존 식권을 감사 기록과 함께 분류했습니다.');
    } catch (classifyError) {
      if (current(capture) && classifyError.name !== 'AbortError') setError(classifyError.message);
    } finally {
      mutationControllers.current.delete(controller); if (current(capture)) setBusyId('');
    }
  }

  return <section className="panel merchant-product-tax-panel" aria-labelledby="legacy-voucher-tax-title">
    <div className="panel-title"><div><h3 id="legacy-voucher-tax-title">기존 활성 식권 과세 검토</h3><p className="panel-note">사용 전인 미분류 식권만 표시합니다. 고객 개인정보는 표시하지 않습니다.</p></div><span className="badge">{items?.length ?? 0}건</span></div>
    {error && <div className="alert error" role="alert">{error} <button type="button" className="ghost" onClick={() => loadVouchers()} disabled={!!busyId}>다시 시도</button></div>}
    {notice && <div className="alert success" role="status" aria-live="polite">{notice}</div>}
    {items === null ? <p className="empty-state" role="status">기존 식권을 불러오는 중...</p> : items.length === 0 ? <p className="empty-state" role="status">검토할 기존 활성 식권이 없습니다.</p> : <div className="merchant-product-tax-list">{items.map((item) => <article className="merchant-product-tax-row" key={item.id}>
      <div><strong>식권 {String(item.id).slice(0, 8)}</strong><span>{item.purchase_price_won == null ? '정확한 구매가 없음' : krw(item.purchase_price_won)} · {String(item.purchased_at ?? '').slice(0, 10)}</span></div>
      <label>확정 과세 유형<select aria-label={`식권 ${item.id} 과세 유형`} value={drafts[item.id]?.tax_type ?? ''} onChange={(event) => setDrafts((current) => ({ ...current, [item.id]: { ...current[item.id], tax_type: event.target.value } }))} disabled={!!busyId}><option value="">직접 선택</option><option value="taxable">과세</option><option value="tax_free">면세</option></select></label>
      <label>분류 사유<input aria-label={`식권 ${item.id} 분류 사유`} minLength="3" maxLength="1000" value={drafts[item.id]?.reason ?? ''} onChange={(event) => setDrafts((current) => ({ ...current, [item.id]: { ...current[item.id], reason: event.target.value } }))} disabled={!!busyId}/></label>
      <button type="button" className="primary" onClick={() => classify(item)} disabled={!!busyId}>{busyId === item.id ? '분류 중...' : '분류 확정'}</button>
    </article>)}</div>}
  </section>;
}

function MerchantSupplierInfoScreen({ merchant, busy, onSave, onSettings, token }) {
  const emptyForm = { biz_reg_no: '', name: '', representative_name: '', address: '', business_type: '', business_item: '', tax_invoice_email: '' };
  const valuesFrom = (item) => Object.fromEntries(Object.keys(emptyForm).map((key) => [key, item?.[key] ?? '']));
  const [values, setValues] = useState(() => valuesFrom(merchant));
  const [draft, setDraft] = useState(() => valuesFrom(merchant));
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    const next = valuesFrom(merchant);
    setValues(next);
    setDraft(next);
    setEditing(false);
  }, [merchant]);

  const field = (key) => (event) => setDraft((current) => ({ ...current, [key]: event.target.value }));
  const beginEdit = () => { setDraft(values); setEditing(true); };
  const cancelEdit = () => { setDraft(values); setEditing(false); };
  async function save(event) {
    event.preventDefault();
    const updated = await onSave(draft);
    if (!updated) return;
    const next = valuesFrom(updated);
    setValues(next);
    setDraft(next);
    setEditing(false);
  }

  return <AdminMockPage
    title={null}
    description="세금계산서에 사용할 식당 사업자정보를 관리합니다."
    className="supplier-info-page"
    preview={false}
    actions={<button type="button" className="account-settings-button supplier-settings-button" onClick={onSettings} aria-label="관리자 정보 설정" title="관리자 정보 설정"><Settings size={20}/></button>}
  >
    <form className="panel supplier-info-card" onSubmit={save}>
      <div className="panel-title supplier-info-card-title">
        <div><h3>사업자 정보</h3><p className="panel-note">팝빌 발행 시 자동 사용될 정보입니다.</p></div>
        <div className="supplier-edit-actions">
          <button type="button" className="ghost supplier-capsule-button" onClick={beginEdit} disabled={editing || busy}>수정</button>
          <button type="button" className="ghost supplier-capsule-button" onClick={cancelEdit} disabled={!editing || busy}>취소</button>
          <button type="submit" className="primary supplier-capsule-button" disabled={!editing || busy}>{busy ? '저장 중' : '저장'}</button>
        </div>
      </div>
      <div className="supplier-info-fields">
        <label>사업자등록번호<input value={draft.biz_reg_no} onChange={field('biz_reg_no')} disabled={!editing} required /></label>
        <label>상호<input value={draft.name} onChange={field('name')} disabled={!editing} required /></label>
        <label>대표자<input value={draft.representative_name} onChange={field('representative_name')} disabled={!editing} /></label>
        <label>주소<input value={draft.address} onChange={field('address')} disabled={!editing} /></label>
        <label>업태<input value={draft.business_type} onChange={field('business_type')} disabled={!editing} /></label>
        <label>종목<input value={draft.business_item} onChange={field('business_item')} disabled={!editing} /></label>
        <label className="wide">세금계산서 담당 이메일<input type="email" value={draft.tax_invoice_email} onChange={field('tax_invoice_email')} disabled={!editing} /></label>
      </div>
    </form>
    <LegacyTaxReviewPanel key={`legacy-payments-${token}`} token={token}/>
    <LegacyVoucherTaxPanel key={`legacy-vouchers-${token}`} token={token}/>
    <MerchantProductTaxPanel key={`merchant-products-${token}`} token={token}/>
  </AdminMockPage>;
}

function MerchantMockScreen({ section, companyItems, onCompanyDetail, merchant, busy, onSaveSupplier, onSettings, token }) {
  if (section === 'company-list') return <MerchantCompanyListScreen items={companyItems} onDetail={onCompanyDetail} />;
  if (section === 'supplier-info') return <MerchantSupplierInfoScreen merchant={merchant} busy={busy} onSave={onSaveSupplier} onSettings={onSettings} token={token} />;
  const screens = {
    'settlements-by-company': MerchantSettlementV2Mock,
    'settlement-evidence': SettlementEvidenceV2Mock,
    'tax-invoices': MerchantTaxInvoiceMock,
    'prepurchase': MerchantPrepurchaseMock,
  };
  const Screen = screens[section];
  return Screen ? <Screen /> : null;
}

function CompanyDashboardMock() {
  // TODO: company_id 강제 스코프 대시보드 API로 교체합니다.
  return <AdminMockPage title={null} description="이번달 사용액과 미납·세금계산서 현황을 확인합니다." preview={false} className="merchant-regular-weight merchant-open-table">
    <section className="grid merchant-kpi-grid"><article className="card merchant-kpi-card"><CreditCard size={22}/><span>이번달 사용액</span><strong className="money">4,812,000원</strong></article><article className="card merchant-kpi-card warning-card"><AlertTriangle size={22}/><span>미납액</span><strong className="money">1,232,000원</strong></article><article className="card merchant-kpi-card"><Users size={22}/><span>등록 사원</span><strong className="money">84명</strong></article><article className="card merchant-kpi-card mock-download-card"><FileText size={22}/><span>최근 세금계산서</span><strong>2026년 6월</strong><button type="button" className="ghost"><Download size={16}/> 다운로드</button></article></section>
    <article className="panel"><div className="panel-title"><div><h3>이번달 이용 요약</h3><p className="panel-note">우리 회사 사원의 식대 이용 현황입니다.</p></div><span className="badge">7월</span></div><div className="mock-summary-strip"><div><span>이용 사원</span><strong className="money">76명</strong></div><div><span>총 끼수</span><strong className="money">542끼</strong></div><div><span>전월 대비</span><strong className="money">+6.8%</strong></div></div></article>
  </AdminMockPage>;
}
function CompanyMonthlyUsageMock() {
  // TODO: company_id 스코프 일별 집계 API로 교체합니다.
  const rows = [['07.01', 48, 52, 468000], ['07.02', 51, 56, 504000], ['07.03', 46, 49, 441000], ['07.04', 54, 61, 549000], ['07.05', 18, 19, 171000], ['07.06', 12, 13, 117000], ['07.07', 52, 57, 513000]];
  const total = rows.reduce((sum, row) => [sum[0] + row[2], sum[1] + row[3]], [0, 0]);
  return <AdminMockPage title={null} description="우리 회사의 일별 식대 이용 현황을 확인합니다." preview={false} className="merchant-regular-weight merchant-open-table">
    <article className="panel"><div className="panel-title"><div><h3>2026년 7월</h3><p className="panel-note">일별 이용 사원수·끼수·금액</p></div><span className="badge">목업 데이터</span></div><div className="table-wrap"><table><thead><tr><th>날짜</th><th className="money">이용 사원수</th><th className="money">끼수</th><th className="money">금액</th></tr></thead><tbody>{rows.map((row) => <tr key={row[0]}><td>{row[0]}</td><td className="money">{row[1]}명</td><td className="money">{row[2]}끼</td><td className="money">{krw(row[3])}</td></tr>)}<tr className="mock-total-row"><td>합계</td><td className="money">-</td><td className="money">{total[0]}끼</td><td className="money">{krw(total[1])}</td></tr></tbody></table></div></article>
  </AdminMockPage>;
}
function CompanyEmployeeUsageMock() {
  // TODO: company_id 스코프 사원별 사용 집계 API로 교체합니다.
  const rows = [['김민지', '개발팀', 18, 162000, 0], ['박준호', '기획팀', 17, 153000, 18000], ['이서연', '디자인팀', 16, 144000, 0], ['정우진', '영업팀', 15, 135000, 15000], ['최하늘', '개발팀', 14, 126000, 0]];
  return <AdminMockPage title={null} description="사원별 끼수와 사용액을 비교합니다." preview={false} className="merchant-regular-weight merchant-open-table">
    <article className="panel"><div className="table-wrap"><table><thead><tr><th>사원명</th><th>부서</th><th className="money">끼수</th><th className="money">사용액</th><th className="money">자부담액</th></tr></thead><tbody>{rows.map((row) => <tr key={row[0]}><td><strong>{row[0]}</strong></td><td>{row[1]}</td><td className="money">{row[2]}끼</td><td className="money">{krw(row[3])}</td><td className="money">{row[4] ? krw(row[4]) : '-'}</td></tr>)}</tbody></table></div></article>
  </AdminMockPage>;
}
function CompanyBillingMock() {
  // TODO: company_id 스코프 settlements 조회로 교체합니다.
  const rows = [['2026년 7월', 4374545, 437455, 4812000, '입금대기'], ['2026년 6월', 4120000, 412000, 4532000, '입금완료'], ['2026년 5월', 3981818, 398182, 4380000, '입금완료'], ['2026년 4월', 4210909, 421091, 4632000, '입금완료']];
  return <AdminMockPage title="청구 내역" description="월별 청구 금액과 납부 상태를 확인합니다." preview={false} className="merchant-regular-weight merchant-open-table">
    <article className="panel"><div className="table-wrap"><table><thead><tr><th>청구월</th><th className="money">공급가액</th><th className="money">부가세</th><th className="money">합계</th><th>상태</th><th>명세서</th></tr></thead><tbody>{rows.map((row) => <tr key={row[0]}><td><strong>{row[0]}</strong></td><td className="money">{krw(row[1])}</td><td className="money">{krw(row[2])}</td><td className="money">{krw(row[3])}</td><td><span className={`settlement-status ${row[4]}`}>{row[4]}</span></td><td><button type="button" className="ghost"><FileText size={15}/> 명세서</button></td></tr>)}</tbody></table></div></article>
  </AdminMockPage>;
}
function CompanyTaxInvoiceMock({ company }) {
  // TODO: company_id 스코프 수신 세금계산서 조회로 교체합니다.
  const [allRows] = useSettlementV2Rows();
  const [notice, setNotice] = useState('');
  const rows = allRows.filter((row) => row.company_id === PILOT_COMPANY_SCOPE_ID && row.tax_invoice_status !== 'not_requested');
  const displayName = company?.name || SETTLEMENT_V2_PARTIES.gaon.name;
  return <AdminMockPage title={null} description="" showHeader={false} preview={false} className="merchant-regular-weight merchant-open-table">
    <div className="alert warning settlement-mock-notice" role="status">{displayName}에 표시하는 수신 전용 로컬 목업입니다. 실제 승인번호·문서 URL·PDF 파일은 제공하지 않습니다.</div>
    {notice && <div className="alert success" role="status" aria-live="polite">{notice}</div>}
    <article className="panel"><div className="panel-title employee-panel-actions"><span className="badge">수신 전용 · 목업</span></div><div className="table-wrap"><table><thead><tr><th>정산월</th><th>작성일자</th><th className="money">합계</th><th>세금계산서 상태</th><th>발행일시</th><th>승인번호</th><th>문서</th></tr></thead><tbody>{rows.map((row) => { const documentReady = ['issued', 'nts_sending', 'nts_accepted'].includes(row.tax_invoice_status); return <tr key={row.id}><td><strong>{row.period_start.slice(0, 7)}</strong> <small className="mock-row-label">목업</small></td><td>{row.invoice?.written_at || '미확정'}</td><td className="money">{krw(row.total_amount)}</td><td><SettlementV2Status type="invoice" value={row.tax_invoice_status}/></td><td>{formatKoreanTimestamp(row.invoice?.issued_at)}</td><td>{row.invoice?.approval_number || '미수신 (로컬 목업)'}</td><td>{documentReady ? <div className="row-actions"><button type="button" className="ghost settlement-v2-inline-action" onClick={() => setNotice('실제 문서 URL이 없는 로컬 목업이므로 문서를 열지 않았습니다.')}><FileText size={14}/> 보기</button><button type="button" className="ghost settlement-v2-inline-action" onClick={() => setNotice('실제 PDF 파일이 없는 로컬 목업이므로 다운로드하지 않았습니다.')}><Download size={14}/> PDF</button></div> : <span className="panel-note">{TAX_INVOICE_STATUS[row.tax_invoice_status]} · 문서 없음</span>}</td></tr>; })}</tbody></table></div>{rows.length === 0 && <SettlementV2Empty />}</article>
  </AdminMockPage>;
}
function CompanyEmployeeListMock() {
  const items = [{ name: '김민지', department: '개발팀', no: 'A-1024', status: '사용중' }, { name: '박준호', department: '기획팀', no: 'A-1031', status: '사용중' }, { name: '이서연', department: '디자인팀', no: 'A-1042', status: '초대대기' }, { name: '정우진', department: '영업팀', no: 'A-1057', status: '사용중' }];
  const [notice, setNotice] = useState('');
  // TODO: 기존 사원관리 핸들러 재사용 여부 확인 후 company_id 스코프 API로 교체합니다.
  return <AdminMockPage title="사원 목록" description="우리 회사 사원 등록 현황을 확인합니다." preview={false} className="merchant-regular-weight merchant-open-table">
    {notice && <div className="alert warning">{notice}</div>}
    <article className="panel"><div className="panel-title"><div><h3>등록 사원</h3><p className="panel-note">기존 사원 관리 화면과 비교하기 위한 신규 목업입니다.</p></div><button type="button" className="primary">+ 사원 등록</button></div><div className="table-wrap"><table><thead><tr><th>이름</th><th>부서</th><th>사번</th><th>상태</th><th>관리</th></tr></thead><tbody>{items.map((item) => <tr key={item.no}><td><strong>{item.name}</strong></td><td>{item.department}</td><td>{item.no}</td><td><span className="badge">{item.status}</span></td><td><button type="button" className="ghost" onClick={() => setNotice(`${item.name} 삭제는 목업 화면에서 실행되지 않습니다.`)}>삭제 (목업)</button></td></tr>)}</tbody></table></div></article>
  </AdminMockPage>;
}
function CompanyInfoScreen({ company, busy, onSave, onSettings }) {
  const emptyForm = { name: '', biz_reg_no: '', representative_name: '', business_type: '', business_item: '', address: '', contact_name: '', contact_phone: '', tax_invoice_email: '' };
  const [form, setForm] = useState(emptyForm);
  useEffect(() => {
    setForm(Object.fromEntries(Object.keys(emptyForm).map((key) => [key, company?.[key] ?? (key === 'tax_invoice_email' ? company?.contact_email ?? '' : '')])));
  }, [company]);
  const field = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }));
  return <AdminMockPage title={null} description="업체 상세에 표시할 사업자정보와 세금계산서 수신 정보를 관리합니다." actions={<button type="button" className="account-settings-button" onClick={onSettings} aria-label="관리자 정보 설정" title="관리자 정보 설정"><Settings size={20}/></button>} preview={false} className="merchant-regular-weight">
    <form className="panel mock-business-form" onSubmit={(event) => { event.preventDefault(); onSave(form); }}><label>사업자등록번호<input value={form.biz_reg_no} onChange={field('biz_reg_no')} required /></label><label>상호<input value={form.name} onChange={field('name')} required /></label><label>대표자<input value={form.representative_name} onChange={field('representative_name')} /></label><label>업태<input value={form.business_type} onChange={field('business_type')} /></label><label>종목<input value={form.business_item} onChange={field('business_item')} /></label><label className="wide">사업장주소<input value={form.address} onChange={field('address')} /></label><label>담당자명<input value={form.contact_name} onChange={field('contact_name')} /></label><label>연락처<input value={form.contact_phone} onChange={field('contact_phone')} /></label><label className="wide">세금계산서 수신 이메일<input type="email" value={form.tax_invoice_email} onChange={field('tax_invoice_email')} /></label><div className="row-actions wide"><button type="button" className="ghost" onClick={() => setForm(Object.fromEntries(Object.keys(emptyForm).map((key) => [key, company?.[key] ?? (key === 'tax_invoice_email' ? company?.contact_email ?? '' : '')])))}>취소</button><button className="primary" disabled={busy}>회사 정보 저장</button></div></form>
  </AdminMockPage>;
}

function CompanyMockScreen({ section, company, busy, onSaveCompany, onSettings, onCompanyInfo }) {
  if (section === 'company-info') return <CompanyInfoScreen company={company} busy={busy} onSave={onSaveCompany} onSettings={onSettings} />;
  if (section === 'company-billing') return <CompanySettlementV2Mock company={company} onCompanyInfo={onCompanyInfo} />;
  if (section === 'company-tax-invoices') return <CompanyTaxInvoiceMock company={company} />;
  const screens = {
    'company-dashboard': CompanyDashboardMock,
    'monthly-usage': CompanyMonthlyUsageMock,
    'employee-usage': CompanyEmployeeUsageMock,
    'company-employee-list': CompanyEmployeeListMock,
  };
  const Screen = screens[section];
  return Screen ? <Screen /> : null;
}

function Dashboard({ session, onLogout }) {
  const token = session.access_token;
  const [me, setMe] = useState(null);
  const [accountSettingsOpen, setAccountSettingsOpen] = useState(false);
  const [accountSettingsForm, setAccountSettingsForm] = useState({ display_name: '', merchant_name: '', password: '', password_confirm: '' });
  const [requests, setRequests] = useState([]);
  const [settlements, setSettlements] = useState(null);
  const [voucherProducts, setVoucherProducts] = useState([]);
  const [voucherProductsMigrationRequired, setVoucherProductsMigrationRequired] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [notificationsMigrationRequired, setNotificationsMigrationRequired] = useState(false);
  const [paymentAlertDay, setPaymentAlertDay] = useState(todayInput());
  const [unreadPaymentCount, setUnreadPaymentCount] = useState(0);
  const notifiedPaymentIdsRef = useRef(new Set());
  const paymentFeedReadyRef = useRef(false);
  const merchantSectionRef = useRef('main');
  const transactionRefreshVersionRef = useRef(0);
  const [cropRequest, setCropRequest] = useState(null);
  const [dailyMenu, setDailyMenu] = useState(null);
  const [dailyMenuForm, setDailyMenuForm] = useState({ service_date: todayInput(), title: '오늘 뷔페 메뉴', menu_text: '', image_url: '' });
  const [merchantCompanies, setMerchantCompanies] = useState(null);
  const [merchantSection, setMerchantSection] = useState('main');
  const [companyManagementTab, setCompanyManagementTab] = useState('company-list');
  const [restaurantManagementTab, setRestaurantManagementTab] = useState('daily-menu');
  const merchantContentSection = merchantSection === 'companies'
    ? companyManagementTab
    : merchantSection === 'restaurant-management' ? restaurantManagementTab : merchantSection;
  const [companySection, setCompanySection] = useState('company-dashboard');
  const [companyUsageTab, setCompanyUsageTab] = useState('employee-usage');
  const companyContentSection = companySection === 'company-usage' ? companyUsageTab : companySection;
  const [refundOpen, setRefundOpen] = useState(false);
  const [paymentHistoryRefreshKey, setPaymentHistoryRefreshKey] = useState(0);
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
  const [contractModal, setContractModal] = useState(null);
  const [contractForm, setContractForm] = useState({ settlement_cycle: 'month_end', settlement_day: '25', unit_price: '', subsidy_enabled: false, company_subsidy_amount: '0', restaurant_subsidy_amount: '0', tax_type: 'unclassified' });
  const [busy, setBusy] = useState(false);
  const [dashboardBooting, setDashboardBooting] = useState(true);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const isMerchantAdmin = me?.role === 'merchant_admin';
  const isPlatformAdmin = me?.role === 'platform_admin';
  const isCompanyAdmin = me?.role === 'company_admin';
  const showCompanyLegacy = isCompanyAdmin && companySection === 'legacy-employees';
  const merchantRequest = useMemo(() => (path, options) => apiFetch(path, token, options), [token]);
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
    const audio = getPaymentSuccessAudio();
    if (!audio) return;
    audio.pause();
    audio.currentTime = 0;
    audio.volume = 1;
    audio.play().catch(() => {});
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
    setAccountSettingsForm({ display_name: me?.display_name ?? '', merchant_name: merchantQr?.merchant?.name ?? '', password: '', password_confirm: '' });
    setError('');
    setAccountSettingsOpen(true);
  }

  async function saveAccountSettings(event) {
    event.preventDefault();
    const displayName = accountSettingsForm.display_name.trim();
    const merchantName = accountSettingsForm.merchant_name.trim();
    const password = accountSettingsForm.password;
    if (!displayName) { setError('관리자 이름을 입력해 주세요.'); return; }
    if (isMerchantAdmin && !merchantName) { setError('식당 이름을 입력해 주세요.'); return; }
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
      if (isMerchantAdmin && merchantName !== merchantQr?.merchant?.name) {
        const updatedMerchant = await apiFetch('/admin/merchant/profile', token, {
          method: 'PATCH', body: JSON.stringify({ name: merchantName }),
        });
        setMerchantQr((current) => ({ ...current, merchant: { ...current?.merchant, ...updatedMerchant } }));
      }
      if (password) {
        const { error: passwordError } = await supabase.auth.updateUser({ password });
        if (passwordError) throw passwordError;
      }
      setAccountSettingsOpen(false);
    } catch (settingsError) { setError(settingsError.message); }
    finally { setBusy(false); }
  }

  async function saveMerchantSupplierProfile(form) {
    setBusy(true); setError(''); setMessage('');
    try {
      const updated = await apiFetch('/admin/merchant/profile', token, {
        method: 'PATCH', body: JSON.stringify(form),
      });
      setMerchantQr((current) => ({ ...current, merchant: { ...current?.merchant, ...updated } }));
      setMessage('공급자 정보를 저장했어요.');
      return updated;
    } catch (supplierError) {
      setError(supplierError.message);
      return null;
    } finally { setBusy(false); }
  }

  async function saveCompanyProfile(form) {
    setBusy(true); setError(''); setMessage('');
    try {
      const updated = await apiFetch('/me/company', token, {
        method: 'PATCH', body: JSON.stringify(form),
      });
      setMe((current) => ({ ...current, company: updated.company }));
      setMessage('회사 정보를 저장했어요. 업체 목록 상세에도 동일하게 표시됩니다.');
    } catch (companyError) { setError(companyError.message); }
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
    win.document.write(`<!doctype html><html><head><title>${merchantName} 결제 QR</title><style>body{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;padding:34px;background:#f3fbf4;color:#14351f}.sheet{max-width:520px;margin:0 auto;background:white;border:2px solid #cdebd5;border-radius:28px;padding:34px;text-align:center}.brand{font-size:18px;font-weight:900;color:#2fb865;letter-spacing:.08em}.title{font-size:32px;font-weight:1000;margin:14px 0 6px}.merchant{font-size:22px;font-weight:900;margin-bottom:22px}.qr{width:300px;height:300px;border:12px solid #eaf7ec;border-radius:24px}.help{font-size:17px;font-weight:800;line-height:1.55;color:#5c7a66}.url{word-break:break-all;font-size:12px;color:#5c7a66;margin-top:18px}@media print{body{background:white}.sheet{box-shadow:none;border-color:#14351f}}</style></head><body><section class="sheet"><div class="brand">GREENEATGO PAYMENT</div><div class="title">직원 결제 QR</div><div class="merchant">${merchantName}</div><img class="qr" src="${merchantQrImageUrl}"/><p class="help">직원 앱으로 스캔하면<br/>회사 계약 단가로 바로 결제됩니다.</p><p class="url">${merchantPayUrl}</p></section><script>window.onload=()=>setTimeout(()=>window.print(),500)</script></body></html>`);
    win.document.close();
  }
  const cards = useMemo(() => isPlatformAdmin ? [
    ['권한', '플랫폼 운영자', WalletCards, 'brown'],
    ['식당', platformMerchants ? `${platformMerchants.items.length}곳` : '조회 중', Coffee, 'green'],
  ] : isMerchantAdmin ? [
    ['오늘 매출', '842,000원', WalletCards, 'brown'],
    ['이번달 누적', '18,400,000원', BarChart3, 'orange'],
    ['미정산 잔액', '5,357,000원', CreditCard, 'green'],
    ['발행 대기 건수', '3건', FileText, 'orange'],
  ] : [
    ['가입 요청', `${requests.length}명`, Users, 'orange'],
    ['직원', employees ? `${employees.items.length}명` : '조회 중', WalletCards, 'brown'],
  ], [isPlatformAdmin, isMerchantAdmin, requests.length, platformMerchants, employees]);

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
        dailyMenuData = await apiFetch('/admin/daily-menu', token);
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
          notifiedPaymentIdsRef.current = new Set(merchantMealPaymentIds(transactionData));
          paymentFeedReadyRef.current = true;
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
    setContractForm(contractFormFromItem(item));
  }

  async function saveContract(event) {
    event.preventDefault();
    if (!contractModal) return;
    const unitPrice = Number(contractForm.unit_price);
    const companySubsidy = Number(contractForm.company_subsidy_amount);
    const restaurantSubsidy = Number(contractForm.restaurant_subsidy_amount);
    if (contractForm.subsidy_enabled && (!contractForm.unit_price || unitPrice <= 0)) { setError('보조금 계약은 0원보다 큰 단가가 필요해요.'); return; }
    if (subsidyContractInvalid(contractForm)) { setError('회사 부담액과 식당 부담액의 합계는 단가보다 작아야 해요.'); return; }
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
          tax_type: contractForm.tax_type,
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
    unlockPaymentAudio();
    window.addEventListener('pointerdown', unlockPaymentAudio, { once: true, capture: true });
    window.addEventListener('keydown', unlockPaymentAudio, { once: true, capture: true });
    return () => {
      window.removeEventListener('pointerdown', unlockPaymentAudio, { capture: true });
      window.removeEventListener('keydown', unlockPaymentAudio, { capture: true });
    };
  }, [isMerchantAdmin]);

  useEffect(() => {
    if (!isMerchantAdmin) return undefined;
    let stopped = false;
    let polling = false;
    const pollRecentPayments = async () => {
      if (stopped || polling || document.visibilityState === 'hidden') return;
      polling = true;
      try {
        const list = await apiFetch('/admin/merchant/transactions', token);
        if (stopped) return;
        const ids = merchantMealPaymentIds(list);
        if (!paymentFeedReadyRef.current) {
          notifiedPaymentIdsRef.current = new Set(ids);
          paymentFeedReadyRef.current = true;
        } else {
          const newIds = ids.filter((id) => !notifiedPaymentIdsRef.current.has(id));
          ids.forEach((id) => notifiedPaymentIdsRef.current.add(id));
          if (newIds.length > 0) {
            playPaymentChime();
            if (merchantSectionRef.current !== 'main') {
              setUnreadPaymentCount((count) => count + newIds.length);
            }
          }
        }
        setTransactions(list);
      } catch {
        // Realtime이 정상 동작하는 동안 폴링 실패는 화면을 방해하지 않는다.
      } finally {
        polling = false;
      }
    };
    const timer = window.setInterval(pollRecentPayments, 5000);
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') pollRecentPayments();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      stopped = true;
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [isMerchantAdmin, token]);

  useEffect(() => {
    const merchantId = merchantQr?.merchant?.id;
    if (!supabase || !isMerchantAdmin || !merchantId) return undefined;
    const channel = supabase.channel(`merchant-payments-${merchantId}`)
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'meal_transactions', filter: `merchant_id=eq.${merchantId}` }, async (event) => {
        if (!['refund', 'cancel'].includes(event.new.kind)) {
          const eventId = String(event.new.id);
          if (!notifiedPaymentIdsRef.current.has(eventId)) {
            notifiedPaymentIdsRef.current.add(eventId);
            playPaymentChime();
            if (merchantSectionRef.current !== 'main') setUnreadPaymentCount((count) => count + 1);
          }
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

  const merchantNavGroups = [
    [['main', '대시보드', Home], ['payment-history', '실시간 매출', CreditCard]],
    [['companies', '업체 관리', Building2], ['settlements-by-company', '업체별 정산', WalletCards], ['settlement-evidence', '증빙 내역', FileSpreadsheet], ['tax-invoices', '세금계산서 발행', FileText], ['prepurchase', '선구매 관리', Package]],
    [['restaurant-management', '식당 관리', Coffee], ['supplier-info', '공급자 정보', Settings]],
  ];
  const companyManagementTabs = [
    ['company-list', '업체 목록'],
    ['companies', '업체 추가'],
  ];
  const restaurantManagementTabs = [
    ['daily-menu', '오늘 뷔페 메뉴'],
    ['vouchers', '판매 상품'],
    ['notifications', '알림'],
    ['announcements', '공지사항'],
    ['reviews', '리뷰'],
  ];
  const companyNavGroups = [
    [['company-dashboard', '대시보드', Home]],
    [['company-billing', '청구 내역', WalletCards], ['company-tax-invoices', '세금계산서', FileText], ['company-info', '회사 정보', Settings]],
    [['legacy-employees', '사원 관리', Users], ['company-usage', '이용 내역', BarChart3]],
  ];
  const companyUsageTabs = [['employee-usage', '사원별 사용'], ['monthly-usage', '월별 이용']];

  return <main className={`shell${isMerchantAdmin ? ' merchant-shell' : ''}${isCompanyAdmin ? ' company-shell' : ''}`}>
    <ImageCropModal request={cropRequest} onCancel={() => finishImageCrop(null)} onApply={finishImageCrop} />
    <header className={`topbar${isMerchantAdmin ? ' merchant-topbar' : ''}${isCompanyAdmin ? ' company-topbar' : ''}`}>
      <div className="top-copy">
        <div className="brand-row">
          <BrandMark />
          {(isMerchantAdmin || isCompanyAdmin) && <strong className="sidebar-entity-name" title={isMerchantAdmin ? merchantQr?.merchant?.name : me?.company?.name}>{isMerchantAdmin ? merchantQr?.merchant?.name : me?.company?.name}</strong>}
          <span className="pill">OPERATIONS</span>
        </div>
        <p>가입 승인, 직원 상태, 식당 결제와 정산 현황을 그린잇 스타일의 카드 대시보드로 확인합니다.</p>
      </div>
      {isPlatformAdmin && <div className="top-actions">
        <button className="ghost" onClick={load} disabled={busy}><RefreshCw size={16}/> 새로고침</button>
        <button className="ghost" onClick={onLogout}><LogOut size={16}/> 로그아웃</button>
      </div>}
    </header>

    {isMerchantAdmin && <nav className="merchant-tabs" aria-label="식당 관리자 메뉴">
      {merchantNavGroups.map((items, groupIndex) => <React.Fragment key={items[0][0]}>{groupIndex > 0 && <div className="merchant-nav-divider" role="separator" />}{items.map(([id, label, Icon]) => <button key={id} type="button" className={merchantSection === id ? 'active' : ''} onClick={() => setMerchantSection(id)} aria-current={merchantSection === id ? 'page' : undefined}><Icon size={20}/><span>{label}</span>{id === 'main' && unreadPaymentCount > 0 && <span className="merchant-nav-badge" aria-label={`새 결제 ${unreadPaymentCount}건`}>{unreadPaymentCount > 99 ? '99+' : unreadPaymentCount}</span>}</button>)}</React.Fragment>)}
      <div className="merchant-nav-divider merchant-nav-divider-before-logout" role="separator" />
      <button type="button" className="merchant-sidebar-logout" onClick={onLogout}><LogOut size={18}/><span>로그아웃</span></button>
      <div className="merchant-sidebar-legal">
        <a href="/privacy.html" target="_blank" rel="noreferrer">개인정보 처리방침</a>
        <span aria-hidden="true">|</span>
        <a href="/terms.html" target="_blank" rel="noreferrer">이용약관</a>
      </div>
    </nav>}

    {isCompanyAdmin && <nav className="company-tabs" aria-label="업체 관리자 메뉴">
      {companyNavGroups.map((items, groupIndex) => <React.Fragment key={items[0][0]}>{groupIndex > 0 && <div className="merchant-nav-divider" role="separator" />}{items.map(([id, label, Icon]) => <button key={id} type="button" className={companySection === id ? 'active' : ''} onClick={() => setCompanySection(id)} aria-current={companySection === id ? 'page' : undefined}><Icon size={20}/><span>{label}</span></button>)}</React.Fragment>)}
      <div className="merchant-nav-divider" role="separator" />
      <button type="button" className="merchant-sidebar-logout" onClick={load} disabled={busy}><RefreshCw size={18}/><span>새로고침</span></button>
      <button type="button" className="merchant-sidebar-logout" onClick={onLogout}><LogOut size={18}/><span>로그아웃</span></button>
      <div className="merchant-sidebar-legal">
        <a href="/privacy.html" target="_blank" rel="noreferrer">개인정보 처리방침</a>
        <span aria-hidden="true">|</span>
        <a href="/terms.html" target="_blank" rel="noreferrer">이용약관</a>
      </div>
    </nav>}

    <div className={isMerchantAdmin ? `merchant-content${merchantSection === 'main' || merchantSection === 'payment-history' ? ' merchant-regular-weight' : ''}` : isCompanyAdmin ? 'company-content merchant-regular-weight' : undefined}>
    {isCompanyAdmin && companySection === 'company-usage' && <nav className="merchant-section-tabs" aria-label="이용 내역 페이지">
      {companyUsageTabs.map(([id, label]) => <button key={id} type="button" className={companyUsageTab === id ? 'active' : ''} onClick={() => setCompanyUsageTab(id)} aria-current={companyUsageTab === id ? 'page' : undefined}>{label}</button>)}
    </nav>}
    {isMerchantAdmin && merchantSection === 'companies' && <nav className="merchant-section-tabs" aria-label="업체 관리 페이지">
      {companyManagementTabs.map(([id, label]) => <button key={id} type="button" className={companyManagementTab === id ? 'active' : ''} onClick={() => setCompanyManagementTab(id)} aria-current={companyManagementTab === id ? 'page' : undefined}>{label}</button>)}
    </nav>}
    {isMerchantAdmin && merchantSection === 'restaurant-management' && <nav className="merchant-section-tabs" aria-label="식당 관리 페이지">
      {restaurantManagementTabs.map(([id, label]) => <button key={id} type="button" className={restaurantManagementTab === id ? 'active' : ''} onClick={() => setRestaurantManagementTab(id)} aria-current={restaurantManagementTab === id ? 'page' : undefined}>{label}</button>)}
    </nav>}
    {isMerchantAdmin && ['announcements', 'reviews'].includes(merchantContentSection) && <AnnouncementReviewPanel token={token} section={merchantContentSection}/>}
    {isMerchantAdmin && <MerchantMockScreen section={merchantContentSection} companyItems={merchantCompanies?.items ?? []} onCompanyDetail={openContractModal} merchant={merchantQr?.merchant} busy={busy} onSaveSupplier={saveMerchantSupplierProfile} onSettings={openAccountSettings} token={token} />}
    {isCompanyAdmin && !showCompanyLegacy && <CompanyMockScreen section={companyContentSection} company={me?.company} busy={busy} onSaveCompany={saveCompanyProfile} onSettings={openAccountSettings} onCompanyInfo={() => setCompanySection('company-info')} />}

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

    {refundOpen && <RefundModal request={merchantRequest} onClose={() => setRefundOpen(false)} onRefunded={async () => { setPaymentHistoryRefreshKey((key) => key + 1); await load(); }} />}

    {employeeBulkOpen && <EmployeeBulkModal token={token} onClose={() => setEmployeeBulkOpen(false)} onConfirmed={async (count) => { setEmployeeBulkOpen(false); setMessage(`직원 ${count}명의 초대를 등록했어요.`); await load(); }} />}

    {contractModal && <div className="modal-backdrop" onClick={() => setContractModal(null)}>
      <section className="invite-modal contract-modal merchant-regular-weight" onClick={(event) => event.stopPropagation()}>
        <div className="panel-title">
          <div>
            <h2>업체 상세</h2>
            <p className="panel-note">회사정보와 계약설정을 함께 확인하고 관리합니다.</p>
          </div>
          <button className="ghost icon-button" onClick={() => setContractModal(null)} aria-label="닫기"><X size={20}/></button>
        </div>
        <section className="company-detail-section">
          <h3>회사 정보</h3>
          <div className="profile-grid contract-summary">
            <span>상호</span><strong>{contractModal.company?.name ?? '-'}</strong>
            <span>사업자등록번호</span><strong>{contractModal.company?.biz_reg_no ?? '-'}</strong>
            <span>대표자</span><strong>{contractModal.company?.representative_name ?? '-'}</strong>
            <span>업태</span><strong>{contractModal.company?.business_type ?? '-'}</strong>
            <span>종목</span><strong>{contractModal.company?.business_item ?? '-'}</strong>
            <span>사업장주소</span><strong>{contractModal.company?.address ?? '-'}</strong>
            <span>담당자명</span><strong>{contractModal.company?.contact_name ?? '-'}</strong>
            <span>담당자 이메일</span><strong>{contractModal.company?.contact_email ?? contractModal.invite?.email ?? '-'}</strong>
            <span>연락처</span><strong>{contractModal.company?.contact_phone ?? '-'}</strong>
            <span>세금계산서 이메일</span><strong>{contractModal.company?.tax_invoice_email ?? '-'}</strong>
            <span>회사 상태</span><strong>{contractModal.company?.status ?? '-'}</strong>
            <span>연결 상태</span><strong>{contractModal.status ?? '-'}</strong>
            <span>연결일</span><strong>{contractModal.created_at ? new Date(contractModal.created_at).toLocaleString('ko-KR') : '-'}</strong>
          </div>
        </section>
        <section className="company-detail-section">
          <h3>계약 설정</h3>
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
          <label>과세 유형
            <select value={contractForm.tax_type} onChange={(event) => setContractForm((form) => ({ ...form, tax_type: event.target.value }))}><option value="unclassified">미분류(이용 차단)</option><option value="taxable">과세</option><option value="tax_free">면세</option></select>
          </label>
          <label className="subsidy-toggle"><input type="checkbox" checked={contractForm.subsidy_enabled} onChange={(event) => setContractForm((form) => ({ ...form, subsidy_enabled: event.target.checked }))} /> 보조금 계약</label>
          {contractForm.subsidy_enabled && <div className="subsidy-fields">
            <label>회사 부담액<input type="number" min="0" step="1" value={contractForm.company_subsidy_amount} onChange={(event) => setContractForm((form) => ({ ...form, company_subsidy_amount: event.target.value }))} required /></label>
            <label>식당 부담액<input type="number" min="0" step="1" value={contractForm.restaurant_subsidy_amount} onChange={(event) => setContractForm((form) => ({ ...form, restaurant_subsidy_amount: event.target.value }))} required /></label>
            <div className={`employee-pay-preview ${subsidyContractInvalid(contractForm) ? 'invalid' : ''}`}><span>직원 실부담액</span><strong>{krw(Math.max(0, Number(contractForm.unit_price || 0) - Number(contractForm.company_subsidy_amount || 0) - Number(contractForm.restaurant_subsidy_amount || 0)))}</strong></div>
            {subsidyContractInvalid(contractForm) && <div className="alert error subsidy-validation">회사 부담액과 식당 부담액의 합계는 단가보다 작아야 해요.</div>}
          </div>}
          <div className="row-actions invite-modal-actions">
            <button className="primary" disabled={busy || subsidyContractInvalid(contractForm)}>저장</button>
            <button className="ghost" type="button" onClick={() => setContractModal(null)}>닫기</button>
          </div>
          </form>
        </section>
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

    {showCompanyLegacy && <section className="inline-summary-row" aria-label="사원 관리 요약">
      <div><Bell size={20}/><span>가입요청</span><strong>{requests.length}명</strong></div>
      <div><Users size={20}/><span>직원</span><strong>{employees ? `${employees.items.length}명` : '조회 중'}</strong></div>
      <div><QrCode size={20}/><span>초대코드</span><strong>{me?.invite_code ?? '-'}</strong><button type="button" className="ghost" onClick={copyCompanyInviteCode} disabled={!me?.invite_code}>복사</button></div>
    </section>}

    {(isPlatformAdmin || (isMerchantAdmin && merchantSection === 'main')) && <section className={`grid${isMerchantAdmin ? ' merchant-kpi-grid' : ''}`}>
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
            const paymentType = item.payment_type_label ?? (item.pay_type === 'ledger' ? '장부' : item.pay_type === 'subsidized' ? '보조금' : '일반');
            return <div className="payment-alert-row" key={item.id}>
              <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false })}</time>
              <strong className="payment-alert-company">{item.company_name ?? '일반 고객'}</strong>
              <span className="payment-alert-person">{item.employee_name ?? '-'}</span>
              <span className={`payment-type-badge ${item.pay_type ?? 'direct'}`}>{paymentType}</span>
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

    {isMerchantAdmin && merchantSection === 'main' && <aside className="merchant-refund-dock"><div><span>결제 취소가 필요하신가요?</span><strong>고객 주문을 조회해 안전하게 환불하세요.</strong></div><button className="refund-open-button" type="button" onClick={() => setRefundOpen(true)}><RotateCcw size={19}/> 환불하기</button></aside>}

    {isMerchantAdmin && merchantSection === 'payment-history' && <PaymentHistoryDashboard request={merchantRequest} refreshKey={paymentHistoryRefreshKey}/>}

    {isPlatformAdmin && <section className="two-col">
      <article className="panel profile-panel">
        <div className="panel-title"><h2>로그인 정보</h2><span className="badge">secure</span></div>
        <div className="profile-grid">
          <span>이메일</span><strong>{session.user.email}</strong>
          <span>{['company_admin', 'merchant_admin'].includes(me?.role) ? '관리자 이름' : '이름'}</span>
          <strong>{me?.display_name ?? '-'}</strong>
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

    {showCompanyLegacy && <section className="panel employee-panel merchant-regular-weight merchant-open-table">
      <div className="panel-title">
        <div><p className="panel-note titleless-guidance">직원 정보, 포인트 잔액과 이번 달 이용 현황을 확인합니다.</p></div>
        <div className="employee-panel-actions"><button className="primary bulk-open-button" onClick={() => setEmployeeBulkOpen(true)} disabled={employees?.bulk_migration_required}>+ 직원 일괄등록</button><span className="badge">{employees?.items?.length ?? 0}명</span></div>
      </div>
      {employees?.bulk_migration_required && <div className="alert error">0017_employee_bulk_invites.sql 적용 후 직원 일괄등록을 사용할 수 있어요.</div>}
      {(employees?.items?.length ?? 0) === 0 ? <p className="empty-state">등록된 직원이 없어요. 일괄등록하거나 직원이 초대코드로 가입하면 여기에 표시됩니다.</p> : <div className="table-wrap"><table><thead><tr><th>상태</th><th>부서</th><th>이름</th><th>사번</th><th>전화번호</th><th>포인트 잔액</th><th>관리</th></tr></thead><tbody>{employees.items.map((employee) => <tr key={employee.id}><td><span className="badge">{employee.is_staged ? '초대대기' : employee.status === 'active' ? '사용중' : employee.status}</span></td><td>{employee.department || '-'}</td><td><strong>{employee.display_name || '이름 없음'}</strong></td><td>{employee.employee_no || '-'}</td><td>{employee.phone || '-'}</td><td>{employee.is_staged ? '-' : `${Number(employee.point_balance ?? 0).toLocaleString()} P`}</td><td>{employee.is_staged ? <span className="muted">최초 가입 대기</span> : <button className="ghost icon-button" disabled={busy} onClick={() => openEmployeeManage(employee)} aria-label={`${employee.display_name ?? '직원'} 관리`} title="직원 관리"><Settings size={18}/></button>}</td></tr>)}</tbody></table></div>}
    </section>}

    {!isPlatformAdmin && isMerchantAdmin && merchantContentSection === 'companies' && <section className="panel merchant-regular-weight merchant-open-table">
      <div className="panel-title">
        <div><p className="panel-note titleless-guidance">새 회사 담당자를 초대합니다.</p></div>
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
        : <div className="table-wrap"><table><thead><tr><th>회사명</th><th>담당자 이메일</th><th>회사상태</th><th>연결상태</th><th>초대 상태</th><th>이메일 전송</th></tr></thead><tbody>{merchantCompanies.items.map((item) => {
          const link = inviteLink(item.invite);
          const companyName = item.company?.name ?? item.company_id;
          return <tr key={item.id}><td>{companyName}</td><td>{item.company?.contact_email ?? item.invite?.email ?? '-'}</td><td>{item.company?.status ?? '-'}</td><td>{item.status}</td><td><span className="badge">{item.invite?.status === 'pending' ? '대기중' : item.invite?.status === 'accepted' || item.invite?.status === 'claimed' ? '수락완료' : item.invite?.status || '-'}</span>{link && item.invite?.status === 'pending' && <button className="ghost" onClick={() => setInviteModal({ link, companyName })}>링크</button>}</td><td>{item.invite?.email_send_status === 'sent' ? '전송완료' : item.invite?.email_send_status === 'failed' ? '전송실패' : '-'} {item.invite?.status === 'pending' && <button className="ghost" disabled={busy} onClick={() => resendCompanyInvite(item.company_id)}>재전송</button>}</td></tr>;
        })}</tbody></table></div>}
    </section>}


    {isMerchantAdmin && merchantContentSection === 'vouchers' && <VoucherProductsPanel items={voucherProducts} migrationRequired={voucherProductsMigrationRequired} token={token} busy={busy} cropImage={requestImageCrop} uploadImage={uploadProductImage} deleteImage={deleteProductImage} onChanged={load} setBusy={setBusy} setError={setError} setMessage={setMessage} />}

    {isMerchantAdmin && merchantContentSection === 'notifications' && <NotificationPanel token={token} history={notifications} migrationRequired={notificationsMigrationRequired} onSent={load} setMessage={setMessage} />}

    {isMerchantAdmin && merchantContentSection === 'daily-menu' && <section className="panel daily-menu-panel">
      <div className="panel-title">
        <div><p className="panel-note titleless-guidance">날짜를 선택해 오늘과 이후의 뷔페 메뉴를 미리 저장할 수 있어요.</p></div>
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



    {showCompanyLegacy && <section className="panel">
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
        <div className="panel-title"><div><span className="eyebrow">ACCOUNT</span><h2 id="account-settings-title">관리자 정보 설정</h2><p className="panel-note">{isMerchantAdmin ? '식당 이름, 관리자 이름과 로그인 비밀번호를 변경할 수 있어요.' : '관리자 이름과 로그인 비밀번호를 변경할 수 있어요.'}</p></div><button type="button" className="icon-button" onClick={() => setAccountSettingsOpen(false)} disabled={busy} aria-label="닫기"><X size={20}/></button></div>
        {error && <div className="alert error">{error}</div>}
        <form className="account-settings-form" onSubmit={saveAccountSettings}>
          <label>로그인 이메일<input type="email" value={session.user.email ?? ''} disabled/></label>
          {isMerchantAdmin && <label>식당 이름<input value={accountSettingsForm.merchant_name} maxLength="80" onChange={(event) => setAccountSettingsForm((form) => ({ ...form, merchant_name: event.target.value }))} required/></label>}
          <label>관리자 이름<input value={accountSettingsForm.display_name} maxLength="80" onChange={(event) => setAccountSettingsForm((form) => ({ ...form, display_name: event.target.value }))} required autoFocus/></label>
          <label>새 비밀번호<input type="password" value={accountSettingsForm.password} minLength="6" autoComplete="new-password" placeholder="변경할 때만 입력 (6자 이상)" onChange={(event) => setAccountSettingsForm((form) => ({ ...form, password: event.target.value }))}/></label>
          <label>새 비밀번호 확인<input type="password" value={accountSettingsForm.password_confirm} minLength="6" autoComplete="new-password" placeholder="새 비밀번호를 다시 입력" onChange={(event) => setAccountSettingsForm((form) => ({ ...form, password_confirm: event.target.value }))}/></label>
          <div className="row-actions"><button type="button" className="ghost" onClick={() => setAccountSettingsOpen(false)} disabled={busy}>취소</button><button className="primary" disabled={busy}>{busy ? '저장 중...' : '변경사항 저장'}</button></div>
        </form>
        <LegalLinks />
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
