import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AlertTriangle, BarChart3, Bell, Building2, CalendarDays, CheckCircle2, ChevronDown, Coffee, CreditCard, Download, FileSpreadsheet, FileText, Home, LogOut, QrCode, RefreshCw, Search, Send, Settings, Users, WalletCards, X, XCircle } from 'lucide-react';
import { createClient } from '@supabase/supabase-js';
import Cropper from 'react-easy-crop';
import './style.css';
import { PaymentHistoryDashboard } from './PaymentFeatures.jsx';
import SettlementDemoPanel from './SettlementDemoPanel.jsx';
import { contractFormFromItem, subsidyContractInvalid } from './contractForm.js';
import { PREPURCHASE_MAX_QUANTITY, PREPURCHASE_MAX_UNIT_PRICE, prepurchaseChargeInvalid, prepurchaseChargePayload, prepurchaseChargeTotal, prepurchaseItems } from './prepurchase.js';
import { captureGeneration, generationIsCurrent } from './generationGuard.js';
import { currentPeriodYm, formatPeriodYm, mapCompanyUsage, shiftPeriodYm } from './companyUsage.js';
import { filterMerchantTransactions, merchantMealPaymentIds, merchantRecentKpis, reconcileMerchantPaymentFeed } from './merchantPaymentFeed.js';
import { BANNER_PLACEMENTS, apiItems, bannerCtr, bannerFormFromItem, bannerListQuery, bannerStatsContract, bannerStatus, imageRatioStatus, isHttpsUrl, normalizeBannerPayload, utcIsoToLocalDateTime } from './partnerBanner.js';
import {
  buildPaymentPayload, canCompanyDispute, canConfirmAndRequest, canMerchantBeginRevision,
  canMerchantIssue, canMerchantMarkPaid, canMerchantSend, canRefreshInvoiceStatus,
  fetchAllSettlementSummaries, hasInvoiceDocument, isBusinessPartyComplete,
  mapSettlement, openDocumentInNewWindow, paymentFormForSettlement, PAYMENT_STATUS_LABELS,
  replaceSettlementDetail, settlementApiRoot,
} from './settlementApi.js';

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
  const blank = { name: '', voucher_count: '0', bonus_count: '0', unit_price: '', discount_rate: '0', discount_amount_per_voucher: '0', status: 'active', display_order: '0', kiwoom_pay_method: 'TOTAL', image_url: '', is_event: false, event_start_at: '', event_end_at: '' };
  const [form, setForm] = useState(blank);
  const [editingId, setEditingId] = useState(null);
  const [pendingImage, setPendingImage] = useState(null);
  const [pendingPreview, setPendingPreview] = useState('');
  const count = Number(form.voucher_count || 0);
  const bonus = Number(form.bonus_count || 0);
  const discount = Number(form.discount_rate || 0);
  const fixedDiscount = Number(form.discount_amount_per_voucher || 0);
  const discountedUnitPrice = Number(form.unit_price || 0) * (100 - discount) / 100 - fixedDiscount;
  const salePrice = Math.round(discountedUnitPrice * count * 100) / 100;

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
    if (discount > 0 && fixedDiscount > 0) { setError('할인율과 장당 할인금액은 한 가지만 적용해 주세요.'); return; }
    if (discountedUnitPrice <= 0) { setError('할인 후 장당 금액은 0원보다 커야 해요.'); return; }
    if (bonus > 0 && (discount > 0 || fixedDiscount > 0) && !window.confirm('보너스와 할인을 동시에 적용하시겠어요?')) return;
    if (form.is_event && (!form.event_start_at || !form.event_end_at)) { setError('이벤트 시작일시와 종료일시를 모두 입력해 주세요.'); return; }
    if (form.is_event && new Date(form.event_end_at) <= new Date(form.event_start_at)) { setError('이벤트 종료일시는 시작일시보다 늦어야 해요.'); return; }
    let uploadedImageUrl = '';
    let persisted = false;
    setBusy(true); setError('');
    try {
      if (pendingImage) uploadedImageUrl = await uploadImage(pendingImage);
      const body = {
        name: form.name.trim(), voucher_count: count, bonus_count: bonus,
        unit_price: Number(form.unit_price), discount_rate: discount,
        discount_amount_per_voucher: fixedDiscount, status: form.status, tax_type: 'taxable',
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
      const nextStatus = item.status === 'active' ? 'sold_out' : 'active';
      await apiFetch(`/admin/voucher-products/${item.id}`, token, { method: 'PATCH', body: JSON.stringify({ status: nextStatus }) });
      setMessage(nextStatus === 'sold_out' ? '상품을 일시품절로 변경했어요.' : '상품 판매를 재개했어요.'); await onChanged();
    } catch (toggleError) { setError(toggleError.message); } finally { setBusy(false); }
  }
  async function remove(item) {
    if (!window.confirm(`'${item.name}' 상품을 삭제하시겠어요? 기존 주문 이력은 보존됩니다.`)) return;
    setBusy(true); setError('');
    try {
      await apiFetch(`/admin/voucher-products/${item.id}`, token, { method: 'DELETE' });
      if (editingId === item.id) { setEditingId(null); setForm(blank); resetPendingImage(); }
      setMessage('판매 상품을 삭제했어요.'); await onChanged();
    } catch (deleteError) { setError(deleteError.message); } finally { setBusy(false); }
  }
  return <section className="panel voucher-panel">
    <div className="panel-title"><div><p className="panel-note titleless-guidance">등록 상품의 판매 상태를 바로 전환하고, 더 이상 쓰지 않는 상품은 삭제할 수 있어요.</p></div><span className="badge">{items.length}개</span></div>
    {migrationRequired && <div className="alert error">상품 DB 마이그레이션이 아직 적용되지 않았어요. 0020·0030·0055 적용 후 할인금액·판매상태·삭제를 사용할 수 있어요.</div>}
    <form className="voucher-form" onSubmit={save}>
      <input value={form.name} onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} placeholder="패키지명" required />
      <label>기본 장수<input type="number" min="1" max="1000" value={form.voucher_count} onChange={(e) => setForm((p) => ({ ...p, voucher_count: e.target.value }))} required /></label>
      <div className="quick-buttons">{[1, 5, 10].map((n) => <button type="button" className="ghost" key={n} onClick={() => setForm((p) => ({ ...p, voucher_count: String(Math.min(1000, Math.max(0, Number(p.voucher_count) || 0) + n)) }))}>+{n}장</button>)}</div>
      <label>보너스 장수<input type="number" min="0" max="1000" value={form.bonus_count} onChange={(e) => setForm((p) => ({ ...p, bonus_count: e.target.value }))} /></label>
      <label>장당 정가<input type="number" min="1" step="0.01" value={form.unit_price} onChange={(e) => setForm((p) => ({ ...p, unit_price: e.target.value }))} required /></label>
      <label>할인율(%)<input type="number" min="0" max="99.99" step="0.01" value={form.discount_rate} onChange={(e) => setForm((p) => ({ ...p, discount_rate: e.target.value, ...(Number(e.target.value) > 0 ? { discount_amount_per_voucher: '0' } : {}) }))} /></label>
      <label>장당 할인금액<input type="number" min="0" step="1" value={form.discount_amount_per_voucher} onChange={(e) => setForm((p) => ({ ...p, discount_amount_per_voucher: e.target.value, ...(Number(e.target.value) > 0 ? { discount_rate: '0' } : {}) }))} disabled={migrationRequired} /></label>
      <label>결제 방식<select value={form.kiwoom_pay_method} onChange={(e) => setForm((p) => ({ ...p, kiwoom_pay_method: e.target.value }))} disabled={migrationRequired}><option value="TOTAL">통합결제창</option><option value="BANK">계좌이체 전용</option></select></label>
      <label>노출순서<input type="number" value={form.display_order} onChange={(e) => setForm((p) => ({ ...p, display_order: e.target.value }))} /></label>
      <label className="event-toggle"><input type="checkbox" checked={form.is_event} onChange={(e) => setForm((p) => ({ ...p, is_event: e.target.checked }))} disabled={migrationRequired}/> 🎉 이벤트 상품으로 등록</label>
      {form.is_event && <>
        <label>이벤트 시작일시<input type="datetime-local" value={form.event_start_at} onChange={(e) => setForm((p) => ({ ...p, event_start_at: e.target.value }))} required /></label>
        <label>이벤트 종료일시<input type="datetime-local" min={form.event_start_at} value={form.event_end_at} onChange={(e) => setForm((p) => ({ ...p, event_end_at: e.target.value }))} required /></label>
      </>}
      <label className="image-picker compact">패키지 이미지<input type="file" accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp" onChange={chooseImage} disabled={busy}/></label>
      <div className="voucher-preview">미리보기 <strong>{count + bonus}장 · {krw(Math.max(0, salePrice))}</strong><span>유료 1장당 {krw(Math.max(0, discountedUnitPrice))}</span>{form.is_event && <span>🎉 노출 기간: {form.event_start_at || '시작일시'} ~ {form.event_end_at || '종료일시'} · 종료 후 자동 숨김</span>}{(pendingPreview || form.image_url) && <img src={pendingPreview || form.image_url} alt="식권 패키지 미리보기"/>}</div>
      {bonus > 0 && (discount > 0 || fixedDiscount > 0) && <div className="alert warning">보너스와 할인이 동시에 적용됩니다. 판매가와 총 장수를 다시 확인하세요.</div>}
      <div className="row-actions"><button className="primary" disabled={busy || migrationRequired}>{editingId ? '수정 저장' : '상품 등록'}</button>{editingId && <button type="button" className="ghost" onClick={() => { setEditingId(null); setForm(blank); resetPendingImage(); }}>취소</button>}</div>
    </form>
    <div className="product-list">{items.map((item) => <article className={item.status === 'active' ? 'product-item' : 'product-item off'} key={item.id}>{item.image_url ? <img className="product-image-preview" src={item.image_url} alt=""/> : <div className="product-image-placeholder">이미지 없음</div>}<div className="product-copy"><strong>{item.name}</strong><span>{item.voucher_count}장{Number(item.bonus_count) > 0 ? ` + ${item.bonus_count}장` : ''} · 판매가 {krw(item.sale_price)} · 순서 {item.display_order}</span><span>{Number(item.discount_amount_per_voucher) > 0 ? `장당 ${krw(item.discount_amount_per_voucher)} 할인` : Number(item.discount_rate) > 0 ? `${item.discount_rate}% 할인` : '할인 없음'}</span><span className="badge">{item.kiwoom_pay_method === 'BANK' ? '계좌이체 전용' : '통합결제창'}</span><span className={`exposure-status ${item.exposure_status}`}>{item.exposure_label}</span>{item.is_event && <span className="event-period">{displayEventPeriod(item)}</span>}</div><div className="row-actions product-admin-actions"><button className="ghost" onClick={() => edit(item)}>수정</button><button type="button" role="switch" aria-checked={item.status === 'active'} className={`status-switch ${item.status === 'active' ? 'on' : ''}`} onClick={() => toggle(item)} disabled={busy || migrationRequired}><span aria-hidden="true"/>{item.status === 'active' ? '판매중' : '일시품절'}</button><button type="button" className="ghost delete-button" onClick={() => remove(item)} disabled={busy || migrationRequired}>삭제</button></div></article>)}</div>
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

  return <section className="panel notification-panel merchant-regular-weight">
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

function CouponManagementPanel({ token, items, migrationRequired, loadError, busy, onChanged, setBusy, setError, setMessage }) {
  const blank = { name: '', discount_type: 'percent', discount_value: '', valid_from: '', valid_until: '', is_active: true };
  const [form, setForm] = useState(blank);
  const [editingId, setEditingId] = useState(null);
  function edit(item) {
    setEditingId(item.id);
    setForm({
      name: item.name ?? '', discount_type: item.discount_type ?? 'percent',
      discount_value: String(item.discount_value ?? ''), valid_from: item.valid_from ?? '',
      valid_until: item.valid_until ?? '', is_active: item.is_active !== false,
    });
  }
  function reset() { setEditingId(null); setForm(blank); }
  async function save(event) {
    event.preventDefault();
    setBusy(true); setError('');
    try {
      await apiFetch(`/admin/coupons${editingId ? `/${editingId}` : ''}`, token, {
        method: editingId ? 'PATCH' : 'POST',
        body: JSON.stringify({
          ...form,
          name: form.name.trim(),
          discount_value: Number(form.discount_value),
          valid_from: form.valid_from || null,
          valid_until: form.valid_until || null,
        }),
      });
      const successMessage = editingId ? '쿠폰을 수정했어요.' : '쿠폰을 등록했어요.';
      reset(); await onChanged();
      setMessage(successMessage);
    } catch (couponError) { setError(couponError.message); }
    finally { setBusy(false); }
  }
  async function toggle(item) {
    setBusy(true); setError('');
    try {
      await apiFetch(`/admin/coupons/${item.id}`, token, {
        method: 'PATCH', body: JSON.stringify({ is_active: !item.is_active }),
      });
      const successMessage = item.is_active ? '쿠폰 적용을 중지했어요.' : '쿠폰 적용을 시작했어요.';
      await onChanged();
      setMessage(successMessage);
    } catch (couponError) { setError(couponError.message); }
    finally { setBusy(false); }
  }
  async function remove(item) {
    if (!window.confirm(`'${item.name}' 쿠폰을 삭제하시겠어요?`)) return;
    setBusy(true); setError('');
    try {
      await apiFetch(`/admin/coupons/${item.id}`, token, { method: 'DELETE' });
      if (editingId === item.id) reset();
      await onChanged(); setMessage('쿠폰을 삭제했어요.');
    } catch (couponError) { setError(couponError.message); }
    finally { setBusy(false); }
  }
  return <section className="panel coupon-panel">
    <div className="panel-title"><div><p className="panel-note titleless-guidance">할인율 쿠폰과 정액 금액 쿠폰을 등록하고 적용 상태를 관리합니다.</p></div><span className="badge">{items.length}개</span></div>
    {migrationRequired && <div className="alert error">쿠폰 기능 업데이트가 적용 중이에요. API와 0055 마이그레이션 적용 후 사용할 수 있어요.</div>}
    {loadError && <div className="alert error">쿠폰 목록을 불러오지 못했어요. {loadError}</div>}
    <div className="coupon-type-cards" role="radiogroup" aria-label="쿠폰 종류">
      <button type="button" role="radio" aria-checked={form.discount_type === 'percent'} className={form.discount_type === 'percent' ? 'active' : ''} onClick={() => setForm((current) => ({ ...current, discount_type: 'percent', discount_value: '' }))}><strong>할인쿠폰</strong><span>결제금액의 일정 비율(%) 할인</span></button>
      <button type="button" role="radio" aria-checked={form.discount_type === 'fixed'} className={form.discount_type === 'fixed' ? 'active' : ''} onClick={() => setForm((current) => ({ ...current, discount_type: 'fixed', discount_value: '' }))}><strong>금액쿠폰</strong><span>정해진 금액(원) 할인</span></button>
    </div>
    <form className="coupon-form" onSubmit={save}>
      <label>쿠폰명<input value={form.name} maxLength="120" onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} placeholder={form.discount_type === 'percent' ? '예: 점심 10% 할인' : '예: 1,000원 할인'} required /></label>
      <label>{form.discount_type === 'percent' ? '할인율(%)' : '할인금액(원)'}<input type="number" min={form.discount_type === 'percent' ? '0.01' : '1'} max={form.discount_type === 'percent' ? '99.99' : undefined} step={form.discount_type === 'percent' ? '0.01' : '1'} value={form.discount_value} onChange={(event) => setForm((current) => ({ ...current, discount_value: event.target.value }))} required /></label>
      <label>시작일<input type="date" value={form.valid_from} onChange={(event) => setForm((current) => ({ ...current, valid_from: event.target.value }))} /></label>
      <label>종료일<input type="date" min={form.valid_from || undefined} value={form.valid_until} onChange={(event) => setForm((current) => ({ ...current, valid_until: event.target.value }))} /></label>
      <label className="checkbox"><input type="checkbox" checked={form.is_active} onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))} /> 등록 즉시 적용</label>
      <div className="row-actions"><button className="primary" disabled={busy || migrationRequired}>{editingId ? '쿠폰 수정' : '쿠폰 등록'}</button>{editingId && <button type="button" className="ghost" onClick={reset}>취소</button>}</div>
    </form>
    <div className="product-list coupon-list">{items.map((item) => <article className={`product-item ${item.is_active ? '' : 'off'}`} key={item.id}><div className="coupon-icon" aria-hidden="true">{item.discount_type === 'percent' ? '%' : '₩'}</div><div className="product-copy"><strong>{item.name}</strong><span>{item.discount_type === 'percent' ? `${item.discount_value}% 할인` : `${krw(item.discount_value)} 할인`}</span><span>{item.valid_from || '즉시'} ~ {item.valid_until || '종료일 없음'}</span></div><div className="row-actions"><button className="ghost" onClick={() => edit(item)}>수정</button><button type="button" role="switch" aria-checked={!!item.is_active} className={`status-switch ${item.is_active ? 'on' : ''}`} onClick={() => toggle(item)} disabled={busy}><span aria-hidden="true"/>{item.is_active ? '적용중' : '중지'}</button><button className="ghost delete-button" onClick={() => remove(item)} disabled={busy}>삭제</button></div></article>)}</div>
  </section>;
}

const blankPartner = { name: '', site_url: '', logo_url: '', contact_name: '', contact_email: '', contact_phone: '', memo: '', status: 'active' };

