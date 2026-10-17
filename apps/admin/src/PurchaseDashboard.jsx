import React, { useEffect, useRef, useState } from 'react';
import { Home, ShoppingBag, ScanLine, ReceiptText, UserRound, Ticket, PartyPopper, Megaphone, MessageSquare, Menu, ChevronRight, Utensils, QrCode, ArrowLeft } from 'lucide-react';
import PurchaseCatalog, { won } from './PurchaseCatalog.jsx';
import PurchaseHistory from './PurchaseHistory.jsx';
import LocalAbandonmentHistory from './LocalAbandonmentHistory.jsx';
import { dashboardTransactions, couponCount, scanIntent } from './purchaseDashboard.js';
import { AccountSettings, InviteCodeEntry, ReviewBoard, PartnerBanner } from './PurchaseExtras.jsx';
import { headerSubtitle, AVATARS, avatarKind } from './purchaseExtras.js';

const tabs = [['홈', Home], ['구매', ShoppingBag], ['QR', ScanLine], ['내역', ReceiptText], ['내정보', UserRound]];
function Picture({ src, alt }) {
  const [failed, setFailed] = useState(false);
  return src && !failed ? <img className="api-picture" src={src} alt={alt} onError={() => setFailed(true)} /> : <div className="picture-fallback"><Utensils aria-hidden="true" /><span>등록된 사진 없음</span></div>;
}
function CouponWallet({ wallet }) {
  return <><h1>쿠폰함</h1><p>{wallet?.merchant?.name || '식당 정보 없음'} · 사용 가능 {couponCount(wallet) ?? '—'}장</p>
    {['issued', 'items'].map(kind => <section key={kind}><h2>{kind === 'issued' ? '내 쿠폰' : '공개 쿠폰'}</h2>
      {!wallet?.[kind]?.length ? <p className="empty-state">쿠폰이 없어요.</p> : wallet[kind].map(c => {
        const benefit = c.coupon_snapshot || c;
        return <article className={`coupon-ticket ${benefit.discount_type === 'percent' ? 'percent' : ''}`} key={c.id}><span className="coupon-rail">COUPON</span><div><strong>{benefit.discount_value ?? '—'}{benefit.discount_type === 'percent' ? '%' : '원'} 할인</strong><h3>{benefit.name || '보유 쿠폰'}</h3><p>{c.valid_until || '종료일 정보 없음'}</p></div></article>;
      })}</section>)}</>;
}
function ReadBoard({ api, kind }) {
  const [data, setData] = useState(null), [error, setError] = useState(''), [revision, setRevision] = useState(0);
  useEffect(() => {
    let alive = true; setError(''); setData(null);
    api(kind === '공지사항' ? '/announcements' : '/reviews', undefined, { public: true }).then(d => { if (alive) setData(d); }).catch(e => { if (alive && !e.stale) setError(e.message); });
    return () => { alive = false; };
  }, [kind, revision]);
  return <><h1>{kind}</h1>
    {error ? <><p role="alert">{error}</p><button onClick={() => setRevision(revision + 1)}>다시 시도</button></> : !data ? <p role="status">불러오는 중…</p> : !data.items?.length ? <p className="empty-state">등록된 {kind === '리뷰' ? '리뷰가' : '공지가'} 없어요.</p> : data.items.map(row => <article key={row.id} className="purchase-card"><h2>{row.title || `${row.rating} / 5`}</h2><p className="pre-line">{row.content}</p>{row.owner_reply && <p>사장님 답변 · {row.owner_reply}</p>}</article>)}</>;
}
function QrPayment({ api, refresh, userId }) {
  const storageKey = `greeneat-scan-pending:${userId}`;
  const [qr, setQr] = useState(''), [pending, setPending] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState(''), [done, setDone] = useState(null), [blocked, setBlocked] = useState(false);
  const lock = useRef(false), alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
      if (saved) {
        if (typeof saved.qr_data !== 'string' || typeof saved.idempotency_key !== 'string' || !saved.idempotency_key) setBlocked(true);
        else { setPending(saved); setQr(saved.qr_data); }
      }
    } catch { setBlocked(true); }
    return () => { alive.current = false; };
  }, [storageKey]);
  async function submit(e) {
    e.preventDefault(); if (lock.current || blocked || !qr.trim()) return;
    lock.current = true; setBusy(true); setError('');
    try {
      const intent = scanIntent(pending, qr.trim(), () => crypto.randomUUID());
      // Persist BEFORE the consuming request. Retry always keeps the exact key.
      sessionStorage.setItem(storageKey, JSON.stringify(intent)); setPending(intent);
      const result = await api('/transactions/scan', intent);
      if (!alive.current) return;
      if (result?.result !== 'success' || !result.transaction || Array.isArray(result.transaction) || typeof result.transaction !== 'object' ||
          typeof result.transaction.id !== 'string' || !result.transaction.id.trim() || !['voucher', 'subsidized', 'ledger'].includes(result.pay_type) ||
          (result.pay_type !== 'ledger' && (!Number.isSafeInteger(result.remaining) || result.remaining < 0)))
        throw new Error('서버 사용 결과를 확인하지 못했어요.');
      sessionStorage.removeItem(storageKey); setPending(null); setDone(result); await refresh();
    } catch (e) {
      if (alive.current && !e.stale) {
        if (e.scanNotConsumed === true) {
          try {
            // Never discard an uncertain request: this flag is set only by the
            // trusted HTTP pre-consumption allowlist in Wallet.api.
            sessionStorage.removeItem(storageKey); setPending(null);
            setError(`${e.message} QR 내용을 수정한 뒤 다시 확인해 주세요.`);
          } catch {
            setBlocked(true); setError('저장된 요청을 지우지 못했어요. 거래 확인 전 새 결제를 만들지 마세요.');
          }
        } else setError(`${e.message} 같은 요청으로 확인하세요. 새 결제를 만들지 마세요.`);
      }
    }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  return <><h1>QR 결제</h1>{done ? <section className="purchase-card"><h2>사용 완료</h2><p>서버에서 식사 결제를 확인했어요.</p><p>{done.pay_type === 'ledger' ? '회사 장부' : `남은 식권 ${done.remaining ?? '—'}장`}</p><button onClick={() => { setDone(null); setQr(''); }}>다음 식사 결제</button></section> : <>
    <div className="qr-frame"><QrCode size={68} aria-hidden="true" /><p>매장 QR 내용으로 결제하세요</p></div>
    <p className="muted">이 웹 화면은 카메라 스캔을 지원하지 않아요. 앱에서 스캔하거나 매장 QR의 원문을 입력해 주세요.</p>
    <p>확인하면 식권 1장 사용 또는 회사 계약 단가로 장부 결제됩니다. 금액과 자격은 서버에서 확인해요.</p>
    {blocked ? <p role="alert">저장된 QR 요청을 확인할 수 없어요. 관리자에게 거래 확인을 요청해 주세요.</p> : <form onSubmit={submit}><label>매장 QR 내용<input required maxLength={500} value={qr} disabled={busy || !!pending} onChange={e => setQr(e.target.value)} /></label><button disabled={busy || !qr.trim()}>{pending ? '같은 요청으로 다시 확인' : 'QR 결제 확인'}</button></form>}
    {pending && <p role="status">이전 요청이 저장되어 있어요. 같은 QR 요청만 다시 확인할 수 있어요.</p>}{error && <p role="alert">{error}</p>}</>}</>;
}

