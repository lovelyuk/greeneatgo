import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CheckCircle2, Coffee, FileSpreadsheet, LogOut, Package, QrCode, RefreshCw, Sprout, Users, WalletCards, XCircle } from 'lucide-react';
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

function Dashboard({ session, onLogout }) {
  const token = session.access_token;
  const [me, setMe] = useState(null);
  const [requests, setRequests] = useState([]);
  const [settlements, setSettlements] = useState(null);
  const [products, setProducts] = useState(null);
  const [productForm, setProductForm] = useState({ name: '', price: '', category: '' });
  const [dailyMenu, setDailyMenu] = useState(null);
  const [dailyMenuForm, setDailyMenuForm] = useState({ title: '오늘의 부페 메뉴', menu_text: '' });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const isMerchantAdmin = me?.role === 'merchant_admin';
  const cards = useMemo(() => isMerchantAdmin ? [
    ['권한', '식당관리자', WalletCards, 'brown'],
    ['상품', products ? `${products.items.filter((item) => item.is_active).length}개` : '조회 중', QrCode, 'orange'],
  ] : [
    ['가입 요청', `${requests.length}명`, Users, 'orange'],
    ['직원 권한', me?.role === 'company_admin' ? '관리자' : '확인 필요', WalletCards, 'brown'],
    ['QR 결제', products ? `${products.items.filter((item) => item.is_active).length}개 상품` : '단일 식당', QrCode, 'orange'],
    ['정산 현황', settlements ? `${settlements.summary.settlement_count}건` : '조회 중', FileSpreadsheet, 'green'],
  ], [isMerchantAdmin, requests.length, me, settlements, products]);

  async function load() {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const meData = await apiFetch('/me', token);
      const [productData, dailyMenuData] = await Promise.all([
        apiFetch('/admin/products', token),
        apiFetch('/admin/daily-menu', token),
      ]);
      let requestData = { items: [] };
      let settlementData = null;
      if (meData.role === 'company_admin') {
        [requestData, settlementData] = await Promise.all([
          apiFetch('/admin/join-requests', token),
          apiFetch('/admin/settlements', token),
        ]);
      }
      setMe(meData);
      setRequests(requestData.items ?? []);
      setSettlements(settlementData);
      setProducts(productData);
      setDailyMenu(dailyMenuData);
      setDailyMenuForm({
        title: dailyMenuData.today_menu?.title ?? '오늘의 부페 메뉴',
        menu_text: dailyMenuData.today_menu?.menu_text ?? '',
      });
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

  useEffect(() => { load(); }, []);

  return <main className="shell">
    <header className="topbar">
      <div className="top-copy">
        <BrandMark />
        <span className="pill">OPERATIONS</span>
        <h1>오늘의 식대 운영 현황</h1>
        <p>가입 승인, 직원 상태, 단일 식당 결제와 정산 현황을 그린잇 스타일의 카드 대시보드로 확인합니다.</p>
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
        <h2>{isMerchantAdmin ? '오늘 메뉴와 상품을 관리하세요' : '든든한 한 끼를 빠르게 승인하세요'}</h2>
        <p>{isMerchantAdmin ? `${products?.merchant?.name ?? '운영 식당'} · ${me?.display_name ?? session.user.email}` : `대기 중인 직원 ${requests.length}명 · 관리자 ${me?.display_name ?? session.user.email}`}</p>
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
        <div className="panel-title"><h2>운영 식당</h2><Coffee size={22}/></div>
        <div className="menu-chips single"><span>🥗 그린잇 식당</span></div>
        <p className="panel-note">현재 파일럿은 한 식당에서만 운영합니다.</p>
      </article>
    </section>


    <section className="panel daily-menu-panel">
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
    </section>


    <section className="panel product-panel">
      <div className="panel-title">
        <div><h2>식당 상품 관리</h2><p className="panel-note">직원 앱은 금액 입력 없이 여기 등록된 상품 중 하나를 선택해 결제합니다.</p></div>
        <span className="badge">{products?.merchant?.name ?? '운영 식당'}</span>
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
    </section>


    {!isMerchantAdmin && <section className="panel settlement-panel">
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

    {!isMerchantAdmin && <section className="panel">
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