function PartnerManagementScreen({ token }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState('');
  const [form, setForm] = useState(blankPartner);
  const load = async () => {
    setLoading(true); setError('');
    try { setItems(apiItems(await apiFetch('/admin/partners', token))); }
    catch (loadError) { setError(loadError.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [token]);
  function edit(item) {
    setEditingId(item.id);
    setForm({ name: item.name ?? '', site_url: item.site_url ?? '', logo_url: item.logo_url ?? '', contact_name: item.contact_name ?? '', contact_email: item.contact_email ?? '', contact_phone: item.contact_phone ?? '', memo: item.memo ?? '', status: item.status ?? 'active' });
  }
  function reset() { setEditingId(''); setForm(blankPartner); }
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      await apiFetch(`/admin/partners${editingId ? `/${editingId}` : ''}`, token, { method: editingId ? 'PATCH' : 'POST', body: JSON.stringify({ ...form, name: form.name.trim(), site_url: form.site_url.trim(), logo_url: form.logo_url.trim() || null, contact_name: form.contact_name.trim() || null, contact_email: form.contact_email.trim() || null, contact_phone: form.contact_phone.trim() || null, memo: form.memo.trim() || null }) });
      setNotice(editingId ? '제휴사를 수정했어요.' : '제휴사를 등록했어요.'); reset(); await load();
    } catch (saveError) { setError(saveError.message); } finally { setBusy(false); }
  }
  async function remove(item) {
    if (!window.confirm(`'${item.name}' 제휴사를 삭제하시겠어요?`)) return;
    setBusy(true); setError('');
    try { await apiFetch(`/admin/partners/${item.id}`, token, { method: 'DELETE' }); if (editingId === item.id) reset(); setNotice('제휴사를 삭제했어요.'); await load(); }
    catch (deleteError) { setError(deleteError.message); } finally { setBusy(false); }
  }
  return <AdminPage title="제휴사" description="배너 광고에 연결할 제휴사와 담당자 정보를 관리합니다." preview={false} className="partner-admin-page">
    <section className="panel partner-management-panel">
      {error && <div className="alert error">{error} <button type="button" className="ghost inline-retry" onClick={load}>다시 시도</button></div>}
      {notice && <div className="alert success">{notice}</div>}
      <form className="partner-form" onSubmit={save}>
        <label>제휴사명<input value={form.name} maxLength="120" required onChange={(event) => setForm({ ...form, name: event.target.value })}/></label>
        <label>사이트 URL (HTTPS)<input type="url" value={form.site_url} required pattern="https://.*" placeholder="https://" onChange={(event) => setForm({ ...form, site_url: event.target.value })}/></label>
        <label>로고 URL<input type="url" value={form.logo_url} placeholder="https://" onChange={(event) => setForm({ ...form, logo_url: event.target.value })}/></label>
        <label>담당자명<input value={form.contact_name} onChange={(event) => setForm({ ...form, contact_name: event.target.value })}/></label>
        <label>담당자 이메일<input type="email" value={form.contact_email} onChange={(event) => setForm({ ...form, contact_email: event.target.value })}/></label>
        <label>담당자 연락처<input value={form.contact_phone} onChange={(event) => setForm({ ...form, contact_phone: event.target.value })}/></label>
        <label className="partner-memo-field">메모<input value={form.memo} maxLength="500" onChange={(event) => setForm({ ...form, memo: event.target.value })}/></label>
        <label>상태<select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}><option value="active">활성</option><option value="paused">일시중지</option><option value="ended">종료</option></select></label>
        <div className="row-actions"><button className="primary" disabled={busy}>{editingId ? '수정 저장' : '제휴사 등록'}</button>{editingId && <button type="button" className="ghost" onClick={reset}>취소</button>}</div>
      </form>
      {loading ? <p className="empty-state">제휴사 목록을 불러오고 있어요.</p> : items.length === 0 ? <p className="empty-state">등록된 제휴사가 없어요.</p> : <div className="table-wrap partner-table-wrap"><table><thead><tr><th>제휴사</th><th>사이트</th><th>담당자</th><th>이메일</th><th>연락처</th><th>상태</th><th>관리</th></tr></thead><tbody>{items.map((item) => { const partnerState = { active: { label: '활성', className: 'live' }, paused: { label: '일시중지', className: 'paused' }, ended: { label: '종료', className: 'ended' } }[item.status] ?? { label: item.status, className: 'paused' }; return <tr key={item.id}><td><div className="partner-cell">{item.logo_url ? <img src={item.logo_url} alt=""/> : <span aria-hidden="true">P</span>}<strong>{item.name}</strong></div></td><td><a href={item.site_url} target="_blank" rel="noreferrer">사이트</a></td><td>{item.contact_name || '-'}</td><td>{item.contact_email || '-'}</td><td>{item.contact_phone || '-'}</td><td><span className={`banner-status ${partnerState.className}`}>{partnerState.label}</span></td><td><div className="row-actions"><button type="button" className="ghost" onClick={() => edit(item)}>수정</button><button type="button" className="ghost delete-button" disabled={busy} onClick={() => remove(item)}>삭제</button></div></td></tr>; })}</tbody></table></div>}
    </section>
  </AdminPage>;
}

const blankBanner = bannerFormFromItem(null);
const formatCount = (value) => Number(value ?? 0).toLocaleString('ko-KR');

function BannerPreview({ form, dimensions }) {
  const reward = form.reward_type === 'point' ? `${formatCount(form.point_amount)}P` : form.reward_type === 'coupon' ? '쿠폰' : '';
  const ratio = dimensions?.width && dimensions?.height ? dimensions.width / dimensions.height : BANNER_PLACEMENTS[form.placement]?.ratio;
  return <aside className="banner-phone-preview" aria-label="사용자 앱 배너 미리보기"><div className="phone-speaker"/><div className="phone-screen"><div className="preview-banner" style={{ aspectRatio: ratio || 3 }}>{form.image_url ? <img src={form.image_url} alt={form.image_alt || ''}/> : <span>이미지 미리보기</span>}<b className="ad-badge">광고</b>{reward && <b className="reward-badge">{reward}</b>}<strong>{form.title || '배너 제목'}</strong></div></div></aside>;
}

function BannerEditorModal({ token, item, partners, coupons, placement, onClose, onSaved }) {
  const [form, setForm] = useState(() => bannerFormFromItem(item, placement));
  const [dimensions, setDimensions] = useState(item ? { width: item.image_width, height: item.image_height } : null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const titleRef = useRef(null);
  useEffect(() => { titleRef.current?.focus(); }, []);
  useEffect(() => {
    if (!form.image_url || (dimensions?.width && dimensions?.height)) return;
    const image = new Image(); image.onload = () => setDimensions({ width: image.naturalWidth, height: image.naturalHeight }); image.src = form.image_url;
  }, [form.image_url]);
  const recommendation = BANNER_PLACEMENTS[form.placement];
  const ratioState = dimensions?.width && dimensions?.height ? imageRatioStatus(dimensions.width, dimensions.height, form.placement) : null;
  async function upload(event) {
    const file = event.target.files?.[0]; if (!file) return;
    if (!form.partner_id) { setError('이미지를 업로드하려면 먼저 제휴사를 선택해 주세요.'); event.target.value = ''; return; }
    setBusy(true); setError('');
    const data = new FormData(); data.append('partner_id', form.partner_id); data.append('placement', form.placement); data.append('image', file);
    try { const uploaded = await apiFetch('/admin/banners/upload-image', token, { method: 'POST', body: data }); setForm((current) => ({ ...current, image_url: uploaded.image_url ?? uploaded.url })); setDimensions({ width: uploaded.width, height: uploaded.height }); }
    catch (uploadError) { setError(uploadError.message); } finally { setBusy(false); event.target.value = ''; }
  }
  async function save(event) {
    event.preventDefault(); setError('');
    if (!isHttpsUrl(form.link_url)) { setError('이동 URL은 https://로 시작해야 해요.'); return; }
    if (form.ends_at && form.starts_at && new Date(form.ends_at) <= new Date(form.starts_at)) { setError('종료 일시는 시작 일시보다 늦어야 해요.'); return; }
    if (form.reward_type === 'point' && !form.total_budget && !window.confirm('총 예산이 없는 무제한 포인트 배너입니다. 계속 저장하시겠어요?')) return;
    setBusy(true);
    try { await apiFetch(`/admin/banners${item?.id ? `/${item.id}` : ''}`, token, { method: item?.id ? 'PATCH' : 'POST', body: JSON.stringify(normalizeBannerPayload(form)) }); await onSaved(); }
    catch (saveError) { setError(saveError.message); } finally { setBusy(false); }
  }
  return <div className="modal-backdrop banner-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && !busy && onClose()}>
    <section className="banner-editor-modal" role="dialog" aria-modal="true" aria-labelledby="banner-editor-title" onKeyDown={(event) => event.key === 'Escape' && !busy && onClose()}>
      <header className="banner-modal-header"><div><h2 id="banner-editor-title">{item ? '제휴 배너 수정' : '제휴 배너 등록'}</h2><p>필수 정보와 리워드 정책을 입력하고 앱 노출 모습을 확인하세요.</p></div><button type="button" className="ghost icon-button" aria-label="닫기" onClick={onClose} disabled={busy}><X size={20}/></button></header>
      <div className="banner-modal-layout"><form className="banner-editor-form" onSubmit={save}>
        {error && <div className="alert error banner-form-wide">{error}</div>}
        <label className="banner-form-wide">제휴사<select value={form.partner_id} required onChange={(event) => setForm({ ...form, partner_id: event.target.value })}><option value="">선택해 주세요</option>{partners.filter((partner) => partner.status === 'active' || (item && partner.id === form.partner_id)).map((partner) => <option value={partner.id} key={partner.id}>{partner.name}{partner.status !== 'active' ? ` (${partner.status === 'paused' ? '일시중지' : '종료'})` : ''}</option>)}</select></label>
        <label className="banner-form-wide">배너 제목<input ref={titleRef} value={form.title} maxLength="120" required onChange={(event) => setForm({ ...form, title: event.target.value })}/></label>
        <label>노출 위치<select value={form.placement} onChange={(event) => setForm({ ...form, placement: event.target.value })}><option value="home_bottom">홈 하단</option><option value="event_page">이벤트 페이지</option></select><small>권장 이미지 {recommendation.width}×{recommendation.height}px ({recommendation.ratio}:1)</small></label>
        <label className="banner-form-wide">배너 이미지<input type="file" accept="image/png,image/jpeg,image/webp" onChange={upload} disabled={busy || !form.partner_id}/><input type="url" value={form.image_url} placeholder="또는 HTTPS 이미지 URL" required onChange={(event) => { setDimensions(null); setForm({ ...form, image_url: event.target.value }); }}/>{!form.partner_id && <small>파일 업로드 전에 제휴사를 선택해 주세요.</small>}{ratioState && <small className={ratioState.matches ? 'ratio-ok' : 'ratio-warning'}>실제 {dimensions.width}×{dimensions.height}px · {ratioState.matches ? '권장 비율과 일치' : `권장 ${recommendation.ratio}:1 비율과 다름`}</small>}</label>
        <label className="banner-form-wide">대체 텍스트<input value={form.image_alt} maxLength="200" required placeholder="이미지를 보지 못하는 사용자를 위한 설명" onChange={(event) => setForm({ ...form, image_alt: event.target.value })}/></label>
        <label className="banner-form-wide">이동 URL (HTTPS)<input type="url" value={form.link_url} required pattern="https://.*" placeholder="https://" onChange={(event) => setForm({ ...form, link_url: event.target.value })}/></label>
        <fieldset className="banner-radio banner-form-wide"><legend>열기 방식</legend><label><input type="radio" name="open-mode" value="webview" checked={form.open_mode === 'webview'} onChange={(event) => setForm({ ...form, open_mode: event.target.value })}/> 앱 내 웹뷰</label><label><input type="radio" name="open-mode" value="external" checked={form.open_mode === 'external'} onChange={(event) => setForm({ ...form, open_mode: event.target.value })}/> 외부 브라우저</label></fieldset>
        <label>노출 시작 일시 (선택)<input type="datetime-local" value={form.starts_at} onChange={(event) => setForm({ ...form, starts_at: event.target.value })}/></label>
        <label>노출 종료 일시 (선택)<input type="datetime-local" value={form.ends_at} min={form.starts_at || undefined} onChange={(event) => setForm({ ...form, ends_at: event.target.value })}/></label>
        <label className="banner-form-wide">리워드 유형<select value={form.reward_type} onChange={(event) => setForm({ ...form, reward_type: event.target.value })}><option value="none">없음</option><option value="point">포인트</option><option value="coupon">쿠폰</option></select></label>
        {form.reward_type === 'point' && <label>지급 포인트<input type="number" min="1" step="1" value={form.point_amount} required onChange={(event) => setForm({ ...form, point_amount: event.target.value })}/><small>단위: P</small></label>}
        {form.reward_type === 'coupon' && <label>지급 쿠폰<select value={form.coupon_id} required onChange={(event) => setForm({ ...form, coupon_id: event.target.value })}><option value="">선택해 주세요</option>{coupons.map((coupon) => <option value={coupon.id} key={coupon.id}>{coupon.name}</option>)}</select></label>}
        {form.reward_type === 'coupon' && <label>쿠폰 유효 일수<input type="number" min="1" step="1" value={form.coupon_valid_days} onChange={(event) => setForm({ ...form, coupon_valid_days: event.target.value })}/></label>}
        {form.reward_type !== 'none' && <><label>지급 정책<select value={form.grant_policy} onChange={(event) => setForm({ ...form, grant_policy: event.target.value })}><option value="once">최초 1회</option><option value="daily">매일 1회</option><option value="unlimited">반복 지급</option></select></label>{form.grant_policy === 'unlimited' && <label>사용자별 지급 한도<input type="number" min="1" step="1" value={form.per_user_limit} onChange={(event) => setForm({ ...form, per_user_limit: event.target.value })}/><small>비워두면 무제한</small></label>}</>}
        {form.reward_type === 'point' && <label className="banner-form-wide">총 포인트 예산<input type="number" min="1" step="1" value={form.total_budget} placeholder="비워두면 무제한 (저장 시 확인)" onChange={(event) => setForm({ ...form, total_budget: event.target.value })}/><small>단위: P · 지급 포인트 합계 기준</small></label>}
        <label className="checkbox banner-form-wide"><input type="checkbox" checked={form.is_active} onChange={(event) => setForm({ ...form, is_active: event.target.checked })}/> 활성화 (기간 안에 사용자 앱에 노출)</label>
        <footer className="banner-modal-actions banner-form-wide"><button type="button" className="ghost" onClick={onClose} disabled={busy}>취소</button><button className="primary" disabled={busy}>{busy ? '저장 중...' : '저장'}</button></footer>
      </form><BannerPreview form={form} dimensions={dimensions}/></div>
    </section>
  </div>;
}

function BannerStatsModal({ token, banner, onClose }) {
  const today = todayInput(); const [range, setRange] = useState({ from: `${today.slice(0, 7)}-01`, to: today });
  const [stats, setStats] = useState(null); const [error, setError] = useState(''); const [loading, setLoading] = useState(false);
  async function load() { setLoading(true); setError(''); try { setStats(bannerStatsContract(await apiFetch(`/admin/banners/${banner.id}/stats?from=${range.from}&to=${range.to}`, token))); } catch (loadError) { setError(loadError.message); } finally { setLoading(false); } }
  useEffect(() => { load(); }, [banner.id]);
  const { items: rows, totals } = bannerStatsContract(stats);
  return <div className="modal-backdrop banner-modal-backdrop"><section className="banner-stats-modal" role="dialog" aria-modal="true" aria-labelledby="banner-stats-title"><header className="banner-modal-header"><div><h2 id="banner-stats-title">배너 상세 통계</h2><p>{banner.partner?.name ?? '-'} · {banner.title}</p></div><button className="ghost icon-button" aria-label="닫기" onClick={onClose}><X size={20}/></button></header><div className="stats-range"><label>시작일<input type="date" value={range.from} max={range.to} onChange={(event) => setRange({ ...range, from: event.target.value })}/></label><label>종료일<input type="date" value={range.to} min={range.from} max={today} onChange={(event) => setRange({ ...range, to: event.target.value })}/></label><button className="primary" onClick={load} disabled={loading}>조회</button></div>{error && <div className="alert error">{error} <button className="ghost inline-retry" onClick={load}>다시 시도</button></div>}<div className="banner-stat-totals"><div><span>노출</span><strong>{formatCount(totals.impressions)}</strong></div><div><span>클릭</span><strong>{formatCount(totals.clicks)}</strong></div><div><span>CTR</span><strong>{bannerCtr(totals)}</strong></div><div><span>지급 금액</span><strong>{formatCount(totals.granted_amount)}</strong></div><div><span>지급 건수</span><strong>{formatCount(totals.granted_count)}</strong></div></div><div className="table-wrap banner-stats-table"><table><thead><tr><th>날짜</th><th>노출</th><th>클릭</th><th>CTR</th><th>지급 금액</th><th>지급 건수</th></tr></thead><tbody>{rows.map((row) => <tr key={row.day}><td>{row.day}</td><td>{formatCount(row.impressions)}</td><td>{formatCount(row.clicks)}</td><td>{bannerCtr(row)}</td><td>{formatCount(row.granted_amount)}</td><td>{formatCount(row.granted_count)}</td></tr>)}</tbody></table></div>{!loading && rows.length === 0 && <p className="empty-state">조회 기간의 통계가 없어요.</p>}</section></div>;
}

function PartnerBannerManagementScreen({ token }) {
  const [placement, setPlacement] = useState('home_bottom'); const [stateFilter, setStateFilter] = useState(''); const [partnerFilter, setPartnerFilter] = useState(''); const [items, setItems] = useState([]); const [partners, setPartners] = useState([]); const [coupons, setCoupons] = useState([]);
  const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [editor, setEditor] = useState(null); const [stats, setStats] = useState(null); const [busy, setBusy] = useState(false);
  const load = async () => { setLoading(true); setError(''); try { const [bannerData, partnerData, couponData] = await Promise.all([apiFetch(bannerListQuery({ placement, state: stateFilter, partnerId: partnerFilter }), token), apiFetch('/admin/partners', token), apiFetch('/admin/coupons?issuable=true', token)]); setItems(bannerData.items); setPartners(apiItems(partnerData)); setCoupons(apiItems(couponData)); } catch (loadError) { setError(loadError.message); } finally { setLoading(false); } };
  useEffect(() => { load(); }, [token, placement, stateFilter, partnerFilter]);
  async function remove(item) { if (!window.confirm(`'${item.title}' 배너를 영구 삭제하시겠어요? 이 작업은 되돌릴 수 없습니다.`)) return; setBusy(true); setError(''); try { await apiFetch(`/admin/banners/${item.id}?force=true`, token, { method: 'DELETE' }); setNotice('배너를 삭제했어요.'); await load(); } catch (deleteError) { setError(deleteError.message); } finally { setBusy(false); } }
  async function move(index, direction) { const target = index + direction; if (target < 0 || target >= items.length) return; const next = [...items]; [next[index], next[target]] = [next[target], next[index]]; setItems(next); setBusy(true); setError(''); try { await apiFetch('/admin/banners/reorder', token, { method: 'PATCH', body: JSON.stringify({ items: next.map((item, sortOrder) => ({ id: item.id, sort_order: sortOrder })) }) }); } catch (moveError) { setItems(items); setError(moveError.message); } finally { setBusy(false); } }
  const rewardLabel = (item) => item.reward?.reward_type === 'point' ? `${formatCount(item.reward.point_amount)}P` : item.reward?.reward_type === 'coupon' ? (item.reward.coupon_name ?? item.reward.coupon?.name ?? '쿠폰') : '없음';
  return <AdminPage title="제휴 배너" description="앱 배너의 노출 순서, 일정, 광고 성과와 리워드를 관리합니다." preview={false} className="partner-admin-page banner-management-page" actions={<button className="primary banner-create-button" onClick={() => setEditor({ placement })}>+ 배너 등록</button>}>
    <nav className="banner-placement-tabs" aria-label="배너 노출 위치">{Object.entries(BANNER_PLACEMENTS).map(([key, value]) => <button type="button" key={key} className={placement === key ? 'active' : ''} aria-current={placement === key ? 'page' : undefined} onClick={() => setPlacement(key)}>{value.label}<small>{value.width}×{value.height}</small></button>)}</nav>
    <div className="banner-list-filters"><label>상태<select value={stateFilter} onChange={(event) => setStateFilter(event.target.value)}><option value="">전체</option><option value="live">노출중</option><option value="scheduled">예약</option><option value="inactive">중지</option><option value="ended">종료</option></select></label><label>제휴사<select value={partnerFilter} onChange={(event) => setPartnerFilter(event.target.value)}><option value="">전체</option>{partners.map((partner) => <option key={partner.id} value={partner.id}>{partner.name}</option>)}</select></label></div>
    <section className="panel banner-list-panel">{error && <div className="alert error">{error} <button className="ghost inline-retry" onClick={load}>다시 시도</button></div>}{notice && <div className="alert success">{notice}</div>}{loading ? <p className="empty-state">배너 목록을 불러오고 있어요.</p> : items.length === 0 ? <p className="empty-state">이 위치에 등록된 배너가 없어요.</p> : <div className="table-wrap banner-table-wrap"><table><thead><tr><th>썸네일</th><th>제휴사</th><th>제목</th><th>기간</th><th>상태</th><th>노출</th><th>클릭</th><th>CTR</th><th>리워드</th><th>순서</th><th>관리</th></tr></thead><tbody>{items.map((item, index) => { const status = bannerStatus(item); return <tr key={item.id}><td><img className="banner-thumbnail" src={item.image_url} alt={item.image_alt || ''}/></td><td>{item.partner.name}</td><td><strong>{item.title}</strong></td><td>{item.starts_at ? utcIsoToLocalDateTime(item.starts_at).replace('T', ' ') : '즉시'}<br/>~ {item.ends_at ? utcIsoToLocalDateTime(item.ends_at).replace('T', ' ') : '종료 없음'}</td><td><span className={`banner-status ${status.key}`}>{status.label}</span></td><td>{formatCount(item.stats.impressions)}</td><td>{formatCount(item.stats.clicks)}</td><td>{bannerCtr(item.stats)}</td><td>{rewardLabel(item)}</td><td><div className="sort-buttons"><button type="button" className="ghost" aria-label={`${item.title} 위로`} disabled={busy || index === 0} onClick={() => move(index, -1)}>↑</button><button type="button" className="ghost" aria-label={`${item.title} 아래로`} disabled={busy || index === items.length - 1} onClick={() => move(index, 1)}>↓</button></div></td><td><div className="row-actions banner-row-actions"><button className="ghost" onClick={() => setStats(item)}>통계</button><button className="ghost" onClick={async () => { setBusy(true); try { setEditor(await apiFetch(`/admin/banners/${item.id}`, token)); } catch (detailError) { setError(detailError.message); } finally { setBusy(false); } }}>수정</button><button className="ghost delete-button" disabled={busy} onClick={() => remove(item)}>삭제</button></div></td></tr>; })}</tbody></table></div>}</section>
    {editor && <BannerEditorModal token={token} item={editor.id ? editor : null} placement={editor.placement ?? placement} partners={partners} coupons={coupons} onClose={() => setEditor(null)} onSaved={async () => { setEditor(null); setNotice('배너를 저장했어요.'); await load(); }}/>} {stats && <BannerStatsModal token={token} banner={stats} onClose={() => setStats(null)}/>}
  </AdminPage>;
}

function PaymentQrPanel({ recentPaymentAlerts, merchantQr, merchantQrImageUrl, merchantPayUrl, onDownload, onCopy }) {
  return <section className="two-col merchant-main-panels payment-qr-management">
    <article className="panel payment-alert-panel">
      <div className="panel-title payment-alert-heading"><div><h2><Bell size={21}/> 오늘의 결제 알림</h2><p className="panel-note">오늘 승인된 최근 결제 10건을 실시간으로 표시합니다.</p></div><span className="badge">{recentPaymentAlerts.length}건</span></div>
      {recentPaymentAlerts.length === 0 ? <p className="empty-state">오늘 들어온 결제가 아직 없어요.</p> : <div className="payment-alert-list">
        {recentPaymentAlerts.map((item) => {
          const paymentType = item.is_bonus
            ? '식권 (보너스)'
            : item.pay_type === 'voucher'
              ? '식권'
              : item.payment_type_label ?? (item.pay_type === 'ledger' ? '장부' : item.pay_type === 'subsidized' ? '보조금' : '일반');
          return <div className="payment-alert-row" key={item.id}>
            <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false })}</time>
            <strong className="payment-alert-company">{item.company_name ?? '일반 고객'}</strong>
            <span className="payment-alert-person">{item.employee_name ?? '-'}</span>
            <span className={`payment-type-badge ${item.pay_type ?? 'direct'}`}>{paymentType}</span>
            <b>{item.is_bonus ? '0원' : krw(Math.abs(Number(item.amount ?? 0)))}</b>
          </div>;
        })}
      </div>}
    </article>
    <article className="panel merchant-qr-panel">
      <div className="panel-title"><div><h2>내 매장 결제 QR</h2><p className="panel-note">카운터에 비치할 직원 결제용 QR입니다.</p></div><QrCode size={24}/></div>
      {merchantQrImageUrl ? <div className="qr-card-body">
        <img className="merchant-qr-image" src={merchantQrImageUrl} alt="매장 결제 QR 코드" />
        <div className="qr-card-copy"><strong>{merchantQr?.merchant?.name ?? '내 매장'}</strong><span>직원 앱 또는 휴대폰 카메라로 스캔</span><input value={merchantPayUrl} readOnly onFocus={(event) => event.target.select()} /></div>
        <div className="row-actions qr-actions"><button className="primary" onClick={onDownload}>PDF 다운로드</button><button className="ghost" onClick={onCopy}>링크 복사</button></div>
      </div> : <p className="empty-state">매장 QR 정보를 불러오고 있어요.</p>}
    </article>
  </section>;
}