export default function PurchaseDashboard({ me, api, supabase, apiBaseUrl, legal, refresh, revision, logout, loading }) {
  // Always land on 홈 after login/reload (user rule). The catalog stays mounted
  // while hidden, so a pending checkout is still read and resolved in the
  // background; recovery controls render only in history.
  const [tab, setTab] = useState(0), [purchaseMode, setPurchaseMode] = useState(null), [page, setPage] = useState(''), [wallet, setWallet] = useState(null), [menu, setMenu] = useState(null), [readError, setReadError] = useState('');
  const rows = dashboardTransactions(me), name = me.display_name || '사용자', isVoucher = me.account_type === 'voucher';
  const avatar = AVATARS[avatarKind(me.role, purchaseMode)];
  useEffect(() => {
    let alive = true; setReadError(''); setWallet(null); setMenu(null);
    api('/coupons').then(d => { if (alive) setWallet(d); }).catch(e => { if (alive && !e.stale) setReadError('쿠폰을 불러오지 못했어요. 새로고침해 주세요.'); });
    api('/daily-menu', undefined, { public: true }).then(d => { if (alive) setMenu(d); }).catch(e => { if (alive && !e.stale) setMenu({ unavailable: true }); });
    return () => { alive = false; };
  }, [revision]);
  const [recoveryTarget, setRecoveryTarget] = useState(null), [recoveryNotice, setRecoveryNotice] = useState('');
  function go(index) { setPage(''); setTab(index); setRecoveryNotice(''); }
  function open(destination) { setPage(destination); setTab(0); }
  const monthUsage = isVoucher ? me.voucher_month_used_count != null ? `${me.voucher_month_used_count}장 · ${won(me.voucher_month_used_amount ?? 0)}` : '정보 없음' : me.month_used != null ? won(me.month_used) : '사용 정보 없음';
  return <div className="dashboard-shell">
    {page && <button className="back-button" onClick={() => { setPage(''); refresh(); }}><ArrowLeft size={18} />홈으로</button>}
    <div hidden={tab !== 0 || !!page}>
      <div className="dashboard-header"><button className="avatar" aria-label="프로필 열기" onClick={() => go(4)}><img src={avatar.src} alt="" data-kind={avatarKind(me.role, purchaseMode)} /></button><div><strong>{name}님</strong><p>{headerSubtitle(me.company?.name, wallet?.merchant?.name)}</p></div><button className="icon-control" aria-label="내정보 메뉴" onClick={() => go(4)}><Menu /></button></div>
      <section className={`meal-ticket ${isVoucher && me.voucher_balance === 0 ? 'empty-ticket' : ''}`} aria-label="내 지갑"><p className="ticket-head" aria-hidden="true"><span>MEAL TICKETS</span><span>남은 식권</span></p><h2 className="sr-only">남은 식권</h2><strong className="ticket-balance" aria-label={isVoucher && me.voucher_balance != null ? `${me.voucher_balance}장` : '정보 없음'}>{Array.from(String(isVoucher ? me.voucher_balance ?? '—' : '—')).map((ch, i) => <span className="flip-tile" key={i} aria-hidden="true">{ch}</span>)}{isVoucher && me.voucher_balance != null && <small aria-hidden="true">장</small>}</strong><div className="ticket-wallet"><div><span>쿠폰</span><strong>{couponCount(wallet) ?? '—'}장</strong></div><div><span>포인트</span><strong>{me.point_balance == null ? '—' : Number(me.point_balance).toLocaleString('ko-KR') + 'P'}</strong></div><div><span>이번 달</span><strong className="ticket-usage">{monthUsage}</strong></div></div><div className="ticket-actions">{isVoucher && <button className="ticket-buy" onClick={() => go(1)}><ShoppingBag size={15} />식권 구매</button>}<button className="ticket-qr" onClick={() => go(2)}><QrCode size={16} />QR 사용하기</button></div></section>
      <p className="wallet-caption">{isVoucher ? '보유 식권 · QR 한 번에 1장 사용' : '회사 장부 결제 · 매장 계약 단가 적용'}</p>
      {!isVoucher && me.voucher_balance != null && <p className="muted">보유 보조금 식권 {me.voucher_balance}장 · 실제 결제 방식은 서버에서 확인해요.</p>}
      <div className="home-shortcuts">{[['쿠폰함', Ticket], ['이벤트', PartyPopper], ['공지사항', Megaphone], ['리뷰', MessageSquare]].map(([label, Icon]) => <button key={label} onClick={() => open(label)}><span><Icon size={21} /></span>{label}</button>)}</div>
      {readError && <p role="alert">{readError}</p>}
      <section className="purchase-card today-menu"><div className="section-heading"><h2>오늘 메뉴</h2><Utensils size={18} /></div>{!menu ? <p role="status">메뉴 확인 중…</p> : menu.unavailable ? <p>메뉴를 불러오지 못했어요. 새로고침해 주세요.</p> : !menu.today_menu ? <p>오늘 등록된 메뉴가 없어요.</p> : <><Picture src={menu.today_menu.image_url} alt={menu.today_menu.title || '오늘 메뉴'} /><h3>{menu.today_menu.title}</h3><p className="pre-line">{menu.today_menu.menu_text}</p></>}</section>
      <div className="section-heading"><h2>최근 이용</h2><button onClick={() => go(3)}>전체 보기<ChevronRight size={14} /></button></div>
      <PurchaseHistory me={me} recent />
      {tab === 0 && !page && <PartnerBanner api={api} placement="home_bottom" onCouponIssued={refresh} />}
      <button className="refresh-button" disabled={loading} onClick={refresh}>새로고침</button>
    </div>
    {/* Exactly one catalog/checkout owns admission and persisted pending state.
        Recovery is portaled into history, not a second financial component. */}
    <div hidden={tab !== 1 && page !== '이벤트'}>
      <PurchaseCatalog
        active={tab === 1 || tab === 3 || page === '이벤트'}
        purchaseActive={tab === 1 || page === '이벤트'}
        recoveryView={tab === 3 && !page}
        recoveryTarget={recoveryTarget}
        onRecoveryNeeded={() => {
          go(3);
          setRecoveryNotice('이전 주문의 결제 결과를 먼저 확인해 주세요. 중복 구매를 막기 위해 새 주문은 만들지 않았어요.');
        }}
        onRecoveryEnded={() => go(1)}
        onClose={() => go(0)}
        onCatalog={c => setPurchaseMode(c?.purchase_mode ?? null)}
        api={api} me={me} revision={revision} apiBaseUrl={apiBaseUrl}
        legal={legal} refresh={refresh} eventsOnly={page === '이벤트'}
      />
    </div>
    <div hidden={tab !== 2}><QrPayment api={api} refresh={refresh} userId={me.user_id} /></div>
    <div hidden={tab !== 3}>{recoveryNotice && tab === 3 && <p role="status">{recoveryNotice}</p>}<div ref={setRecoveryTarget} /><PurchaseHistory me={me} />{tab === 3 && <LocalAbandonmentHistory api={api} userId={me.user_id} />}</div>
    <div hidden={tab !== 4}><h1>내정보</h1><div className="profile-heading"><span className="avatar"><img src={avatar.src} alt={avatar.label} /></span><div><h2>{name}</h2><p>{me.company?.name || (me.role === 'employee' ? '회사 임직원' : '개인 구매자')}</p></div></div><section className="purchase-card setting-group"><p><span>휴대폰 번호</span><strong>{me.phone || '—'}</strong></p><p><span>인증수단</span><strong>이메일 (웹)</strong></p><p><span>결제수단</span><strong>{me.account_type === 'ledger' ? '회사 장부' : '식권'}</strong></p></section><section className="purchase-card setting-group" aria-label="알림 및 초대"><button onClick={() => open('계정 설정')}>계정 설정<strong>이름 · 비밀번호</strong></button>{me.role === 'customer' && <button onClick={() => open('초대코드')}>초대코드 입력<ChevronRight size={16} /></button>}</section><section className="purchase-card setting-group">{[['쿠폰함', () => open('쿠폰함')], ['식권 상품', () => go(1)], ['공지사항', () => open('공지사항')], ['구매 인증 리뷰', () => open('리뷰')]].map(([label, action]) => <button key={label} onClick={action}>{label}<ChevronRight size={16} /></button>)}</section><section className="purchase-card setting-group"><a href="/privacy.html" target="_blank" rel="noreferrer">개인정보 처리방침<ChevronRight size={16} /></a><a href="/terms.html" target="_blank" rel="noreferrer">이용약관<ChevronRight size={16} /></a><p><span>웹 버전</span><strong>구매자 웹</strong></p><button className="danger-text" onClick={logout}>로그아웃<ChevronRight size={16} /></button></section><p className="muted">결제 알림(푸시)은 앱에서만 받을 수 있어요.</p></div>
    {page === '쿠폰함' && <>{readError && <><p role="alert">{readError}</p><button onClick={refresh} disabled={loading}>다시 시도</button></>}{wallet ? <CouponWallet wallet={wallet} /> : !readError && <p role="status">쿠폰 확인 중…</p>}</>}
    {page === '공지사항' && <ReadBoard key={page} kind={page} api={api} />}
    {page === '리뷰' && <ReviewBoard api={api} />}
    {page === '계정 설정' && <AccountSettings me={me} api={api} supabase={supabase} refresh={refresh} />}
    {page === '초대코드' && <InviteCodeEntry me={me} api={api} refresh={refresh} />}
    <nav className="app-tab-bar" aria-label="구매자 탭">{tabs.map(([label, Icon], index) => <button key={label} aria-current={tab === index && !page ? 'page' : undefined} onClick={() => go(index)}><Icon size={21} aria-hidden="true" /><span>{label}</span></button>)}</nav>
  </div>;
}