function AnnouncementReviewPanel({ token, section }) {
  const today = todayInput();
  const [data, setData] = useState({ items: [] });
  const [error, setError] = useState('');
  const [form, setForm] = useState({ title: '', content: '', pinned: false, send_push: false });
  const [editingAnnouncementId, setEditingAnnouncementId] = useState('');
  const [sort, setSort] = useState('latest');
  const [reviewFilter, setReviewFilter] = useState('all');
  const [period, setPeriod] = useState({ from: `${today.slice(0, 7)}-01`, to: today });
  const [replyDrafts, setReplyDrafts] = useState({});
  const load = async () => {
    try {
      const next = await apiFetch(section === 'announcements' ? '/admin/announcements' : `/admin/reviews?sort=${sort}`, token);
      setData(next);
      if (section === 'reviews') {
        setReplyDrafts((current) => Object.fromEntries((next.items ?? []).map((item) => [
          item.id,
          Object.prototype.hasOwnProperty.call(current, item.id) ? current[item.id] : item.owner_reply ?? '',
        ])));
      }
      setError('');
    } catch (loadError) { setError(loadError.message); }
  };
  useEffect(() => { load(); }, [section, sort]);
  async function publish(event) {
    event.preventDefault();
    try {
      const editing = Boolean(editingAnnouncementId);
      const payload = editing
        ? { title: form.title, content: form.content, pinned: form.pinned }
        : form;
      await apiFetch(`/admin/announcements${editing ? `/${editingAnnouncementId}` : ''}`, token, {
        method: editingAnnouncementId ? 'PATCH' : 'POST',
        body: JSON.stringify(payload),
      });
      setEditingAnnouncementId('');
      setForm({ title: '', content: '', pinned: false, send_push: false });
      await load();
    } catch (publishError) { setError(publishError.message); }
  }
  function editAnnouncement(item) {
    setEditingAnnouncementId(item.id);
    setForm({ title: item.title, content: item.content, pinned: item.pinned, send_push: false });
  }
  function cancelAnnouncementEdit() {
    setEditingAnnouncementId('');
    setForm({ title: '', content: '', pinned: false, send_push: false });
  }
  async function patchItem(id, values) {
    try {
      await apiFetch(`/admin/${section}/${id}`, token, { method: 'PATCH', body: JSON.stringify(values) });
      await load();
    } catch (patchError) { setError(patchError.message); }
  }
  async function deleteAnnouncement(item) {
    if (!window.confirm(`'${item.title}' 공지사항을 삭제하시겠어요?`)) return;
    try {
      await apiFetch(`/admin/announcements/${item.id}`, token, { method: 'DELETE' });
      await load();
    } catch (deleteError) { setError(deleteError.message); }
  }
  if (section === 'announcements') return <section className="panel">
    <div className="panel-title"><div><p className="panel-note titleless-guidance">{editingAnnouncementId ? '공지사항 내용을 수정하고 저장합니다.' : '앱에 계속 노출할 소식을 작성하고 관리합니다.'}</p></div></div>
    {error && <div className="alert error">{error}</div>}
    <form className="form" onSubmit={publish}>
      <label>제목<input value={form.title} maxLength="120" onChange={(event) => setForm({ ...form, title: event.target.value })} required/></label>
      <label>내용<textarea rows="5" value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} required/></label>
      <label className="checkbox"><input type="checkbox" checked={form.pinned} onChange={(event) => setForm({ ...form, pinned: event.target.checked })}/> 상단 고정</label>
      {!editingAnnouncementId && <label className="checkbox"><input type="checkbox" checked={form.send_push} onChange={(event) => setForm({ ...form, send_push: event.target.checked })}/> 푸시 알림도 함께 발송</label>}
      <div className="actions"><button className="primary">{editingAnnouncementId ? '수정 저장' : '게시하기'}</button>{editingAnnouncementId && <button type="button" className="ghost" onClick={cancelAnnouncementEdit}>수정 취소</button>}</div>
    </form>
    <div className="list">{data.items.map((item) => <article className={`card ${item.status === 'hidden' ? 'muted' : ''}`} key={item.id}><h3>{item.pinned && '📌 '}{item.title} {item.status === 'hidden' && '(숨김)'}</h3><p>{item.content}</p><small>{new Date(item.created_at).toLocaleString('ko-KR')}</small><div className="actions"><button className="ghost" onClick={() => patchItem(item.id, { pinned: !item.pinned })}>{item.pinned ? '고정 해제' : '상단 고정'}</button><button className="ghost" onClick={() => editAnnouncement(item)}>수정</button><button className="ghost delete-button" onClick={() => deleteAnnouncement(item)}>삭제</button></div></article>)}</div>
  </section>;
  const filteredItems = data.items.filter((item) => {
    const reviewDate = item.created_at ? new Date(item.created_at).toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' }) : '';
    const inPeriod = (!period.from || reviewDate >= period.from) && (!period.to || reviewDate <= period.to);
    const matchesStatus = reviewFilter === 'all'
      || (reviewFilter === 'unanswered' && !String(item.owner_reply ?? '').trim())
      || (reviewFilter === 'hidden' && item.status === 'hidden');
    return inPeriod && matchesStatus;
  });
  return <section className="panel review-management-panel">
    <div className="panel-title"><div><p className="panel-note titleless-guidance">평균 별점 ⭐️ {data.average_rating ?? 0} ({data.review_count ?? 0}개)</p></div><select value={sort} onChange={(event) => setSort(event.target.value)}><option value="latest">최신순</option><option value="rating_asc">낮은 별점순</option></select></div>
    <div className="review-filter-bar">
      <label>조회 시작일<input type="date" value={period.from} max={period.to || today} onChange={(event) => setPeriod((current) => ({ ...current, from: event.target.value }))}/></label>
      <label>조회 종료일<input type="date" value={period.to} min={period.from || undefined} max={today} onChange={(event) => setPeriod((current) => ({ ...current, to: event.target.value }))}/></label>
      <label>필터<select value={reviewFilter} onChange={(event) => setReviewFilter(event.target.value)}><option value="all">전체</option><option value="unanswered">미답변</option><option value="hidden">숨김</option></select></label>
      <span className="badge">조회 {filteredItems.length}건</span>
    </div>
    <p className="panel-note review-visibility-note">숨김을 켜면 해당 리뷰는 글쓴이와 식당 관리자에게만 보입니다.</p>
    {error && <div className="alert error">{error}</div>}
    <div className="list">{filteredItems.length === 0 ? <p className="empty-state">조건에 맞는 리뷰가 없어요.</p> : filteredItems.map((item) => <article className={`card ${item.status === 'hidden' ? 'muted' : ''}`} key={item.id}>
      <h3>{item.author_name} {'⭐'.repeat(item.rating)} {item.status === 'hidden' && '(숨김)'}</h3>
      <small>{item.created_at ? new Date(item.created_at).toLocaleString('ko-KR') : '-'}</small>
      <p>{item.content || '내용 없이 별점만 남긴 리뷰예요.'}</p>
      {item.image_urls?.length > 0 && <div className="review-images">{item.image_urls.map((url) => <img src={url} key={url} alt="리뷰"/>)}</div>}
      <label>사장님 답글<textarea value={replyDrafts[item.id] ?? ''} onChange={(event) => setReplyDrafts((current) => ({ ...current, [item.id]: event.target.value }))}/></label>
      <label className="checkbox review-visibility-checkbox"><input type="checkbox" checked={item.status === 'hidden'} onChange={(event) => patchItem(item.id, { status: event.target.checked ? 'hidden' : 'visible' })}/> 사용자 앱에서 숨김 <span>글쓴이와 관리자만 볼 수 있음</span></label>
      <div className="actions"><button className="primary" onClick={() => patchItem(item.id, { owner_reply: replyDrafts[item.id] ?? '' })}>답글 저장</button></div>
    </article>)}</div>
  </section>;
}

function AdminPage({ title, description, children, actions = null, preview = true, showHeader = true, className = '' }) {
  return <section className={`admin-page${className ? ` ${className}` : ''}`}>
    {showHeader && <div className="panel-title admin-page-title"><div>{preview && <span className="eyebrow">PREVIEW</span>}{title && <h2>{title}</h2>}<p className={`panel-note${!title ? ' titleless-guidance' : ''}`}>{description}</p></div><div className="admin-page-actions">{actions}{preview && <span className="badge">목업</span>}</div></div>}
    {children ?? <article className="panel"><p className="empty-state">화면 구성을 준비 중입니다.</p></article>}
  </section>;
}


const SETTLEMENT_STATUS = {
  calculating: '계산 중', draft: '작성 중', sent: '정산 확인 대기', pending: '정산 확인 대기',
  confirmed: '정산 확정', disputed: '이의 제기', revising: '수정 검토 중',
  finalized: '정산 마감', completed: '정산 완료', cancelled: '정산 취소',
};
const TAX_INVOICE_STATUS = {
  not_requested: '미요청', requested: '발급 요청', issuing: '발행 처리 중', issued: '발행 완료',
  nts_sending: '국세청 전송 중', nts_accepted: '국세청 접수 완료', failed: '발행 실패', cancelled: '발행 취소',
};
const PAYMENT_STATUS = PAYMENT_STATUS_LABELS;

function useSettlementV2Rows(token, isMerchant) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [warning, setWarning] = useState('');
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const root = settlementApiRoot(isMerchant);
  useEffect(() => {
    const controller = new AbortController();
    setError(''); setWarning(''); setLoading(true);
    (async () => {
      try {
        const summaries = await fetchAllSettlementSummaries(({ limit, offset }) =>
          apiFetch(`${root}?limit=${limit}&offset=${offset}`, token, { signal: controller.signal }));
        if (!controller.signal.aborted) setRows(summaries.map(mapSettlement));
      } catch (loadError) {
        if (!controller.signal.aborted) { setRows((current) => current ?? []); setError(loadError.message); }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [root, token, reloadKey]);
  return {
    rows, error, warning, loading,
    reload: () => { if (!loading) setReloadKey((value) => value + 1); },
    clearMessages: () => { setError(''); setWarning(''); },
    setRows,
  };
}

function formatKoreanTimestamp(value) {
  if (!value) return '미확정';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '미확정';
  return new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function settlementV2Evidence(row, recipient = row.recipient) {
  return { id: `ev-${row.id}`, kind: '매출', item: `${row.period_start.slice(0, 7)} 식대(월합계)`, type: '세금계산서', recipient: recipient.name, bizNo: recipient.biz_reg_no, supply: row.supply_amount, vat: row.vat_amount, total: row.total_amount, writtenAt: row.invoice?.written_at ?? '미확정', approvalNo: row.invoice?.approval_number ?? '미수신', approvedAt: formatKoreanTimestamp(row.invoice?.issued_at) };
}

function SettlementV2Status({ type = 'generic', value }) {
  const labels = type === 'settlement' ? SETTLEMENT_STATUS : type === 'invoice' ? TAX_INVOICE_STATUS : type === 'payment' ? PAYMENT_STATUS : null;
  return <span className={`settlement-v2-status ${value}`}>{labels?.[value] ?? value}</span>;
}

function SettlementV2Empty({ text = '내역이 없습니다' }) {
  return <div className="settlement-v2-empty" role="status"><FileText size={32}/><strong>{text}</strong></div>;
}

function SettlementV2Screen({ viewer, token, companyProfile = null, onCompanyInfo = null }) {
  const isMerchant = viewer === 'merchant';
  const { rows: loadedRows, error: loadError, warning: loadWarning, loading, reload, clearMessages, setRows } = useSettlementV2Rows(token, isMerchant);
  const rows = loadedRows ?? [];
  const [year, setYear] = useState(() => new Date().getFullYear());
  const [month, setMonth] = useState('all');
  const [selectedId, setSelectedId] = useState(null);
  const [detailTab, setDetailTab] = useState('evidence');
  const [dialog, setDialog] = useState(null);
  const [notice, setNotice] = useState('');
  const [actionError, setActionError] = useState('');
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [pendingAction, setPendingAction] = useState('');
  const [confirmChecks, setConfirmChecks] = useState([false, false, false]);
  const [disputeReason, setDisputeReason] = useState('');
  const [paymentForm, setPaymentForm] = useState({ amount: '', depositor_name: '', deposited_at: '', memo: '' });
  const actionButtonRef = useRef(null);
  const backButtonRef = useRef(null);
  const dialogRef = useRef(null);
  const dialogReturnRef = useRef(null);
  const evidenceRequestRef = useRef(0);
  const selectedIdRef = useRef(null);
  const disputeIdempotencyKeyRef = useRef(null);
  const paymentIdempotencyKeyRef = useRef(null);
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

  const evidenceRows = selected?.transactions ?? [];
  const evidenceTotal = evidenceRows.reduce((total, transaction) => total + transaction.total_amount, 0);
  const depositRows = (selected?.payments ?? []).map((payment) => [formatKoreanTimestamp(payment.deposited_at), payment.amount, payment.memo || payment.depositor_name || '-']);
  const depositedAmount = selected?.payment?.amount ?? 0;

  async function openSettlement(row) {
    const requestId = evidenceRequestRef.current + 1;
    evidenceRequestRef.current = requestId;
    selectedIdRef.current = row.id;
    setSelectedId(row.id);
    clearMessages();
    setDetailTab('evidence');
    setNotice('');
    setActionError('');
    setEvidenceLoading(true);
    try {
      const root = settlementApiRoot(isMerchant);
      const detail = await apiFetch(`${root}/${encodeURIComponent(row.id)}?include_transactions=true`, token);
      if (evidenceRequestRef.current !== requestId) return;
      setRows((current) => replaceSettlementDetail(current, detail));
    } catch (evidenceError) {
      if (evidenceRequestRef.current === requestId) setActionError(evidenceError.message);
    } finally {
      if (evidenceRequestRef.current === requestId) setEvidenceLoading(false);
    }
  }

  function closeDialog() {
    if (pendingAction) return;
    if (dialog === 'dispute') disputeIdempotencyKeyRef.current = null;
    if (dialog === 'payment') paymentIdempotencyKeyRef.current = null;
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

  async function refreshAfterAction(message) {
    const settlementId = selected.id;
    if (selectedIdRef.current !== settlementId) return false;
    const requestId = evidenceRequestRef.current + 1;
    evidenceRequestRef.current = requestId;
    const root = settlementApiRoot(isMerchant);
    try {
      const detail = await apiFetch(`${root}/${encodeURIComponent(settlementId)}?include_transactions=true`, token);
      if (evidenceRequestRef.current !== requestId || selectedIdRef.current !== settlementId) return false;
      setRows((current) => replaceSettlementDetail(current, detail));
      setNotice(message);
      return true;
    } catch (detailError) {
      if (evidenceRequestRef.current === requestId && selectedIdRef.current === settlementId) {
        setNotice(message);
        setActionError(`처리는 완료됐지만 최신 상세 정보를 불러오지 못했습니다. 다시 시도해 주세요. (${detailError.message})`);
      }
      return false;
    } finally {
      if (evidenceRequestRef.current === requestId && selectedIdRef.current === settlementId) setEvidenceLoading(false);
    }
  }

  async function retrySelectedDetail() {
    if (!selected || pendingAction) return;
    const settlementId = selected.id;
    if (selectedIdRef.current !== settlementId) return;
    const requestId = evidenceRequestRef.current + 1;
    evidenceRequestRef.current = requestId;
    setPendingAction('detail-refresh');
    clearMessages();
    setActionError('');
    setEvidenceLoading(true);
    try {
      const root = settlementApiRoot(isMerchant);
      const detail = await apiFetch(`${root}/${encodeURIComponent(settlementId)}?include_transactions=true`, token);
      if (evidenceRequestRef.current !== requestId || selectedIdRef.current !== settlementId) return;
      setRows((current) => replaceSettlementDetail(current, detail));
    } catch (detailError) {
      if (evidenceRequestRef.current === requestId && selectedIdRef.current === settlementId) setActionError(detailError.message);
    } finally {
      if (evidenceRequestRef.current === requestId && selectedIdRef.current === settlementId) setEvidenceLoading(false);
      setPendingAction((current) => current === 'detail-refresh' ? '' : current);
    }
  }

  async function confirmInvoiceAction() {
    if (!selected || pendingAction) return;
    if (!isMerchant && (!recipientReady || !confirmChecks.every(Boolean))) {
      setActionError('회사 정보의 필수 공급받는자 정보를 모두 입력하고 확인 항목에 동의해 주세요.');
      return;
    }
    setPendingAction('invoice'); setActionError('');
    const root = settlementApiRoot(isMerchant);
    try {
      await apiFetch(`${root}/${encodeURIComponent(selected.id)}/${isMerchant ? 'tax-invoice/issue' : 'confirm-and-request-tax-invoice'}`, token, {
        method: 'POST',
        body: JSON.stringify(isMerchant ? {} : { business_info_accurate: true, email_accurate: true, amount_checked: true }),
      });
      await refreshAfterAction(isMerchant
        ? '세금계산서 발행 요청을 처리했습니다. 결과가 불명확하거나 처리 중이면 상태 새로고침으로 팝빌 결과를 확인해 주세요.'
        : '정산을 확정하고 세금계산서 발급을 요청했습니다.');
      dialogReturnRef.current = backButtonRef.current;
      setDialog(null);
    } catch (actionFailure) {
      setActionError(actionFailure.code === 'POPBILL_RECONCILIATION_REQUIRED'
        ? '발행 결과가 불명확합니다. 중복 발행하지 말고 상태 새로고침으로 팝빌 결과를 확인해 주세요.'
        : actionFailure.message);
    } finally {
      setPendingAction('');
    }
  }

  async function settlementWorkflowAction(action) {
    if (!selected || !isMerchant || pendingAction) return;
    setPendingAction(action); setActionError('');
    try {
      await apiFetch(`/admin/merchant/settlements/${encodeURIComponent(selected.id)}/${action}`, token, { method: 'POST', body: '{}' });
      const message = action === 'begin-revision'
        ? '정산서 수정 검토를 시작했습니다. 검토 후 업체에 정산서를 재발송해 주세요.'
        : selected.settlement_status === 'revising'
          ? '수정 검토한 정산서를 업체에 재발송했습니다.'
          : '정산서를 업체에 발송했습니다.';
      await refreshAfterAction(message);
    } catch (workflowError) { setActionError(workflowError.message); }
    finally { setPendingAction(''); }
  }

  async function disputeSettlement(event) {
    event.preventDefault();
    if (!selected || isMerchant || pendingAction) return;
    const reason = disputeReason.trim();
    if (!reason) { setActionError('이의 제기 사유를 입력해 주세요.'); return; }
    setPendingAction('dispute'); setActionError('');
    try {
      disputeIdempotencyKeyRef.current ??= crypto.randomUUID();
      await apiFetch(`/company/settlements/${encodeURIComponent(selected.id)}/dispute`, token, {
        method: 'POST', body: JSON.stringify({ reason, idempotency_key: disputeIdempotencyKeyRef.current }),
      });
      await refreshAfterAction('정산 내용에 이의를 제기했습니다. 업체의 수정 정산서를 기다려 주세요.');
      disputeIdempotencyKeyRef.current = null;
      setDialog(null); setDisputeReason('');
    } catch (disputeError) { setActionError(disputeError.message); }
    finally { setPendingAction(''); }
  }

  async function markPaid(event) {
    event.preventDefault();
    if (!selected || !isMerchant || pendingAction) return;
    let payload;
    try {
      paymentIdempotencyKeyRef.current ??= crypto.randomUUID();
      payload = buildPaymentPayload(paymentForm, paymentIdempotencyKeyRef.current);
    }
    catch (validationError) { setActionError(validationError.message); return; }
    setPendingAction('paid'); setActionError('');
    try {
      await apiFetch(`/admin/merchant/settlements/${encodeURIComponent(selected.id)}/mark-paid`, token, {
        method: 'POST', body: JSON.stringify(payload),
      });
      await refreshAfterAction('입금 내역을 등록했습니다.');
      paymentIdempotencyKeyRef.current = null;
      dialogReturnRef.current = actionButtonRef.current;
      setDialog(null);
    } catch (paymentError) { setActionError(paymentError.message); }
    finally { setPendingAction(''); }
  }

  async function refreshInvoiceStatus() {
    if (!selected || !isMerchant || pendingAction) return;
    setPendingAction('refresh'); setActionError('');
    try {
      await apiFetch(`/admin/merchant/settlements/${encodeURIComponent(selected.id)}/tax-invoice/refresh-status`, token, { method: 'POST', body: '{}' });
      await refreshAfterAction('팝빌과 국세청 처리 상태를 새로고침했습니다.');
    } catch (refreshError) { setActionError(refreshError.message); }
    finally { setPendingAction(''); }
  }

  async function openInvoiceDocument(kind) {
    if (!selected || pendingAction) return;
    setPendingAction(kind); setActionError('');
    try {
      const root = settlementApiRoot(isMerchant);
      await openDocumentInNewWindow(window.open.bind(window), async () => {
        const data = await apiFetch(`${root}/${encodeURIComponent(selected.id)}/tax-invoice/${kind === 'view' ? 'view-url' : 'pdf-url'}`, token);
        return data?.url;
      });
    } catch (documentError) { setActionError(documentError.message); }
    finally { setPendingAction(''); }
  }

  if (!selected) return <AdminPage title="매출 정산" description={isMerchant ? '업체별 월 정산과 증빙·입금 처리 현황을 확인합니다.' : '우리 회사의 월별 청구와 세금계산서 처리 현황을 확인합니다.'} showHeader={false} preview={false} className="merchant-regular-weight merchant-open-table">
    {loadError && <div className="alert error" role="alert">{loadError} <button type="button" className="ghost" onClick={reload} disabled={loading}>다시 시도</button></div>}
    {loadWarning && <div className="alert warning" role="alert">{loadWarning} <button type="button" className="ghost" onClick={reload} disabled={loading}>다시 시도</button></div>}
    {notice && <div className="alert success" role="status" aria-live="polite">{notice}</div>}
    <div className="settlement-v2-title-actions"><span className="badge">월별 정산 목록</span></div>
    <div className="settlement-v2-periodbar"><div className="settlement-v2-months" role="tablist" aria-label="정산월"><button id="settlement-month-all-tab" type="button" role="tab" aria-selected={month === 'all'} aria-controls="settlement-month-panel" className={month === 'all' ? 'active' : ''} onClick={() => setMonth('all')}>전체</button>{Array.from({ length: 12 }, (_, index) => index + 1).map((value) => <button id={`settlement-month-${value}-tab`} type="button" role="tab" aria-selected={month === value} aria-controls="settlement-month-panel" key={value} className={month === value ? 'active' : ''} disabled={!availableMonths.has(value)} onClick={() => setMonth(value)}>{value}월</button>)}</div><div className="settlement-v2-year-control" aria-label="정산 연도"><button type="button" className="ghost" onClick={() => { setYear((value) => value - 1); setMonth('all'); }} aria-label="이전 연도">‹</button><strong>{year}</strong><button type="button" className="ghost" onClick={() => { setYear((value) => value + 1); setMonth('all'); }} aria-label="다음 연도">›</button></div></div>
    <div className="settlement-v2-guide"><span>· 매출 금액은 매일 1회 업데이트됩니다.</span><span>· 고객사와 직접거래가 있는 경우 정산금액에서 제외되어 노출됩니다.</span></div>
    <article id="settlement-month-panel" aria-labelledby={month === 'all' ? 'settlement-month-all-tab' : `settlement-month-${month}-tab`} className="panel settlement-v2-list-panel" role="tabpanel">{loadedRows === null ? <SettlementV2Empty text="정산 내역을 불러오는 중입니다"/> : <><div className="table-wrap"><table className="settlement-v2-table"><thead><tr><th>정산월</th><th>{isMerchant ? '업체명' : '공급자'}</th><th className="money">정산금액</th><th>정산</th><th>세금계산서</th><th>입금</th><th>주요 액션</th></tr></thead><tbody>{visibleRows.map((row) => { const displayRecipient = recipientFor(row); return <tr key={row.id} className="settlement-v2-clickable-row" onClick={() => openSettlement(row)}><td><button type="button" className="settlement-v2-row-link" aria-label={`${row.period_start.slice(0, 7)} ${displayRecipient.name}${row.is_demo ? ' 시연' : ''} 정산서 상세 보기`} onClick={(event) => { event.stopPropagation(); openSettlement(row); }}>{row.period_start.slice(0, 7)}{row.is_demo ? ' · 시연' : ''}</button></td><td>{(isMerchant ? displayRecipient.name : row.supplier.name) || '확인 필요'}</td><td className="money">{krw(row.total_amount)}</td><td><SettlementV2Status type="settlement" value={row.settlement_status}/></td><td><SettlementV2Status type="invoice" value={row.tax_invoice_status}/></td><td><SettlementV2Status type="payment" value={row.payment_status}/></td><td><button type="button" className="ghost settlement-v2-inline-action" onClick={(event) => { event.stopPropagation(); openSettlement(row); }}>{row.is_demo ? '시연 상세 보기' : !isMerchant && canConfirmAndRequest(row) ? '정산 내용 확인 및 세금계산서 발급 요청' : isMerchant && row.settlement_status === 'draft' ? '업체에 정산서 발송' : isMerchant && row.settlement_status === 'revising' ? '업체에 정산서 재발송' : isMerchant && canMerchantBeginRevision(row) ? '정산서 수정 시작' : '상세 보기'}</button></td></tr>; })}</tbody></table></div>{visibleRows.length === 0 && <SettlementV2Empty />}</>}</article>
  </AdminPage>;

  const invoiceAvailable = !selected.is_demo && ['issued', 'nts_sending', 'nts_accepted'].includes(selected.tax_invoice_status);
  const companyCanRequest = !isMerchant && canConfirmAndRequest(selected);
  const companyCanDispute = !isMerchant && canCompanyDispute(selected);
  const merchantCanSend = isMerchant && canMerchantSend(selected);
  const merchantCanBeginRevision = isMerchant && canMerchantBeginRevision(selected);
  const merchantCanIssue = isMerchant && canMerchantIssue(selected);
  const merchantCanMarkPaid = isMerchant && canMerchantMarkPaid(selected);
  return <AdminPage title={null} description="" showHeader={false} preview={false} className="merchant-regular-weight merchant-open-table">

    {loadError && <div className="alert error" role="alert">{loadError} <button type="button" className="ghost" onClick={retrySelectedDetail} disabled={Boolean(pendingAction)}>다시 시도</button></div>}
    {loadWarning && <div className="alert warning" role="alert">{loadWarning} <button type="button" className="ghost" onClick={retrySelectedDetail} disabled={Boolean(pendingAction)}>다시 시도</button></div>}
    {actionError && <div className="alert error" role="alert" aria-live="assertive">{actionError} <button type="button" className="ghost" onClick={retrySelectedDetail} disabled={Boolean(pendingAction)}>다시 시도</button></div>}
    {notice && <div className="alert success" role="status" aria-live="polite">{notice}</div>}
    {selected.is_demo && <div className="alert warning" role="status">시연 정산입니다. 단계 진행과 초기화는 공급자 정보의 정산·세금계산서 시연 영역에서만 할 수 있습니다.</div>}
    <div className="settlement-v2-detailbar"><button ref={backButtonRef} type="button" className="ghost" disabled={Boolean(pendingAction)} onClick={() => { evidenceRequestRef.current += 1; selectedIdRef.current = null; setEvidenceLoading(false); setSelectedId(null); setNotice(''); setActionError(''); }}>‹ 뒤로</button><div className="settlement-v2-detail-actions">{!selected.is_demo && <button type="button" className="ghost" onClick={() => setNotice('정산자료 엑셀 다운로드는 현재 제공되지 않습니다.')}><Download size={16}/> 엑셀 다운로드</button>}{invoiceAvailable && <><button type="button" className="ghost" disabled={Boolean(pendingAction)} onClick={() => openInvoiceDocument('view')}><FileText size={16}/> 보기</button><button type="button" className="ghost" disabled={Boolean(pendingAction)} onClick={() => openInvoiceDocument('pdf')}><Download size={16}/> PDF</button></>}{isMerchant && canRefreshInvoiceStatus(selected) && <button type="button" className="ghost" disabled={Boolean(pendingAction)} onClick={refreshInvoiceStatus}><RefreshCw size={16}/> 상태 새로고침</button>}{merchantCanSend && <button ref={actionButtonRef} type="button" className="primary" disabled={Boolean(pendingAction)} onClick={() => settlementWorkflowAction('send')}>{selected.settlement_status === 'revising' ? '업체에 정산서 재발송' : '업체에 정산서 발송'}</button>}{merchantCanBeginRevision && <button ref={actionButtonRef} type="button" className="primary" disabled={Boolean(pendingAction)} onClick={() => settlementWorkflowAction('begin-revision')}>정산서 수정 시작</button>}{merchantCanIssue && <button ref={actionButtonRef} type="button" className="primary" disabled={Boolean(pendingAction)} onClick={() => { setConfirmChecks([false, false, false]); dialogReturnRef.current = actionButtonRef.current; setDialog('issue'); }}>세금계산서 발행</button>}{companyCanRequest && <button ref={actionButtonRef} type="button" className="primary" disabled={!recipientReady || Boolean(pendingAction)} onClick={() => { setConfirmChecks([false, false, false]); dialogReturnRef.current = actionButtonRef.current; setDialog('request'); }}>정산 내용 확인 및 세금계산서 발급 요청</button>}{companyCanDispute && <button type="button" className="ghost" disabled={Boolean(pendingAction)} onClick={() => { disputeIdempotencyKeyRef.current = crypto.randomUUID(); setDisputeReason(''); setActionError(''); setDialog('dispute'); }}>정산 내용 이의 제기</button>}{merchantCanMarkPaid && <button ref={actionButtonRef} type="button" className="ghost" disabled={Boolean(pendingAction)} onClick={() => { paymentIdempotencyKeyRef.current = crypto.randomUUID(); setPaymentForm(paymentFormForSettlement(selected)); setActionError(''); dialogReturnRef.current = actionButtonRef.current; setDialog('payment'); }}>입금 등록</button>}</div></div>
    {!isMerchant && !recipientReady && <div className="alert warning" role="alert">정산 확정에 필요한 회사 정보(사업자 정보, 세금계산서 이메일, 담당자명·연락처)가 미완성입니다. <button type="button" className="ghost" onClick={onCompanyInfo}>회사 정보에서 입력하기</button></div>}
    <article className="panel settlement-v2-overview">
      <div className="settlement-v2-overview-row"><span>정산 요약</span><div className="settlement-v2-summary-grid"><div><small>공급자</small><strong>{selected.supplier.name}</strong></div><div><small>정산금액</small><strong className="money">{krw(selected.total_amount)}</strong></div><div><small>정산</small><SettlementV2Status type="settlement" value={selected.settlement_status}/></div><div><small>세금계산서</small><SettlementV2Status type="invoice" value={selected.tax_invoice_status}/></div><div><small>입금</small><SettlementV2Status type="payment" value={selected.payment_status}/></div></div></div>
      <div className="settlement-v2-overview-row"><span>정산 기간</span><strong>{selected.period_start} ~ {selected.period_end}</strong></div>
      <div className="settlement-v2-overview-row"><span>금액 구성</span><div className="settlement-v2-amounts"><div><small>공급가액</small><strong className="money">{krw(selected.supply_amount)}</strong></div><div><small>부가세</small><strong className="money">{krw(selected.vat_amount)}</strong></div><div><small>합계</small><strong className="money">{krw(selected.total_amount)}</strong></div></div></div>
      <div className="settlement-v2-overview-row"><span>입금 정보</span><div className="settlement-v2-account-summary"><span>은행 <strong>{selected.payment.bank_name || '미설정/확인 필요'}</strong></span><span>계좌번호 <strong>{selected.payment.account_number || '미설정/확인 필요'}</strong></span><span>예금주 <strong>{selected.payment.account_holder || '미설정/확인 필요'}</strong></span><span>입금 예정일 <strong>{selected.due_date || '확인 필요'}</strong></span>{!isMerchant && <small>회사에서는 입금 정보를 조회만 할 수 있습니다.</small>}</div></div>

      <div className="settlement-v2-overview-row"><span>공급받는자 정보</span><dl className="settlement-v2-business"><div><dt>상호</dt><dd>{profileRecipient.name || '확인 필요'}</dd></div><div><dt>사업자번호</dt><dd>{profileRecipient.biz_reg_no || '확인 필요'}</dd></div><div><dt>종사업장번호</dt><dd>{profileRecipient.branch_no || '해당 없음'}</dd></div><div><dt>대표자명</dt><dd>{profileRecipient.representative_name || '확인 필요'}</dd></div><div><dt>주소</dt><dd>{profileRecipient.address || '확인 필요'}</dd></div><div><dt>업태</dt><dd>{profileRecipient.business_type || '확인 필요'}</dd></div><div><dt>종목</dt><dd>{profileRecipient.business_item || '확인 필요'}</dd></div><div><dt>세금계산서 이메일</dt><dd>{profileRecipient.tax_invoice_email || '확인 필요'}</dd></div></dl></div>
      {invoiceAvailable && <div className="settlement-v2-overview-row"><span>세금계산서 메타데이터</span><dl className="settlement-v2-business"><div><dt>작성일자</dt><dd>{selected.invoice?.written_at || '미확정'}</dd></div><div><dt>발행일시</dt><dd>{formatKoreanTimestamp(selected.invoice?.issued_at)}</dd></div><div><dt>승인번호</dt><dd>{selected.invoice?.approval_number || '미수신'}</dd></div></dl></div>}
      {selected.tax_invoice_status === 'failed' && <div className="settlement-v2-overview-row"><span>실패 사유</span><strong className="settlement-v2-error-text">{selected.invoice?.failed_reason || '확인 필요'}</strong></div>}
    </article>
    <div className="settlement-v2-tabs" role="tablist" aria-label="정산서 상세"><button id="settlement-evidence-tab" type="button" role="tab" aria-selected={detailTab === 'evidence'} aria-controls="settlement-evidence-panel" className={detailTab === 'evidence' ? 'active' : ''} onClick={() => setDetailTab('evidence')}>증빙 내역</button><button id="settlement-deposits-tab" type="button" role="tab" aria-selected={detailTab === 'deposits'} aria-controls="settlement-deposits-panel" className={detailTab === 'deposits' ? 'active' : ''} onClick={() => setDetailTab('deposits')}>입금/이체 내역</button></div>
    {detailTab === 'evidence' && <article id="settlement-evidence-panel" aria-labelledby="settlement-evidence-tab" role="tabpanel" className="panel"><div className="panel-title"><div><h3>해당 정산 기간 사용 내역</h3><p className="panel-note">{evidenceLoading ? '사용 내역을 불러오는 중입니다.' : `${selected.period_start} ~ ${selected.period_end} · ${evidenceRows.length}건 · 합계 ${krw(evidenceTotal)}`}</p></div></div><div className="table-wrap"><table><thead><tr><th>거래 일시</th><th>이름</th><th>부서/사번</th><th>구분</th><th>메뉴/내역</th><th className="money">공급가액</th><th className="money">부가세</th><th className="money">합계</th><th>거래번호</th></tr></thead><tbody>{evidenceRows.map((row) => <tr key={row.id}><td>{formatKoreanTimestamp(row.created_at)}</td><td>{row.employee_name}</td><td>{[row.department, row.employee_no].filter(Boolean).join(' / ') || '-'}</td><td>{row.kind === 'spend' ? (row.pay_type === 'subsidized' ? '보조금' : '장부') : row.kind === 'refund' ? '환불' : '취소'}</td><td>{row.item}</td><td className="money">{krw(row.supply_amount)}</td><td className="money">{krw(row.vat_amount)}</td><td className="money">{krw(row.total_amount)}</td><td>{row.tx_code || '-'}</td></tr>)}</tbody></table></div>{evidenceRows.length === 0 && <SettlementV2Empty text={evidenceLoading ? '사용 내역을 불러오는 중입니다' : '해당 정산 기간의 사용 내역이 없습니다'} />}</article>}
    {detailTab === 'deposits' && <article id="settlement-deposits-panel" aria-labelledby="settlement-deposits-tab" role="tabpanel" className="panel"><div className="panel-title"><div><h3>입금 내역 (금액: {krw(depositedAmount)})</h3><p className="panel-note">입금 계좌와 이체 내역입니다.{!isMerchant && ' 회사 관리자는 조회만 할 수 있습니다.'}</p></div></div><div className="settlement-v2-account"><span>은행 <strong>{selected.payment.bank_name || '미설정/확인 필요'}</strong></span><span>계좌번호 <strong>{selected.payment.account_number || '미설정/확인 필요'}</strong></span><span>예금주 <strong>{selected.payment.account_holder || '미설정/확인 필요'}</strong></span><span>입금 예정일 <strong>{selected.due_date || '확인 필요'}</strong></span></div><div className="table-wrap"><table><thead><tr><th>거래 일시</th><th className="money">입금액(원)</th><th>적요</th></tr></thead><tbody>{depositRows.map((row, index) => <tr key={`${row[0]}-${index}`}><td>{row[0]}</td><td className="money">{krw(row[1])}</td><td>{row[2]}</td></tr>)}</tbody></table></div>{depositRows.length === 0 && <SettlementV2Empty />}</article>}
    {dialog === 'dispute' && <div className="modal-backdrop" onClick={closeDialog}><section ref={dialogRef} className="invite-modal mock-tax-modal" role="dialog" aria-modal="true" aria-labelledby="settlement-dispute-dialog-title" onClick={(event) => event.stopPropagation()} onKeyDown={handleDialogKeyDown}><div className="modal-head"><div><span className="eyebrow">DISPUTE</span><h2 id="settlement-dispute-dialog-title">정산 내용 이의 제기</h2></div><button type="button" className="ghost" aria-label="닫기" onClick={closeDialog} disabled={Boolean(pendingAction)}><X size={18}/></button></div><p className="panel-note">업체가 확인하고 수정할 수 있도록 금액 또는 내역의 문제를 구체적으로 입력해 주세요.</p>{actionError && <div className="alert error" role="alert">{actionError}</div>}<form className="form" onSubmit={disputeSettlement}><label>이의 제기 사유<textarea rows="5" maxLength="1000" value={disputeReason} onChange={(event) => setDisputeReason(event.target.value)} disabled={Boolean(pendingAction)} required autoFocus/></label><div className="actions"><button type="button" className="ghost" onClick={closeDialog} disabled={Boolean(pendingAction)}>취소</button><button type="submit" className="primary" disabled={!disputeReason.trim() || Boolean(pendingAction)}>{pendingAction === 'dispute' ? '제출 중...' : '정산 내용 이의 제기'}</button></div></form></section></div>}
    {dialog === 'payment' && <div className="modal-backdrop" onClick={closeDialog}><section ref={dialogRef} className="invite-modal mock-tax-modal" role="dialog" aria-modal="true" aria-labelledby="settlement-payment-dialog-title" onClick={(event) => event.stopPropagation()} onKeyDown={handleDialogKeyDown}><div className="modal-head"><div><span className="eyebrow">PAYMENT</span><h2 id="settlement-payment-dialog-title">입금 내역 등록</h2></div><button type="button" className="ghost" aria-label="닫기" onClick={closeDialog} disabled={Boolean(pendingAction)}><X size={18}/></button></div><p className="panel-note">서버에 실제 입금 내역을 등록합니다. 현재 입금액 {krw(depositedAmount)}, 남은 금액 {krw(Math.max(0, selected.total_amount - depositedAmount))}</p>{actionError && <div className="alert error" role="alert" aria-live="assertive">{actionError}</div>}<form className="form" onSubmit={markPaid}><label>입금액(원)<input type="number" min="1" step="1" inputMode="numeric" value={paymentForm.amount} onChange={(event) => setPaymentForm((current) => ({ ...current, amount: event.target.value }))} disabled={Boolean(pendingAction)} required autoFocus/></label><label>입금자명<input value={paymentForm.depositor_name} onChange={(event) => setPaymentForm((current) => ({ ...current, depositor_name: event.target.value }))} disabled={Boolean(pendingAction)} required/></label><label>입금 일시<input type="datetime-local" value={paymentForm.deposited_at} onChange={(event) => setPaymentForm((current) => ({ ...current, deposited_at: event.target.value }))} disabled={Boolean(pendingAction)} required/></label><label>메모 (선택)<textarea rows="3" value={paymentForm.memo} onChange={(event) => setPaymentForm((current) => ({ ...current, memo: event.target.value }))} disabled={Boolean(pendingAction)}/></label><dl className="settlement-v2-business settlement-v2-dialog-business" aria-label="입금 등록 내용 검토"><div><dt>정산 기간</dt><dd>{selected.period_start} ~ {selected.period_end}</dd></div><div><dt>등록 금액</dt><dd>{krw(Number(paymentForm.amount) || 0)}</dd></div><div><dt>입금자</dt><dd>{paymentForm.depositor_name || '확인 필요'}</dd></div><div><dt>입금 일시</dt><dd>{paymentForm.deposited_at || '확인 필요'}</dd></div></dl><div className="modal-actions"><button type="button" className="ghost" onClick={closeDialog} disabled={Boolean(pendingAction)}>취소</button><button type="submit" className="primary" disabled={Boolean(pendingAction)}>{pendingAction === 'paid' ? '등록 중...' : '입금 등록'}</button></div></form></section></div>}
    {dialog && !['payment', 'dispute'].includes(dialog) && <div className="modal-backdrop" onClick={closeDialog}><section ref={dialogRef} className="invite-modal mock-tax-modal" role="dialog" aria-modal="true" aria-labelledby="settlement-v2-dialog-title" onClick={(event) => event.stopPropagation()} onKeyDown={handleDialogKeyDown}><div className="modal-head"><div><span className="eyebrow">TAX INVOICE · POPBILL</span><h2 id="settlement-v2-dialog-title">{isMerchant ? '세금계산서 발행' : '정산 내용 확인 및 세금계산서 발급 요청'}</h2></div><button type="button" className="ghost" aria-label="닫기" onClick={closeDialog} autoFocus><X size={18}/></button></div><div className="alert warning">실제 세금계산서 발행 또는 발급 요청입니다. 표시된 사업자 정보와 금액을 확인해 주세요.</div><div className="mock-invoice-parties"><article><span>공급자</span><strong>{selected.supplier.name}</strong><small>{selected.supplier.biz_reg_no || '사업자번호 확인 필요'} · {selected.supplier.representative_name || '대표자 확인 필요'}</small></article><article><span>공급받는자</span><strong>{profileRecipient.name || '확인 필요'}</strong><small>{profileRecipient.biz_reg_no || '사업자번호 확인 필요'} · {profileRecipient.representative_name || '대표자 확인 필요'}</small></article></div><dl className="settlement-v2-business settlement-v2-dialog-business"><div><dt>상호</dt><dd>{profileRecipient.name || '확인 필요'}</dd></div><div><dt>사업자등록번호</dt><dd>{profileRecipient.biz_reg_no || '확인 필요'}</dd></div><div><dt>종사업장번호</dt><dd>{profileRecipient.branch_no || '해당 없음'}</dd></div><div><dt>대표자</dt><dd>{profileRecipient.representative_name || '확인 필요'}</dd></div><div><dt>사업장 주소</dt><dd>{profileRecipient.address || '확인 필요'}</dd></div><div><dt>업태</dt><dd>{profileRecipient.business_type || '확인 필요'}</dd></div><div><dt>종목</dt><dd>{profileRecipient.business_item || '확인 필요'}</dd></div><div><dt>수신 이메일</dt><dd>{profileRecipient.tax_invoice_email || '확인 필요'}</dd></div></dl><div className="table-wrap"><table><thead><tr><th>품목</th><th className="money">공급가액</th><th className="money">부가세</th><th className="money">합계</th><th>작성일자</th></tr></thead><tbody><tr><td>{selected.period_start.slice(0, 7)} 식대(월합계)</td><td className="money">{krw(selected.supply_amount)}</td><td className="money">{krw(selected.vat_amount)}</td><td className="money">{krw(selected.total_amount)}</td><td>{selected.period_end || '미확정'}</td></tr></tbody></table></div>{!isMerchant && <fieldset className="settlement-v2-confirmations"><legend>확정 전 필수 확인</legend>{['정산 기간과 정산금액을 확인했습니다.', '공급받는자 사업자 정보와 수신 이메일을 확인했습니다.', '정산 확정과 세금계산서 발급 요청이 동시에 처리됨에 동의합니다.'].map((label, index) => <label key={label}><input type="checkbox" checked={confirmChecks[index]} onChange={(event) => setConfirmChecks((current) => current.map((value, currentIndex) => currentIndex === index ? event.target.checked : value))}/><span>{label}</span></label>)}</fieldset>}<div className="modal-actions"><button type="button" className="ghost" onClick={closeDialog}>닫기</button><button type="button" className="primary" onClick={confirmInvoiceAction} disabled={Boolean(pendingAction) || (!isMerchant && (!recipientReady || !confirmChecks.every(Boolean)))}>{isMerchant ? '발행 요청' : '정산 내용 확인 및 세금계산서 발급 요청'}</button></div></section></div>}
  </AdminPage>;
}

function MerchantSettlementScreen({ token }) {
  return <SettlementV2Screen viewer="merchant" token={token} />;
}

function CompanySettlementScreen({ token, company, onCompanyInfo }) {
  return <SettlementV2Screen viewer="company" token={token} companyProfile={company} onCompanyInfo={onCompanyInfo} />;
}

function SettlementEvidencePanel({ settlementRows }) {
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [kind, setKind] = useState('전체');
  const [type, setType] = useState('전체');
  const [notice, setNotice] = useState('');
  const evidenceRecords = settlementRows.filter((row) => ['issued', 'nts_sending', 'nts_accepted'].includes(row.tax_invoice_status)).map(settlementV2Evidence);
  const evidenceYears = [...new Set([String(new Date().getFullYear()), ...evidenceRecords.map((row) => row.writtenAt.slice(0, 4))])].sort().reverse();
  const rows = evidenceRecords.filter((row) => row.writtenAt.startsWith(year) && (kind === '전체' || row.kind === kind) && (type === '전체' || row.type === type));
  return <section id="tax-invoice-evidence-panel" role="tabpanel" aria-labelledby="tax-invoice-evidence-tab">
    {notice && <div className="alert success">{notice}</div>}
    <article className="panel"><div className="settlement-v2-evidence-head"><div className="settlement-v2-evidence-filters"><label>조회기간<select value={year} onChange={(event) => setYear(event.target.value)}>{evidenceYears.map((value) => <option key={value}>{value}</option>)}</select></label><label>증빙 구분<select value={kind} onChange={(event) => setKind(event.target.value)}><option>전체</option><option>매출</option><option>매입</option></select></label><label>증빙 유형<select value={type} onChange={(event) => setType(event.target.value)}><option>전체</option><option>세금계산서</option><option>현금영수증</option><option>카드</option></select></label></div><button type="button" className="primary" onClick={() => setNotice('증빙내역 엑셀 다운로드는 현재 제공되지 않습니다.')}><Download size={16}/> 부가가치세 신고 참고자료 엑셀 다운로드</button></div><div className="settlement-v2-guide"><span>· 조회기간은 각 증빙의 작성일자 기준입니다.</span><span>· 국세청 부가가치세 신고 참고자료로써 증빙내역을 표시합니다. 상세는 매출 정산에서 확인해 주세요.</span></div><div className="table-wrap"><table><thead><tr><th>증빙 구분</th><th>품목명</th><th>증빙 유형</th><th>공급받는자</th><th>발급수단(사업자)번호</th><th className="money">공급가액</th><th className="money">부가세</th><th className="money">총액</th><th>작성일자</th><th>승인번호</th><th>승인일자</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td><SettlementV2Status value={row.kind}/></td><td>{row.item}</td><td>{row.type}</td><td>{row.recipient}</td><td>{row.bizNo}</td><td className="money">{krw(row.supply)}</td><td className="money">{krw(row.vat)}</td><td className="money">{krw(row.total)}</td><td>{row.writtenAt}</td><td>{row.approvalNo}</td><td>{row.approvedAt}</td></tr>)}</tbody></table></div>{rows.length === 0 && <SettlementV2Empty text="증빙 내역이 없습니다"/>}</article>
  </section>;
}

function MerchantTaxInvoiceScreen({ token, initialTab = 'issue' }) {
  const { rows: loadedItems, error: loadError, warning: loadWarning, loading, reload } = useSettlementV2Rows(token, true);
  const items = loadedItems ?? [];
  const [notice, setNotice] = useState('');
  const [activeTab, setActiveTab] = useState(initialTab);
  const [issueError, setIssueError] = useState('');
  const [pendingId, setPendingId] = useState('');
  async function mutate(id, action) {
    if (pendingId) return;
    setPendingId(id); setIssueError(''); setNotice('');
    try {
      await apiFetch(`/admin/merchant/settlements/${encodeURIComponent(id)}/tax-invoice/${action}`, token, { method: 'POST', body: '{}' });
      setNotice(action === 'issue'
        ? '세금계산서 발행 요청을 처리했습니다. 결과가 불명확하거나 처리 중이면 상태 새로고침으로 확인해 주세요.'
        : '팝빌과 국세청 처리 상태를 새로고침했습니다.');
      reload();
    } catch (mutationError) {
      setIssueError(mutationError.code === 'POPBILL_RECONCILIATION_REQUIRED'
        ? '발행 결과가 불명확합니다. 중복 발행하지 말고 상태 새로고침으로 팝빌 결과를 확인해 주세요.'
        : mutationError.message);
      reload();
    } finally { setPendingId(''); }
  }
  function handleTabKeyDown(event) {
    let nextTab = null;
    if (event.key === 'Home') nextTab = 'issue';
    else if (event.key === 'End') nextTab = 'evidence';
    else if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      nextTab = activeTab === 'issue' ? 'evidence' : 'issue';
    }
    if (!nextTab) return;
    event.preventDefault();
    setActiveTab(nextTab);
    event.currentTarget.parentElement
      ?.querySelector(`#tax-invoice-${nextTab}-tab`)
      ?.focus();
  }
  return <AdminPage title="세금계산서" description="발행 관리부터 완료된 증빙 조회까지 한곳에서 처리합니다." showHeader={false} preview={false} className="merchant-regular-weight merchant-open-table">
    {loadError && <div className="alert error" role="alert">{loadError} <button type="button" className="ghost" onClick={reload} disabled={loading}>다시 시도</button></div>}
    {loadWarning && <div className="alert warning" role="alert">{loadWarning} <button type="button" className="ghost" onClick={reload} disabled={loading}>다시 시도</button></div>}
    {issueError && <div className="alert error" role="alert">{issueError} <button type="button" className="ghost" onClick={reload} disabled={loading || Boolean(pendingId)}>다시 시도</button></div>}
    {notice && <div className="alert success" role="status" aria-live="polite">{notice}</div>}
    <div className="settlement-v2-tabs" role="tablist" aria-label="세금계산서 관리">
      <button id="tax-invoice-issue-tab" type="button" role="tab" aria-selected={activeTab === 'issue'} aria-controls="tax-invoice-issue-panel" tabIndex={activeTab === 'issue' ? 0 : -1} className={activeTab === 'issue' ? 'active' : ''} onKeyDown={handleTabKeyDown} onClick={() => setActiveTab('issue')}>발행 관리</button>
      <button id="tax-invoice-evidence-tab" type="button" role="tab" aria-selected={activeTab === 'evidence'} aria-controls="tax-invoice-evidence-panel" tabIndex={activeTab === 'evidence' ? 0 : -1} className={activeTab === 'evidence' ? 'active' : ''} onKeyDown={handleTabKeyDown} onClick={() => setActiveTab('evidence')}>발행 완료·증빙 내역</button>
    </div>
    {activeTab === 'issue' && <article id="tax-invoice-issue-panel" role="tabpanel" aria-labelledby="tax-invoice-issue-tab" className="panel">{loadedItems === null ? <SettlementV2Empty text="세금계산서 내역을 불러오는 중입니다"/> : <><div className="table-wrap"><table><thead><tr><th>정산월</th><th>업체명</th><th className="money">공급가액</th><th className="money">부가세</th><th>상태</th><th>처리</th></tr></thead><tbody>{items.map((item) => { const legal = canMerchantIssue(item); const refreshable = canRefreshInvoiceStatus(item); return <tr key={item.id}><td>{item.period_start.slice(0, 7)}</td><td><strong>{item.recipient.name || '확인 필요'}</strong></td><td className="money">{krw(item.supply_amount)}</td><td className="money">{krw(item.vat_amount)}</td><td><SettlementV2Status type="invoice" value={item.tax_invoice_status}/></td><td><div className="row-actions">{legal && <button type="button" className="ghost" disabled={Boolean(pendingId)} onClick={() => mutate(item.id, 'issue')}>발행</button>}{refreshable && <button type="button" className="ghost" disabled={Boolean(pendingId)} onClick={() => mutate(item.id, 'refresh-status')}><RefreshCw size={14}/> 상태 새로고침</button>}{!legal && !refreshable && <span className="panel-note">처리 불가</span>}</div></td></tr>; })}</tbody></table></div>{items.length === 0 && <SettlementV2Empty />}</>}</article>}
    {activeTab === 'evidence' && <SettlementEvidencePanel settlementRows={items} />}
  </AdminPage>;
}
function MerchantPrepurchaseScreen({ token, onChanged, refreshVersion }) {
  const [items, setItems] = useState([]);
  const [loadState, setLoadState] = useState('loading');
  const [loadError, setLoadError] = useState('');
  const [chargeError, setChargeError] = useState('');
  const [notice, setNotice] = useState('');
  const [chargeItem, setChargeItem] = useState(null);
  const [chargeForm, setChargeForm] = useState({ quantity: '', unit_price: '' });
  const [chargeTouched, setChargeTouched] = useState({ quantity: false, unit_price: false });
  const [charging, setCharging] = useState(false);
  const chargeRequestKeyRef = useRef(null);
  const chargeTriggerRef = useRef(null);
  const quantityInputRef = useRef(null);
  const readGenerationRef = useRef(0);

  async function loadPrepurchaseItems(signal) {
    const generation = ++readGenerationRef.current;
    setLoadState('loading');
    setLoadError('');
    try {
      const data = await apiFetch('/admin/merchant/prepurchases', token, signal ? { signal } : {});
      if (signal?.aborted || generation !== readGenerationRef.current) return;
      setItems(prepurchaseItems(data));
      setLoadState('loaded');
    } catch (error) {
      if (error.name === 'AbortError' || signal?.aborted || generation !== readGenerationRef.current) return;
      setLoadError(error.message);
      setLoadState('failed');
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    loadPrepurchaseItems(controller.signal);
    return () => {
      controller.abort();
      readGenerationRef.current += 1;
    };
  }, [token, refreshVersion]);

  useEffect(() => {
    if (chargeItem) quantityInputRef.current?.focus();
  }, [chargeItem]);

  useEffect(() => {
    if (!chargeItem) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === 'Escape' && !charging) {
        event.preventDefault();
        closeCharge();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [chargeItem, charging]);

  function closeCharge(eventOrForce) {
    const force = eventOrForce === true;
    if (charging && !force) return;
    setChargeItem(null);
    setChargeError('');
    chargeRequestKeyRef.current = null;
    window.requestAnimationFrame(() => chargeTriggerRef.current?.focus());
  }

  function openCharge(item, trigger) {
    setNotice('');
    setChargeError('');
    chargeTriggerRef.current = trigger;
    chargeRequestKeyRef.current = crypto.randomUUID();
    setChargeItem(item);
    setChargeForm({ quantity: '', unit_price: item.unit_price == null ? '' : String(item.unit_price) });
    setChargeTouched({ quantity: false, unit_price: false });
  }

  function updateChargeField(field, value) {
    setChargeForm((form) => {
      if (form[field] === value) return form;
      chargeRequestKeyRef.current = crypto.randomUUID();
      return { ...form, [field]: value };
    });
    setChargeTouched((touched) => ({ ...touched, [field]: true }));
  }

  async function submitCharge(event) {
    event.preventDefault();
    if (!chargeItem || !chargeRequestKeyRef.current || charging || prepurchaseChargeInvalid(chargeForm.quantity, chargeForm.unit_price)) {
      setChargeTouched({ quantity: true, unit_price: true });
      return;
    }
    setCharging(true);
    setChargeError('');
    setNotice('');
    try {
      await apiFetch(`/admin/merchant/companies/${encodeURIComponent(chargeItem.company_id)}/prepurchases`, token, {
        method: 'POST',
        body: JSON.stringify(prepurchaseChargePayload(chargeForm.quantity, chargeForm.unit_price, chargeRequestKeyRef.current)),
      });
      setCharging(false);
      closeCharge(true);
      setNotice('선구매 수량을 충전했어요.');
      await Promise.all([loadPrepurchaseItems(), onChanged?.()]);
    } catch (error) {
      const ambiguous = !error.status || error.status >= 500;
      setChargeError(ambiguous
        ? `${error.message} 충전 처리 상태가 불명확할 수 있습니다. 같은 요청을 안전하게 다시 시도할 수 있습니다.`
        : error.message);
    } finally {
      setCharging(false);
    }
  }

  const displayNumber = (value, suffix = '') => value == null ? '-' : `${Number(value).toLocaleString('ko-KR')}${suffix}`;
  const displayDate = (value) => {
    if (!value) return '-';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString('ko-KR');
  };
  const amount = prepurchaseChargeTotal(chargeForm.quantity, chargeForm.unit_price);
  const invalidCharge = prepurchaseChargeInvalid(chargeForm.quantity, chargeForm.unit_price);
  const quantityValue = Number(chargeForm.quantity);
  const unitPriceValue = Number(chargeForm.unit_price);
  const quantityInvalid = !Number.isInteger(quantityValue) || quantityValue <= 0 || quantityValue > PREPURCHASE_MAX_QUANTITY;
  const unitPriceInvalid = !Number.isInteger(unitPriceValue) || unitPriceValue <= 0 || unitPriceValue > PREPURCHASE_MAX_UNIT_PRICE;

  return <AdminPage title={null} description="선구매 계약 업체의 구매 및 잔여 수량을 관리합니다." preview={false} className="prepurchase-page merchant-regular-weight merchant-open-table">
    <article className="panel prepurchase-panel">
      {loadState === 'failed' && <div className="alert error" role="alert">{loadError} <button type="button" className="ghost" onClick={() => loadPrepurchaseItems()} disabled={charging}>다시 시도</button></div>}
      {notice && <div className="alert success" role="status">{notice}</div>}
      {loadState === 'loading' ? <p className="empty-state" role="status">선구매 내역을 불러오는 중입니다.</p> : loadState === 'loaded' && (items.length === 0 ? <p className="empty-state">선구매 계약이 설정된 업체가 없습니다.</p> : <div className="table-wrap prepurchase-table-wrap"><table><thead><tr><th>업체명</th><th>최근 구매일</th><th>구매 수량</th><th>단가</th><th>잔여량</th><th>충전 버튼</th></tr></thead><tbody>{items.map((item) => <tr key={item.merchant_company_id}><td><strong>{item.company_name}</strong></td><td>{displayDate(item.latest_purchase_at)}</td><td className="money">{displayNumber(item.purchase_quantity)}</td><td className="money">{item.unit_price == null ? '-' : krw(item.unit_price)}</td><td className="money">{displayNumber(item.remaining_quantity)}</td><td><button type="button" className="primary prepurchase-charge-button" onClick={(event) => openCharge(item, event.currentTarget)}>충전</button></td></tr>)}</tbody></table></div>)}
    </article>
    {chargeItem && <div className="modal-backdrop prepurchase-modal-backdrop" onClick={closeCharge}>
      <section className="invite-modal prepurchase-charge-modal merchant-regular-weight" role="dialog" aria-modal="true" aria-labelledby="prepurchase-charge-title" aria-describedby="prepurchase-charge-description" onClick={(event) => event.stopPropagation()}>
        <div className="panel-title"><div><h2 id="prepurchase-charge-title">충전</h2><p id="prepurchase-charge-description" className="panel-note">{chargeItem.company_name}의 충전 수량과 단가를 입력해 주세요.</p></div><button type="button" className="ghost icon-button" aria-label="닫기" onClick={closeCharge} disabled={charging}><X size={20}/></button></div>
        {chargeError && <div className="alert error" role="alert">{chargeError}</div>}
        <form className="prepurchase-charge-form" onSubmit={submitCharge}>
          <label>잔여량<input value={displayNumber(chargeItem.remaining_quantity)} readOnly /></label>
          <label>구매 수량<input ref={quantityInputRef} type="number" inputMode="numeric" min="1" max={PREPURCHASE_MAX_QUANTITY} step="1" value={chargeForm.quantity} onChange={(event) => updateChargeField('quantity', event.target.value)} onBlur={() => setChargeTouched((value) => ({ ...value, quantity: true }))} aria-invalid={chargeTouched.quantity && quantityInvalid} aria-describedby="prepurchase-quantity-help" required /><span id="prepurchase-quantity-help" className={chargeTouched.quantity && quantityInvalid ? 'prepurchase-field-error' : 'panel-note'}>{chargeTouched.quantity && quantityInvalid ? '구매 수량은 1 이상 1,000,000 이하의 정수여야 합니다.' : '1 이상 1,000,000 이하의 정수를 입력하세요.'}</span></label>
          <label>단가<input type="number" inputMode="numeric" min="1" max={PREPURCHASE_MAX_UNIT_PRICE} step="1" value={chargeForm.unit_price} onChange={(event) => updateChargeField('unit_price', event.target.value)} onBlur={() => setChargeTouched((value) => ({ ...value, unit_price: true }))} aria-invalid={chargeTouched.unit_price && unitPriceInvalid} aria-describedby="prepurchase-unit-price-help" required /><span id="prepurchase-unit-price-help" className={chargeTouched.unit_price && unitPriceInvalid ? 'prepurchase-field-error' : 'panel-note'}>{chargeTouched.unit_price && unitPriceInvalid ? '단가는 1원 이상 10,000,000원 이하의 정수여야 합니다.' : '1원 이상 10,000,000원 이하의 정수를 입력하세요.'}</span></label>
          <label>금액<input value={krw(amount)} readOnly /></label>
          <button className="primary" disabled={charging || invalidCharge}>{charging ? '충전 중...' : '충전'}</button>
        </form>
      </section>
    </div>}
  </AdminPage>;
}
function MerchantCompanyListScreen({ items, onDetail }) {
  return <AdminPage title={null} description="연결 업체의 회사정보와 계약설정을 확인합니다." preview={false} className="company-list-page merchant-regular-weight merchant-open-table">
    <article className="panel">{items.length === 0 ? <p className="empty-state">연결된 업체가 없어요.</p> : <div className="table-wrap"><table><thead><tr><th>업체명</th><th>사업자등록번호</th><th>계약 유형</th><th>담당자 이메일</th><th>연락처</th><th>관리</th></tr></thead><tbody>{items.map((item) => {
      const company = item.company ?? {};
      const subsidy = item.contract?.subsidy_enabled;
      return <tr key={item.id}><td><strong>{company.name ?? '-'}</strong></td><td>{company.biz_reg_no ?? '-'}</td><td><span className={`payment-type-badge ${subsidy ? 'subsidized' : 'ledger'}`}>{subsidy ? '보조금' : '후불'}</span></td><td>{company.contact_email ?? item.invite?.email ?? '-'}</td><td>{company.contact_phone ?? '-'}</td><td><button type="button" className="ghost" onClick={() => onDetail(item)}>상세</button></td></tr>;
    })}</tbody></table></div>}</article>
  </AdminPage>;
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

function MerchantSupplierInfoScreen({ merchant, busy, onSave, onSettings, token }) {
  const emptyForm = { biz_reg_no: '', name: '', representative_name: '', address: '', business_type: '', business_item: '', owner_phone: '', tax_invoice_email: '', bank_name: '', account_number: '', account_holder: '' };
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

  return <AdminPage
    title={null}
    description="세금계산서와 정산 상세에 사용할 식당 정보를 관리합니다."
    className="supplier-info-page"
    preview={false}
    actions={<button type="button" className="account-settings-button supplier-settings-button" onClick={onSettings} aria-label="관리자 정보 설정" title="관리자 정보 설정"><Settings size={20}/></button>}
  >
    <form className="panel supplier-info-card" onSubmit={save}>
      <div className="panel-title supplier-info-card-title">
        <div className="supplier-edit-actions">
          <button type="button" className="ghost supplier-capsule-button" onClick={beginEdit} disabled={editing || busy}>수정</button>
          <button type="button" className="ghost supplier-capsule-button" onClick={cancelEdit} disabled={!editing || busy}>취소</button>
          <button type="submit" className="primary supplier-capsule-button" disabled={!editing || busy}>{busy ? '저장 중' : '저장'}</button>
        </div>
      </div>
      <section className="supplier-info-section" aria-labelledby="supplier-business-info-title">
        <h3 id="supplier-business-info-title">사업자 정보</h3>
        <div className="supplier-info-fields">
          <label>사업자등록번호<input value={draft.biz_reg_no} onChange={field('biz_reg_no')} disabled={!editing} required /></label>
          <label>상호<input value={draft.name} onChange={field('name')} disabled={!editing} required /></label>
          <label>대표자<input value={draft.representative_name} onChange={field('representative_name')} disabled={!editing} /></label>
          <label>주소<input value={draft.address} onChange={field('address')} disabled={!editing} /></label>
          <label>업태<input value={draft.business_type} onChange={field('business_type')} disabled={!editing} /></label>
          <label>종목<input value={draft.business_item} onChange={field('business_item')} disabled={!editing} /></label>
          <label>담당 전화번호<input type="tel" autoComplete="tel" value={draft.owner_phone} onChange={field('owner_phone')} disabled={!editing} required /></label>
          <label className="wide">세금계산서 담당 이메일<input type="email" value={draft.tax_invoice_email} onChange={field('tax_invoice_email')} disabled={!editing} /></label>
        </div>
      </section>
      <section className="supplier-info-section supplier-deposit-section" aria-labelledby="supplier-deposit-info-title">
        <div>
          <h3 id="supplier-deposit-info-title">입금 정보</h3>
          <p className="panel-note">정산 상세에 표시할 선택 정보입니다.</p>
        </div>
        <div className="supplier-info-fields">
          <label>은행명<input value={draft.bank_name} onChange={field('bank_name')} disabled={!editing} maxLength={80} /></label>
          <label>계좌번호<input value={draft.account_number} onChange={field('account_number')} disabled={!editing} maxLength={80} /></label>
          <label>예금주<input value={draft.account_holder} onChange={field('account_holder')} disabled={!editing} maxLength={80} /></label>
        </div>
      </section>
    </form>
    <LegacyTaxReviewPanel key={`legacy-payments-${token}`} token={token}/>
    <SettlementDemoPanel key={`settlement-demo-${token}`} token={token} apiFetch={apiFetch} openDocumentInNewWindow={openDocumentInNewWindow} krw={krw}/>
  </AdminPage>;
}

function MerchantScreen({ section, companyItems, onCompanyDetail, onCompaniesChanged, merchant, busy, onSaveSupplier, onSettings, token, scopeId, prepurchaseRefreshVersion }) {
  if (section === 'main') return <DashboardView kind="merchant" token={token} scopeId={scopeId}/>;
  if (section === 'company-list') return <MerchantCompanyListScreen items={companyItems} onDetail={onCompanyDetail} />;
  if (section === 'supplier-info') return <MerchantSupplierInfoScreen merchant={merchant} busy={busy} onSave={onSaveSupplier} onSettings={onSettings} token={token} />;
  if (section === 'prepurchase') return <MerchantPrepurchaseScreen token={token} onChanged={onCompaniesChanged} refreshVersion={prepurchaseRefreshVersion} />;
  if (section === 'settlement-evidence') return <MerchantTaxInvoiceScreen token={token} initialTab="evidence" />;
  const screens = {
    'settlements-by-company': MerchantSettlementScreen,
    'tax-invoices': MerchantTaxInvoiceScreen,
  };
  const Screen = screens[section];
  return Screen ? <Screen token={token} /> : null;
}

function CompanyUsagePeriod({ value, onChange, disabled }) {
  const maxYm = currentPeriodYm();
  const nextDisabled = disabled || value >= maxYm;
  return <div className="company-usage-period" aria-label="조회 월 선택">
    <button type="button" className="ghost" onClick={() => onChange(shiftPeriodYm(value, -1))} disabled={disabled} aria-label="이전 달">이전 달</button>
    <label><span className="sr-only">조회 월</span><input type="month" value={value} max={maxYm} onChange={(event) => event.target.value && onChange(event.target.value > maxYm ? maxYm : event.target.value)} disabled={disabled}/></label>
    <button type="button" className="ghost" onClick={() => onChange(shiftPeriodYm(value, 1))} disabled={nextDisabled} aria-label="다음 달">다음 달</button>
  </div>;
}

function CompanyUsageState({ loading, error, retry }) {
  if (loading) return <p className="empty-state" role="status">이용 현황을 불러오는 중입니다.</p>;
  if (error) return <div className="alert error" role="alert">{error} <button type="button" className="ghost" onClick={retry}>다시 시도</button></div>;
  return null;
}

const dashColors = ['#4C8BF5', '#8CB5FA'];

function kstDateParts(date = new Date()) {
  return Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(date).filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]));
}

function defaultDashboardPeriod(date = new Date()) {
  const { year, month, day } = kstDateParts(date);
  return { from: `${year}-${month}-01`, to: `${year}-${month}-${day}` };
}

function validDashboardDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value ?? '')) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function dashboardPeriodFromUrl() {
  const fallback = defaultDashboardPeriod();
  const params = new URLSearchParams(window.location.search);
  const from = params.get('from');
  const to = params.get('to');
  return validDashboardDate(from) && validDashboardDate(to) && from <= to ? { from, to } : fallback;
}

function dashNumber(value) {
  return value.toLocaleString('ko-KR');
}

function dashboardContractError() {
  return new Error('대시보드 응답 형식이 올바르지 않습니다. 다시 시도해 주세요.');
}

function assertDashboardObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw dashboardContractError();
  return value;
}

function assertDashboardKeys(value, expected) {
  const actual = Object.keys(value).sort();
  const keys = [...expected].sort();
  if (actual.length !== keys.length || actual.some((key, index) => key !== keys[index])) throw dashboardContractError();
}

function assertDashboardNumber(value, integer = false) {
  if (typeof value !== 'number' || !Number.isFinite(value) || (integer && !Number.isInteger(value))) throw dashboardContractError();
  return value;
}

function assertDashboardString(value) {
  if (typeof value !== 'string' || value.trim() === '') throw dashboardContractError();
  return value;
}

function mapDashboardSummary(payload) {
  const data = assertDashboardObject(payload);
  assertDashboardKeys(data, ['total_amount', 'total_amount_delta_pct', 'total_count', 'total_count_delta_pct', 'by_meal_type', 'top_companies_by_amount', 'top_companies_by_count', 'unit', 'series']);
  const totalAmount = assertDashboardNumber(data.total_amount, true);
  const totalCount = assertDashboardNumber(data.total_count, true);
  const delta = (value) => value === null ? null : assertDashboardNumber(value);
  if (!Array.isArray(data.by_meal_type) || !Array.isArray(data.top_companies_by_amount)
      || !Array.isArray(data.top_companies_by_count) || !Array.isArray(data.series)
      || !['day', 'week', 'month'].includes(data.unit)) throw dashboardContractError();
  const byMealType = data.by_meal_type.map((item) => {
    const row = assertDashboardObject(item);
    assertDashboardKeys(row, ['label', 'amount', 'count', 'ratio']);
    const ratio = assertDashboardNumber(row.ratio);
    if (ratio < 0 || ratio > 100) throw dashboardContractError();
    return {
      label: assertDashboardString(row.label),
      amount: assertDashboardNumber(row.amount, true),
      count: assertDashboardNumber(row.count, true),
      ratio,
    };
  });
  if (byMealType.length !== 2 || byMealType[0].label !== '중식' || byMealType[1].label !== '석식') throw dashboardContractError();
  const rankRows = (items, valueKey) => items.map((item) => {
    const row = assertDashboardObject(item);
    assertDashboardKeys(row, ['rank', 'name', valueKey]);
    return {
      rank: assertDashboardNumber(row.rank, true),
      name: assertDashboardString(row.name),
      [valueKey]: assertDashboardNumber(row[valueKey], true),
    };
  });
  const series = data.series.map((item) => {
    const row = assertDashboardObject(item);
    assertDashboardKeys(row, ['date', 'amount', 'count']);
    if (!validDashboardDate(row.date)) throw dashboardContractError();
    return { date: row.date, amount: assertDashboardNumber(row.amount, true), count: assertDashboardNumber(row.count, true) };
  });
  return {
    total_amount: totalAmount,
    total_amount_delta_pct: delta(data.total_amount_delta_pct),
    total_count: totalCount,
    total_count_delta_pct: delta(data.total_count_delta_pct),
    by_meal_type: byMealType,
    top_companies_by_amount: rankRows(data.top_companies_by_amount, 'amount'),
    top_companies_by_count: rankRows(data.top_companies_by_count, 'count'),
    unit: data.unit,
    series,
  };
}

function DashCardTitle({ children, Icon, tone }) {
  return <div className="dash-card-title"><span className={`dash-icon-badge dash-icon-${tone}`}><Icon size={19}/></span><h3>{children}</h3></div>;
}

function SummaryCard({ label, value, delta, money = false, Icon, tone }) {
  const direction = delta === null || delta === 0 ? '' : delta > 0 ? 'up' : 'down';
  return <article className={`dash-card dash-summary-card dash-summary-${tone}`}>
    <span className={`dash-icon-badge dash-icon-${tone}`}><Icon size={21}/></span>
    <div className="dash-summary-copy"><span>{label}</span>
    <strong>{money ? krw(value) : `${dashNumber(value)}건`}</strong>
    <small className={`dash-delta ${direction}`}>전 기간 대비 {delta === null ? '-' : `${delta > 0 ? '↑' : delta < 0 ? '↓' : ''} ${Math.abs(delta).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}%`}</small></div>
  </article>;
}

function DonutCard({ rows, total }) {
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const segments = rows.map((row, index) => {
    const arcRatio = Math.max(0, Math.min(1, row.ratio / 100));
    const segment = { ...row, arcRatio, color: dashColors[index % dashColors.length], offset };
    offset += arcRatio * circumference;
    return segment;
  });
  return <article className="dash-card dash-donut-card">
    <DashCardTitle Icon={Coffee} tone="blue">식사 구분</DashCardTitle>
    {rows.length === 0 ? <p className="dash-empty">조회 기간의 데이터가 없습니다.</p> : <div className="dash-donut-body">
      <svg className="dash-donut" viewBox="0 0 120 120" role="img" aria-label="식사 구분 도넛 차트">
        <circle cx="60" cy="60" r={radius} fill="none" stroke="#EEF2EF" strokeWidth="16" />
        {segments.map((row) => <circle key={`${row.label}-${row.color}`} cx="60" cy="60" r={radius} fill="none" stroke={row.color} strokeWidth="16" strokeDasharray={`${row.arcRatio * circumference} ${circumference}`} strokeDashoffset={-row.offset} transform="rotate(-90 60 60)" />)}
        <text x="60" y="57" textAnchor="middle" className="dash-donut-label">합계</text>
        <text x="60" y="72" textAnchor="middle" className="dash-donut-total">{dashNumber(total)}건</text>
      </svg>
      <ul className="dash-legend">{segments.map((row) => <li key={row.label}><i style={{ background: row.color }} /><span>{row.label}</span><strong>{row.ratio.toLocaleString('ko-KR', { maximumFractionDigits: 1 })}%</strong></li>)}</ul>
    </div>}
  </article>;
}

function RankTable({ title, rows, valueKey, money = false, secondHeader }) {
  return <article className="dash-card dash-detail-card"><div className="dash-table-heading"><h3>{title}</h3><span>(단위: {money ? '원' : '건'})</span></div>
    {rows.length === 0 ? <p className="dash-empty">조회 기간의 데이터가 없습니다.</p> : <div className="dash-table-wrap"><table><thead><tr><th>순위</th><th>{secondHeader}</th><th className="money">값</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.name}-${index}`} className={row.isTotal ? 'dash-total-row' : ''}><td>{row.isTotal ? '' : row.rank}</td><td>{row.name}</td><td className="money">{dashNumber(row[valueKey])}</td></tr>)}</tbody></table></div>}
  </article>;
}

function compactMoneyTick(value) {
  const absolute = Math.abs(value);
  if (absolute >= 1000000) return `${(value / 1000000).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}M`;
  if (absolute >= 1000) return `${(value / 1000).toLocaleString('ko-KR', { maximumFractionDigits: 0 })}K`;
  return dashNumber(value);
}

const MIN_POINT_GAP = 40;
const DASH_CHART_HEIGHT = 250;
const DASH_CHART_TOP = 18;
const DASH_CHART_BOTTOM = 42;
const DASH_CHART_SIDE = MIN_POINT_GAP / 2;

function dashboardUnitLabel(unit) {
  return unit === 'week' ? '주별' : unit === 'month' ? '월별' : '일별';
}

function dashboardAxisDate(value, unit) {
  const [year, month, day] = value.split('-').map(Number);
  if (unit === 'month') return `${year}.${String(month).padStart(2, '0')}`;
  if (unit === 'week') return `${String(month).padStart(2, '0')}월 ${Math.ceil(day / 7)}주`;
  return `${String(month).padStart(2, '0')}.${String(day).padStart(2, '0')}`;
}

function dashboardTooltipDate(value, unit) {
  const [year, month, day] = value.split('-').map(Number);
  if (unit === 'month') return `${year}년 ${month}월`;
  if (unit === 'week') return `${year}.${String(month).padStart(2, '0')}.${String(day).padStart(2, '0')} 시작 주`;
  return `${year}.${String(month).padStart(2, '0')}.${String(day).padStart(2, '0')}`;
}

function TrendChart({ title, series, unit, valueKey, money = false, color }) {
  const reactId = useId();
  const gradientId = `dash-area-${valueKey}-${reactId.replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const viewportRef = useRef(null);
  const [viewportWidth, setViewportWidth] = useState(0);
  const [hoveredIndex, setHoveredIndex] = useState(null);
  const values = series.map((row) => row[valueKey]);
  const minValue = Math.min(...values, 0);
  const maxValue = Math.max(...values, 0);
  const valueRange = maxValue - minValue || 1;
  const plotHeight = DASH_CHART_HEIGHT - DASH_CHART_TOP - DASH_CHART_BOTTOM;
  const plotWidth = Math.max(viewportWidth, series.length * MIN_POINT_GAP);
  const innerWidth = Math.max(0, plotWidth - DASH_CHART_SIDE * 2);
  const yFor = (value) => DASH_CHART_TOP + plotHeight - ((value - minValue) / valueRange) * plotHeight;
  const points = series.map((row, index) => ({
    x: series.length === 1 ? plotWidth / 2 : DASH_CHART_SIDE + (index / (series.length - 1)) * innerWidth,
    y: yFor(row[valueKey]),
    row,
  }));
  const line = points.map((point, index) => `${index ? 'L' : 'M'} ${point.x} ${point.y}`).join(' ');
  const zeroY = yFor(0);
  const area = points.length === 0 ? '' : `${line} L ${points.at(-1).x} ${zeroY} L ${points[0].x} ${zeroY} Z`;
  const ticks = minValue === maxValue ? [0]
    : minValue < 0 && maxValue > 0
      ? [minValue, 0, maxValue / 2, maxValue]
      : [minValue, minValue + valueRange / 3, minValue + valueRange * 2 / 3, maxValue];

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return undefined;
    const measure = () => setViewportWidth(Math.max(0, Math.floor(viewport.clientWidth)));
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const scroll = viewportRef.current;
    if (!scroll) return undefined;
    const frame = window.requestAnimationFrame(() => {
      scroll.scrollLeft = scroll.scrollWidth - scroll.clientWidth;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [plotWidth, series.length, unit]);

  useEffect(() => { setHoveredIndex(null); }, [series, valueKey]);

  return <article className="dash-card dash-detail-card">
    <div className="dash-table-heading"><h3>{title}</h3><span>(단위: {money ? '원' : '건'} · {dashboardUnitLabel(unit)})</span></div>
    {series.length === 0 ? <p className="dash-empty">조회 기간의 데이터가 없습니다.</p> : <div className="dash-chart-layout">
      <svg className="dash-chart-y-axis" viewBox={`0 0 58 ${DASH_CHART_HEIGHT}`} role="presentation" aria-hidden="true">
        {ticks.map((tick, index) => { const y = yFor(tick); return <text key={`${tick}-${index}`} x="54" y={y + 4} textAnchor="end" className="dash-axis-label">{money ? compactMoneyTick(tick) : Math.round(tick).toLocaleString('ko-KR')}</text>; })}
      </svg>
      <div className="dash-chart-scroll" ref={viewportRef} onScroll={() => setHoveredIndex(null)}>
        <div className="dash-chart-plot" style={{ width: `${plotWidth}px` }}>
          <svg className="dash-trend" width={plotWidth} height={DASH_CHART_HEIGHT} viewBox={`0 0 ${plotWidth} ${DASH_CHART_HEIGHT}`} role="img" aria-label={title}>
            <defs><linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={color} stopOpacity=".28"/><stop offset="1" stopColor={color} stopOpacity=".03"/></linearGradient></defs>
            {ticks.map((tick, index) => { const y = yFor(tick); return <line key={`${tick}-${index}`} x1="0" x2={plotWidth} y1={y} y2={y} className="dash-gridline"/>; })}
            <path d={area} fill={`url(#${gradientId})`} /><path d={line} className="dash-line" style={{ stroke: color }} />
            {points.map((point, index) => <g key={`${point.row.date}-${index}`} tabIndex="0" role="img" aria-label={`${dashboardTooltipDate(point.row.date, unit)}, ${money ? krw(point.row[valueKey]) : `${dashNumber(point.row[valueKey])}건`}`} onFocus={() => setHoveredIndex(index)} onBlur={() => setHoveredIndex(null)} onMouseEnter={() => setHoveredIndex(index)} onMouseLeave={() => setHoveredIndex(null)} onPointerDown={() => setHoveredIndex(index)} onPointerLeave={() => setHoveredIndex(null)}>
              <circle cx={point.x} cy={point.y} r="4" className="dash-point" style={{ stroke: color }}><title>{`${dashboardTooltipDate(point.row.date, unit)}: ${money ? krw(point.row[valueKey]) : `${dashNumber(point.row[valueKey])}건`}`}</title></circle>
              <text x={point.x} y={DASH_CHART_HEIGHT - 14} textAnchor="middle" className="dash-axis-label">{dashboardAxisDate(point.row.date, unit)}</text>
            </g>)}
          </svg>
          {hoveredIndex !== null && points[hoveredIndex] && <div className="dash-tooltip" role="tooltip" style={{ left: `${Math.min(plotWidth - 70, Math.max(70, points[hoveredIndex].x))}px`, top: `${Math.max(4, points[hoveredIndex].y - 54)}px` }}><span>{dashboardTooltipDate(points[hoveredIndex].row.date, unit)}</span><strong>{money ? krw(points[hoveredIndex].row[valueKey]) : `${dashNumber(points[hoveredIndex].row[valueKey])}건`}</strong></div>}
        </div>
      </div>
    </div>}
  </article>;
}

function PeriodPicker({ draft, onChange, onApply, loading }) {
  return <form className="dash-period" onSubmit={(event) => { event.preventDefault(); onApply(); }} aria-label="대시보드 조회 기간">
    <label><span>시작일</span><input type="date" value={draft.from} onChange={(event) => onChange({ ...draft, from: event.target.value })}/></label>
    <span className="dash-period-separator" aria-hidden="true">~</span>
    <label><span>종료일</span><input type="date" value={draft.to} onChange={(event) => onChange({ ...draft, to: event.target.value })}/></label>
    <button type="submit" className="primary" disabled={loading}>조회</button>
  </form>;
}

function DashboardView({ kind, token, scopeId }) {
  const initialPeriod = useMemo(dashboardPeriodFromUrl, []);
  const [draft, setDraft] = useState(initialPeriod);
  const [applied, setApplied] = useState(initialPeriod);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const scopeKey = kind === 'merchant' ? 'merchant_id' : 'company_id';
  const merchant = kind === 'merchant';

  useEffect(() => {
    if (!scopeId) { setLoading(false); setError('대시보드 조회 권한 정보를 확인할 수 없습니다.'); return undefined; }
    const controller = new AbortController();
    const params = new URLSearchParams(window.location.search);
    params.set('from', applied.from); params.set('to', applied.to); params.set(scopeKey, scopeId);
    params.delete(merchant ? 'company_id' : 'merchant_id');
    window.history.replaceState(null, '', `${window.location.pathname}?${params.toString()}${window.location.hash}`);
    setLoading(true); setError(''); setSummary(null);
    apiFetch(`/admin/dashboard/summary?from=${encodeURIComponent(applied.from)}&to=${encodeURIComponent(applied.to)}&${scopeKey}=${encodeURIComponent(scopeId)}`, token, { signal: controller.signal })
      .then(mapDashboardSummary)
      .then((data) => { if (!controller.signal.aborted) setSummary(data); })
      .catch((loadError) => { if (!controller.signal.aborted) setError(loadError.message || '대시보드를 불러오지 못했어요.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [applied, kind, reload, scopeId, scopeKey, token]);

  function applyPeriod() {
    if (!validDashboardDate(draft.from) || !validDashboardDate(draft.to) || draft.from > draft.to) { setError('올바른 조회 기간을 입력해 주세요.'); return; }
    setApplied({ ...draft });
  }

  const mealRows = summary?.by_meal_type ?? [];
  const hasDashboardData = Boolean(summary && (
    summary.total_amount !== 0 || summary.total_count !== 0
    || mealRows.some((row) => row.amount !== 0 || row.count !== 0)
    || summary.top_companies_by_amount.length > 0 || summary.top_companies_by_count.length > 0
    || summary.series.some((row) => row.amount !== 0 || row.count !== 0)
  ));
  const amountRank = !hasDashboardData ? [] : merchant ? summary.top_companies_by_amount : [
    ...mealRows.map((row, index) => ({ rank: index + 1, name: row.label, amount: row.amount })),
    { rank: '', name: '합계', amount: summary.total_amount, isTotal: true },
  ];
  const countRank = !hasDashboardData ? [] : merchant ? summary.top_companies_by_count : [
    ...mealRows.map((row, index) => ({ rank: index + 1, name: row.label, count: row.count })),
    { rank: '', name: '합계', count: summary.total_count, isTotal: true },
  ];
  const labels = merchant ? {
    amount: '총 매출', count: '총 수량',
    rankAmount: '거래처별 매출 합계', rankCount: '거래처별 수량 합계',
    trendAmount: '기간별 매출 그래프', trendCount: '기간별 수량 그래프',
  } : {
    amount: '총 이용액', count: '총 이용 수량',
    rankAmount: '식사 구분별 이용액 합계', rankCount: '식사 구분별 이용 수량 합계',
    trendAmount: '기간별 이용액 그래프', trendCount: '기간별 이용 수량 그래프',
  };

  return <AdminPage showHeader={false} preview={false} className="dash-page merchant-regular-weight">
    <PeriodPicker draft={draft} onChange={setDraft} onApply={applyPeriod} loading={loading}/>
    {error && <div className="dash-error" role="alert">{error}<button type="button" className="ghost" onClick={() => setReload((value) => value + 1)} disabled={loading}>다시 시도</button></div>}
    {loading && <div className="dash-loading" role="status" aria-label="대시보드를 불러오는 중"><div className="dash-summary-grid">{[0, 1, 2].map((key) => <div key={key} className="dash-card dash-skeleton" />)}</div><div className="dash-two-grid">{[0, 1, 2, 3].map((key) => <div key={key} className="dash-card dash-skeleton dash-skeleton-large" />)}</div></div>}
    {summary && !loading && <>
      <section className="dash-summary-grid"><SummaryCard label={labels.amount} value={summary.total_amount} delta={summary.total_amount_delta_pct} money Icon={WalletCards} tone="green"/><DonutCard rows={mealRows} total={summary.total_count}/><SummaryCard label={labels.count} value={summary.total_count} delta={summary.total_count_delta_pct} Icon={BarChart3} tone="orange"/></section>
      <section className="dash-two-grid"><RankTable title={labels.rankAmount} rows={amountRank} valueKey="amount" money secondHeader={merchant ? '거래처명' : '구분'}/><RankTable title={labels.rankCount} rows={countRank} valueKey="count" secondHeader={merchant ? '거래처명' : '구분'}/></section>
      <section className="dash-two-grid"><TrendChart title={labels.trendAmount} series={hasDashboardData ? summary.series : []} unit={summary.unit} valueKey="amount" money color="#2FB865"/><TrendChart title={labels.trendCount} series={hasDashboardData ? summary.series : []} unit={summary.unit} valueKey="count" color="#4C8BF5"/></section>
    </>}
  </AdminPage>;
}

function CompanyDashboard({ token, scopeId }) {
  return <DashboardView kind="company" token={token} scopeId={scopeId}/>;
}

function CompanyMonthlyUsage({ usage, ym, onYmChange, loading, error, retry }) {
  const totals = (usage?.daily ?? []).reduce((sum, row) => ({ spends: sum.spends + row.spendCount, reversals: sum.reversals + row.reversalCount, amount: sum.amount + row.grossSpendAmount }), { spends: 0, reversals: 0, amount: 0 });
  return <AdminPage title={null} description="우리 회사의 일별 식대 이용 현황을 확인합니다." preview={false} className="merchant-regular-weight merchant-open-table company-usage-page">
    <CompanyUsagePeriod value={ym} onChange={onYmChange} disabled={loading}/>
    <CompanyUsageState loading={loading} error={error} retry={retry}/>
    {usage && <article className="panel"><div className="panel-title"><div><h3>{formatPeriodYm(usage.periodYm)}</h3><p className="panel-note">일별 이용 사원수와 결제·취소를 분리한 집계입니다.</p></div></div>{usage.daily.length === 0 ? <p className="empty-state">선택한 달의 이용 내역이 없습니다.</p> : <div className="table-wrap"><table><thead><tr><th>날짜</th><th className="money">이용 사원수</th><th className="money">결제</th><th className="money">취소</th><th className="money">사용액 (취소 반영)</th></tr></thead><tbody>{usage.daily.map((row) => <tr key={row.id}><td>{row.date}</td><td className="money">{row.uniqueUsers.toLocaleString('ko-KR')}명</td><td className="money">{row.spendCount.toLocaleString('ko-KR')}건</td><td className="money">{row.reversalCount.toLocaleString('ko-KR')}건</td><td className="money">{krw(row.grossSpendAmount)}</td></tr>)}<tr className="usage-total-row"><td>합계</td><td className="money">-</td><td className="money">{totals.spends.toLocaleString('ko-KR')}건</td><td className="money">{totals.reversals.toLocaleString('ko-KR')}건</td><td className="money">{krw(totals.amount)}</td></tr></tbody></table></div>}</article>}
  </AdminPage>;
}

function CompanyEmployeeUsage({ usage, ym, onYmChange, loading, error, retry }) {
  return <AdminPage title={null} description="사원별 결제·취소와 사용액을 비교합니다." preview={false} className="merchant-regular-weight merchant-open-table company-usage-page">
    <CompanyUsagePeriod value={ym} onChange={onYmChange} disabled={loading}/>
    <CompanyUsageState loading={loading} error={error} retry={retry}/>
    {usage && <article className="panel"><div className="panel-title"><div><h3>{formatPeriodYm(usage.periodYm)}</h3><p className="panel-note">활동 이력이 있는 사원의 결제·취소 집계입니다.</p></div></div>{usage.employees.length === 0 ? <p className="empty-state">선택한 달의 사원별 이용 내역이 없습니다.</p> : <div className="table-wrap"><table><thead><tr><th>사원명</th><th>상태</th><th>부서</th><th>사번</th><th className="money">결제</th><th className="money">취소</th><th className="money">사용일</th><th className="money">사용액 (취소 반영)</th><th className="money">자부담액</th></tr></thead><tbody>{usage.employees.map((row) => <tr key={row.id}><td><strong>{row.name}</strong></td><td><span className={`employee-status-badge status-${row.status}`}>{({ active: '활성', inactive: '비활성', paused: '일시중지', suspended: '정지', disabled: '비활성', former: '이관', unknown: '확인 필요' })[row.status] ?? row.status}</span></td><td>{row.department || '-'}</td><td>{row.employeeNo || '-'}</td><td className="money">{row.spendCount.toLocaleString('ko-KR')}건</td><td className="money">{row.reversalCount.toLocaleString('ko-KR')}건</td><td className="money">{row.usageDays.toLocaleString('ko-KR')}일</td><td className="money">{krw(row.grossSpendAmount)}</td><td className="money">{krw(row.employeePaidAmount)}</td></tr>)}</tbody></table></div>}</article>}
  </AdminPage>;
}
function CompanyTaxInvoiceScreen({ token }) {
  const { rows: loadedRows, error, warning, loading, reload } = useSettlementV2Rows(token, false);
  const rows = (loadedRows ?? []).filter((row) => row.tax_invoice_status !== 'not_requested');
  const [actionError, setActionError] = useState('');
  const [pendingId, setPendingId] = useState('');
  async function openDocument(row, kind) {
    if (pendingId) return;
    setPendingId(row.id); setActionError('');
    try {
      await openDocumentInNewWindow(window.open.bind(window), async () => {
        const data = await apiFetch(`/company/settlements/${encodeURIComponent(row.id)}/tax-invoice/${kind}-url`, token);
        return data?.url;
      });
    } catch (documentError) { setActionError(documentError.message); }
    finally { setPendingId(''); }
  }
  return <AdminPage title={null} description="" showHeader={false} preview={false} className="merchant-regular-weight merchant-open-table">
    {(error || actionError) && <div className="alert error" role="alert">{actionError || error} <button type="button" className="ghost" onClick={reload} disabled={loading || Boolean(pendingId)}>다시 시도</button></div>}
    {warning && <div className="alert warning" role="alert">{warning} <button type="button" className="ghost" onClick={reload} disabled={loading}>다시 시도</button></div>}
    <article className="panel"><div className="panel-title employee-panel-actions"><span className="badge">수신 전용</span></div>{loadedRows === null ? <SettlementV2Empty text="세금계산서 내역을 불러오는 중입니다"/> : <><div className="table-wrap"><table><thead><tr><th>정산월</th><th>작성일자</th><th className="money">합계</th><th>세금계산서 상태</th><th>발행일시</th><th>승인번호</th><th>문서</th></tr></thead><tbody>{rows.map((row) => { const documentReady = hasInvoiceDocument(row); return <tr key={row.id}><td><strong>{row.period_start.slice(0, 7)}</strong></td><td>{row.invoice?.written_at || '미확정'}</td><td className="money">{krw(row.total_amount)}</td><td><SettlementV2Status type="invoice" value={row.tax_invoice_status}/></td><td>{formatKoreanTimestamp(row.invoice?.issued_at)}</td><td>{row.invoice?.approval_number || '미수신'}</td><td>{documentReady ? <div className="row-actions"><button type="button" className="ghost settlement-v2-inline-action" disabled={Boolean(pendingId)} onClick={() => openDocument(row, 'view')}><FileText size={14}/> 보기</button><button type="button" className="ghost settlement-v2-inline-action" disabled={Boolean(pendingId)} onClick={() => openDocument(row, 'pdf')}><Download size={14}/> PDF</button></div> : <span className="panel-note">{TAX_INVOICE_STATUS[row.tax_invoice_status]} · 문서 없음</span>}</td></tr>; })}</tbody></table></div>{rows.length === 0 && <SettlementV2Empty />}</>}</article>
  </AdminPage>;
}

function CompanyInfoScreen({ company, busy, onSave, onSettings }) {
  const emptyForm = { name: '', biz_reg_no: '', representative_name: '', business_type: '', business_item: '', address: '', contact_name: '', contact_phone: '', tax_invoice_email: '' };
  const valuesFrom = (item) => Object.fromEntries(Object.keys(emptyForm).map((key) => [key, item?.[key] ?? (key === 'tax_invoice_email' ? item?.contact_email ?? '' : '')]));
  const [form, setForm] = useState(() => valuesFrom(company));
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    setForm(valuesFrom(company));
    setEditing(false);
  }, [company]);
  const field = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }));
  const beginEdit = () => { setForm(valuesFrom(company)); setEditing(true); };
  const cancelEdit = () => { setForm(valuesFrom(company)); setEditing(false); };
  return <AdminPage title={null} description="업체 상세에 표시할 사업자정보와 세금계산서 수신 정보를 관리합니다." actions={<button type="button" className="account-settings-button" onClick={onSettings} aria-label="관리자 정보 설정" title="관리자 정보 설정"><Settings size={20}/></button>} preview={false} className="merchant-regular-weight supplier-info-page">
    <form className="panel supplier-info-card" onSubmit={async (event) => { event.preventDefault(); await onSave(form); }}>
      <div className="panel-title supplier-info-card-title">
        <div className="supplier-edit-actions">
          <button type="button" className="ghost supplier-capsule-button" onClick={beginEdit} disabled={editing || busy}>수정</button>
          <button type="button" className="ghost supplier-capsule-button" onClick={cancelEdit} disabled={!editing || busy}>취소</button>
          <button type="submit" className="primary supplier-capsule-button" disabled={!editing || busy}>{busy ? '저장 중' : '저장'}</button>
        </div>
      </div>
      <div className="supplier-info-fields">
        <label>사업자등록번호<input value={form.biz_reg_no} onChange={field('biz_reg_no')} disabled={!editing} required /></label>
        <label>상호<input value={form.name} onChange={field('name')} disabled={!editing} required /></label>
        <label>대표자<input value={form.representative_name} onChange={field('representative_name')} disabled={!editing} /></label>
        <label>업태<input value={form.business_type} onChange={field('business_type')} disabled={!editing} /></label>
        <label>종목<input value={form.business_item} onChange={field('business_item')} disabled={!editing} /></label>
        <label className="wide">사업장주소<input value={form.address} onChange={field('address')} disabled={!editing} /></label>
        <label>담당자명<input value={form.contact_name} onChange={field('contact_name')} disabled={!editing} /></label>
        <label>연락처<input value={form.contact_phone} onChange={field('contact_phone')} disabled={!editing} /></label>
        <label className="wide">세금계산서 수신 이메일<input type="email" value={form.tax_invoice_email} onChange={field('tax_invoice_email')} disabled={!editing} /></label>
      </div>
    </form>
  </AdminPage>;
}

function CompanyScreen({ section, company, busy, onSaveCompany, onSettings, onCompanyInfo, token, scopeId }) {
  const usageSection = ['monthly-usage', 'employee-usage'].includes(section);
  const [usageYm, setUsageYm] = useState(currentPeriodYm);
  const [usage, setUsage] = useState(null);
  const [usageLoading, setUsageLoading] = useState(false);
  const [usageError, setUsageError] = useState('');
  const [usageReload, setUsageReload] = useState(0);

  useEffect(() => {
    if (!usageSection) return undefined;
    const controller = new AbortController();
    setUsageLoading(true);
    setUsageError('');
    setUsage(null);
    apiFetch(`/admin/company-usage?ym=${encodeURIComponent(usageYm)}`, token, { signal: controller.signal }).then((payload) => {
      if (controller.signal.aborted) return;
      try {
        setUsage(mapCompanyUsage(payload, usageYm));
      } catch (contractError) {
        setUsageError(contractError.message || '이용 현황 응답을 확인할 수 없어요.');
      }
    }).catch((loadError) => { if (!controller.signal.aborted) setUsageError(loadError.message || '이용 현황을 불러오지 못했어요.'); })
      .finally(() => { if (!controller.signal.aborted) setUsageLoading(false); });
    return () => controller.abort();
  }, [token, usageYm, usageReload, usageSection]);

  if (section === 'company-info') return <CompanyInfoScreen company={company} busy={busy} onSave={onSaveCompany} onSettings={onSettings} />;
  if (section === 'company-billing') return <CompanySettlementScreen token={token} company={company} onCompanyInfo={onCompanyInfo} />;
  if (section === 'company-tax-invoices') return <CompanyTaxInvoiceScreen token={token} company={company} />;
  const screens = {
    'company-dashboard': CompanyDashboard,
    'monthly-usage': CompanyMonthlyUsage,
    'employee-usage': CompanyEmployeeUsage,
  };
  const Screen = screens[section];
  return Screen ? <Screen token={token} scopeId={scopeId} usage={usage} ym={usageYm} onYmChange={setUsageYm} loading={usageLoading} error={usageError} retry={() => setUsageReload((value) => value + 1)} /> : null;
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
  const [coupons, setCoupons] = useState([]);
  const [couponsMigrationRequired, setCouponsMigrationRequired] = useState(false);
  const [couponLoadError, setCouponLoadError] = useState('');
  const [notifications, setNotifications] = useState([]);
  const [notificationsMigrationRequired, setNotificationsMigrationRequired] = useState(false);
  const [paymentAlertDay, setPaymentAlertDay] = useState(todayInput());
  const [unreadPaymentCount, setUnreadPaymentCount] = useState(0);
  const notifiedPaymentIdsRef = useRef(new Set());
  const paymentFeedReadyRef = useRef(false);
  const paymentAlertsVisibleRef = useRef(false);
  const transactionRefreshVersionRef = useRef(0);
  const [cropRequest, setCropRequest] = useState(null);
  const [dailyMenu, setDailyMenu] = useState(null);
  const [dailyMenuForm, setDailyMenuForm] = useState({ service_date: todayInput(), title: '오늘 뷔페 메뉴', menu_text: '', image_url: '' });
  const [merchantCompanies, setMerchantCompanies] = useState(null);
  const [prepurchaseRefreshVersion, setPrepurchaseRefreshVersion] = useState(0);
  const [merchantSection, setMerchantSection] = useState('main');
  const [companyManagementTab, setCompanyManagementTab] = useState('company-list');
  const [restaurantManagementTab, setRestaurantManagementTab] = useState('daily-menu');
  const merchantContentSection = merchantSection === 'companies'
    ? companyManagementTab
    : merchantSection === 'restaurant-management' ? restaurantManagementTab : merchantSection;
  const [companySection, setCompanySection] = useState('company-dashboard');
  const [companyUsageTab, setCompanyUsageTab] = useState('employee-usage');
  const companyContentSection = companySection === 'company-usage' ? companyUsageTab : companySection;
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
  const [contractForm, setContractForm] = useState({ settlement_cycle: 'month_end', settlement_day: '25', unit_price: '', subsidy_enabled: false, prepurchase_enabled: false, company_subsidy_amount: '0', restaurant_subsidy_amount: '0', tax_type: 'unclassified' });
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
  const merchantKpis = useMemo(() => merchantRecentKpis(transactions, paymentAlertDay), [transactions, paymentAlertDay]);
  const cards = useMemo(() => isPlatformAdmin ? [
    ['권한', '플랫폼 운영자', WalletCards, 'brown'],
    ['식당', platformMerchants ? `${platformMerchants.items.length}곳` : '조회 중', Coffee, 'green'],
  ] : isMerchantAdmin ? [
    ['오늘 매출 (최근 내역)', krw(merchantKpis.amount), WalletCards, 'brown'],
    ['오늘 결제 (최근 내역)', `${merchantKpis.count}건`, BarChart3, 'orange'],
    ['불러온 거래', transactions ? `${merchantKpis.loadedCount}건` : '조회 중', CreditCard, 'green'],
    ['전체 거래', merchantKpis.totalCount === null ? '조회 중' : `${merchantKpis.totalCount}건`, FileText, 'orange'],
  ] : [
    ['가입 요청', `${requests.length}명`, Users, 'orange'],
    ['직원', employees ? `${employees.items.length}명` : '조회 중', WalletCards, 'brown'],
  ], [isPlatformAdmin, isMerchantAdmin, requests.length, platformMerchants, employees, merchantKpis, transactions]);

  const recentPaymentAlerts = useMemo(() => (filterMerchantTransactions(transactions)?.items ?? [])
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
          let couponData;
          let notificationData;
          const transactionRequestVersion = ++transactionRefreshVersionRef.current;
          [merchantCompanyData, transactionData, merchantQrData, voucherData, couponData, notificationData] = await Promise.all([
            apiFetch('/admin/merchant/companies', token),
            apiFetch('/admin/merchant/transactions', token),
            apiFetch('/admin/merchant/qr', token),
            apiFetch('/admin/voucher-products', token),
            apiFetch('/admin/coupons', token).catch((couponError) => {
              const migrationRequired = couponError.code === 'MIGRATION_REQUIRED' || couponError.status === 404;
              return {
                items: [], migration_required: migrationRequired,
                load_error: migrationRequired ? '' : couponError.message,
              };
            }),
            apiFetch('/admin/notifications', token),
          ]);
          transactionData = filterMerchantTransactions(transactionData);
          if (transactionRequestVersion === transactionRefreshVersionRef.current) {
            notifiedPaymentIdsRef.current = new Set(merchantMealPaymentIds(transactionData));
            paymentFeedReadyRef.current = true;
          } else {
            transactionData = null;
          }
          setVoucherProducts(voucherData.items ?? []);
          setVoucherProductsMigrationRequired(!!voucherData.migration_required);
          setCoupons(couponData.items ?? []);
          setCouponsMigrationRequired(!!couponData.migration_required);
          setCouponLoadError(couponData.load_error ?? '');
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
      if (transactionData !== null || meData.role !== 'merchant_admin') setTransactions(transactionData);
      setMerchantQr(merchantQrData);
      setPlatformMerchants(platformMerchantData);
      setDailyMenu(dailyMenuData);
      setDailyMenuForm({
        service_date: dailyMenuData?.service_date ?? todayInput(),
        title: dailyMenuData?.today_menu?.title ?? '오늘 뷔페 메뉴',
        menu_text: dailyMenuData?.today_menu?.menu_text ?? '',
        image_url: dailyMenuData?.today_menu?.image_url ?? '',
      });
      if (meData.role === 'merchant_admin') setPrepurchaseRefreshVersion((version) => version + 1);
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
          prepurchase_enabled: contractForm.prepurchase_enabled,
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
    const visible = merchantSection === 'restaurant-management' && merchantContentSection === 'payment-qr';
    paymentAlertsVisibleRef.current = visible;
    if (visible) setUnreadPaymentCount(0);
  }, [merchantSection, merchantContentSection]);

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
      const refreshVersion = ++transactionRefreshVersionRef.current;
      try {
        const list = await apiFetch('/admin/merchant/transactions', token);
        if (stopped || refreshVersion !== transactionRefreshVersionRef.current) return;
        const result = reconcileMerchantPaymentFeed(list, notifiedPaymentIdsRef.current, paymentFeedReadyRef.current);
        notifiedPaymentIdsRef.current = result.nextNotifiedIds;
        if (paymentFeedReadyRef.current && result.newIds.length > 0) {
          playPaymentChime();
          if (!paymentAlertsVisibleRef.current) {
            setUnreadPaymentCount((count) => count + result.newIds.length);
          }
        }
        paymentFeedReadyRef.current = true;
        setTransactions(result.list);
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
        // Reconcile against the complete API feed rather than playing directly
        // from the event, so initial/current rows cannot produce duplicate sounds.
        const refreshVersion = ++transactionRefreshVersionRef.current;
        try {
          const list = await apiFetch('/admin/merchant/transactions', token);
          if (refreshVersion !== transactionRefreshVersionRef.current) return;
          const result = reconcileMerchantPaymentFeed(list, notifiedPaymentIdsRef.current, paymentFeedReadyRef.current);
          notifiedPaymentIdsRef.current = result.nextNotifiedIds;
          if (paymentFeedReadyRef.current && result.newIds.length > 0) {
            playPaymentChime();
            if (!paymentAlertsVisibleRef.current) setUnreadPaymentCount((count) => count + result.newIds.length);
          }
          paymentFeedReadyRef.current = true;
          setTransactions(result.list);
        } catch (noticeError) { setError(`결제 알림 확인 실패: ${noticeError.message}`); }
      }).subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [isMerchantAdmin, merchantQr?.merchant?.id, token]);

  if (dashboardBooting) return <main className="loading"><BrandMark /><div className="spinner"/><p className="loading-copy">운영자 권한을 확인하고 있어요...</p></main>;

  if (!me) return <main className="loading"><BrandMark /><div className="alert error">권한 정보를 불러오지 못했어요. {error}</div><button className="ghost" onClick={onLogout}>로그아웃</button></main>;

  const merchantNavGroups = [
    [['main', '대시보드', Home], ['payment-history', '실시간 매출', CreditCard]],
    [['companies', '업체 정보', Building2], ['settlements-by-company', '매출 정산', WalletCards], ['tax-invoices', '세금계산서', FileText]],
    [['restaurant-management', '식당 관리', Coffee], ['supplier-info', '공급자 정보', Settings]],
  ];
  const companyManagementTabs = [
    ['company-list', '업체 목록'],
    ['companies', '업체 추가'],
    ['prepurchase', '선구매'],
  ];
  const restaurantManagementTabs = [
    ['daily-menu', '오늘 뷔페 메뉴'],
    ['vouchers', '판매 상품'],
    ['coupons', '쿠폰 관리'],
    ['payment-qr', '결제 QR'],
    ['notifications', '알림'],
    ['announcements', '공지사항'],
    ['reviews', '리뷰'],
    ['partners', '제휴사'],
    ['partner-banners', '배너 광고 설정'],
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
      {merchantNavGroups.map((items, groupIndex) => <React.Fragment key={items[0][0]}>{groupIndex > 0 && <div className="merchant-nav-divider" role="separator" />}{items.map(([id, label, Icon]) => <button key={id} type="button" className={merchantSection === id ? 'active' : ''} onClick={() => setMerchantSection(id)} aria-current={merchantSection === id ? 'page' : undefined}><Icon size={20}/><span>{label}</span>{id === 'restaurant-management' && unreadPaymentCount > 0 && <span className="merchant-nav-badge" aria-label={`새 결제 ${unreadPaymentCount}건`}>{unreadPaymentCount > 99 ? '99+' : unreadPaymentCount}</span>}</button>)}</React.Fragment>)}
      <div className="merchant-nav-divider merchant-nav-divider-before-logout" role="separator" />
      <button type="button" className="merchant-sidebar-logout" onClick={load} disabled={busy}><RefreshCw size={18}/><span>새로고침</span></button>
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

    <div className={isMerchantAdmin ? `merchant-content${merchantSection === 'main' || merchantSection === 'payment-history' || ['vouchers', 'coupons', 'payment-qr', 'announcements', 'reviews'].includes(merchantContentSection) ? ' merchant-regular-weight' : ''}` : isCompanyAdmin ? 'company-content merchant-regular-weight' : undefined}>
    {isCompanyAdmin && companySection === 'company-usage' && <nav className="merchant-section-tabs" aria-label="이용 내역 페이지">
      {companyUsageTabs.map(([id, label]) => <button key={id} type="button" className={companyUsageTab === id ? 'active' : ''} onClick={() => setCompanyUsageTab(id)} aria-current={companyUsageTab === id ? 'page' : undefined}>{label}</button>)}
    </nav>}
    {isMerchantAdmin && merchantSection === 'companies' && <nav className="merchant-section-tabs" aria-label="업체 정보 페이지">
      {companyManagementTabs.map(([id, label]) => <button key={id} type="button" className={companyManagementTab === id ? 'active' : ''} onClick={() => setCompanyManagementTab(id)} aria-current={companyManagementTab === id ? 'page' : undefined}>{label}</button>)}
    </nav>}
    {isMerchantAdmin && merchantSection === 'restaurant-management' && <nav className="merchant-section-tabs" aria-label="식당 관리 페이지">
      {restaurantManagementTabs.map(([id, label]) => <button key={id} type="button" className={restaurantManagementTab === id ? 'active' : ''} onClick={() => setRestaurantManagementTab(id)} aria-current={restaurantManagementTab === id ? 'page' : undefined}>{label}</button>)}
    </nav>}
    {isMerchantAdmin && merchantContentSection === 'partners' && <PartnerManagementScreen token={token}/>}
    {isMerchantAdmin && merchantContentSection === 'partner-banners' && <PartnerBannerManagementScreen token={token}/>}
    {isMerchantAdmin && ['announcements', 'reviews'].includes(merchantContentSection) && <AnnouncementReviewPanel token={token} section={merchantContentSection}/>}
    {isMerchantAdmin && <MerchantScreen section={merchantContentSection} companyItems={merchantCompanies?.items ?? []} onCompanyDetail={openContractModal} onCompaniesChanged={load} merchant={merchantQr?.merchant} busy={busy} onSaveSupplier={saveMerchantSupplierProfile} onSettings={openAccountSettings} token={token} scopeId={me?.merchant_id} prepurchaseRefreshVersion={prepurchaseRefreshVersion} />}
    {isCompanyAdmin && !showCompanyLegacy && <CompanyScreen section={companyContentSection} company={me?.company} busy={busy} onSaveCompany={saveCompanyProfile} onSettings={openAccountSettings} onCompanyInfo={() => setCompanySection('company-info')} token={token} scopeId={me?.company_id} />}

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
          <label className="subsidy-toggle"><input type="checkbox" checked={contractForm.prepurchase_enabled} onChange={(event) => setContractForm((form) => ({ ...form, prepurchase_enabled: event.target.checked }))} /> 선구매</label>
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

    {isPlatformAdmin && <section className="grid">
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

    {isMerchantAdmin && merchantSection === 'payment-history' && <PaymentHistoryDashboard request={merchantRequest}/>}

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

    {isMerchantAdmin && merchantContentSection === 'coupons' && <CouponManagementPanel token={token} items={coupons} migrationRequired={couponsMigrationRequired} loadError={couponLoadError} busy={busy} onChanged={load} setBusy={setBusy} setError={setError} setMessage={setMessage} />}

    {isMerchantAdmin && merchantContentSection === 'payment-qr' && <PaymentQrPanel recentPaymentAlerts={recentPaymentAlerts} merchantQr={merchantQr} merchantQrImageUrl={merchantQrImageUrl} merchantPayUrl={merchantPayUrl} onDownload={downloadMerchantQrPdf} onCopy={copyMerchantPayUrl} />}

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
