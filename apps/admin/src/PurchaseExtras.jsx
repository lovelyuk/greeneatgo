import React, { useEffect, useRef, useState } from 'react';
import { Star, ImagePlus, X } from 'lucide-react';
import { safeBannerLink, rewardLabel, reviewPayload, validateNewPassword } from './purchaseExtras.js';

const won = value => `${Math.abs(Number(value) || 0).toLocaleString('ko-KR')}원`;
const shortDate = raw => {
  const date = raw ? new Date(raw) : null;
  return date && !Number.isNaN(date.getTime()) ? `${date.getMonth() + 1}월 ${date.getDate()}일` : '날짜 정보 없음';
};

/* ---------------- 계정 설정 (이름·비밀번호) ---------------- */
export function AccountSettings({ me, api, supabase, refresh }) {
  const [name, setName] = useState(me.display_name || ''), [current, setCurrent] = useState(''), [next, setNext] = useState(''), [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [message, setMessage] = useState('');
  async function saveName(e) {
    e.preventDefault(); const trimmed = name.trim();
    if (busy || !trimmed || trimmed === me.display_name) return;
    setBusy(true); setError(''); setMessage('');
    try { await api('/me', { display_name: trimmed }, { method: 'PATCH' }); await refresh(); setMessage('이름을 변경했어요.'); }
    catch (err) { if (!err.stale) setError(err.message); }
    finally { setBusy(false); }
  }
  async function savePassword(e) {
    e.preventDefault(); if (busy) return;
    const problem = validateNewPassword(current, next, confirm);
    if (problem) { setError(problem); setMessage(''); return; }
    setBusy(true); setError(''); setMessage('');
    try {
      const { data } = await supabase.auth.getSession();
      const email = data.session?.user?.email;
      if (!email) throw new Error('이메일 계정만 비밀번호를 변경할 수 있어요.');
      // Re-authenticate with the current password before changing it.
      const verify = await supabase.auth.signInWithPassword({ email, password: current });
      if (verify.error) throw new Error('현재 비밀번호가 올바르지 않아요.');
      const { error: updateError } = await supabase.auth.updateUser({ password: next });
      if (updateError) throw new Error(updateError.message || '비밀번호를 변경하지 못했어요.');
      setCurrent(''); setNext(''); setConfirm(''); setMessage('비밀번호를 변경했어요.');
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <section aria-label="계정 설정">
    <h1>계정 설정</h1>
    <form className="purchase-card" onSubmit={saveName}>
      <h2>이름 변경</h2>
      <label>이름<input required maxLength={80} value={name} onChange={e => setName(e.target.value)} /></label>
      <button disabled={busy || !name.trim() || name.trim() === me.display_name}>이름 저장</button>
    </form>
    <form className="purchase-card" onSubmit={savePassword}>
      <h2>비밀번호 변경</h2>
      <label>현재 비밀번호<input type="password" autoComplete="current-password" value={current} onChange={e => setCurrent(e.target.value)} /></label>
      <label>새 비밀번호<input type="password" autoComplete="new-password" value={next} onChange={e => setNext(e.target.value)} /></label>
      <label>새 비밀번호 확인<input type="password" autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} /></label>
      <button disabled={busy || !current || !next || !confirm}>비밀번호 변경</button>
    </form>
    {message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}
  </section>;
}

/* ---------------- 초대코드 입력 (일반 구매자 → 회사 가입 신청) ---------------- */
export function InviteCodeEntry({ me, api, refresh }) {
  const [code, setCode] = useState(''), [department, setDepartment] = useState(''), [employeeNo, setEmployeeNo] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [done, setDone] = useState(false);
  const lock = useRef(false);
  if (me.role !== 'customer') return <section><h1>초대코드 입력</h1><p className="empty-state">이미 회사에 소속된 계정이에요.</p></section>;
  async function submit(e) {
    e.preventDefault(); if (lock.current || code.trim().length < 4) return;
    lock.current = true; setBusy(true); setError('');
    try {
      await api('/join/request', {
        invite_code: code.trim(), display_name: me.display_name || '사용자',
        ...(me.phone ? { phone: me.phone } : {}),
        ...(department.trim() ? { department: department.trim() } : {}),
        ...(employeeNo.trim() ? { employee_no: employeeNo.trim() } : {}),
      });
      setDone(true); await refresh();
    } catch (err) { if (!err.stale) setError(err.message); }
    finally { lock.current = false; setBusy(false); }
  }
  return <section aria-label="초대코드 입력">
    <h1>초대코드 입력</h1>
    {done ? <p role="status">가입 신청을 보냈어요. 회사관리자 승인 후 장부 결제를 이용할 수 있어요.</p> : <form className="purchase-card" onSubmit={submit}>
      <p className="muted">회사에서 받은 초대코드를 입력하면 회사관리자에게 가입 승인을 요청해요.</p>
      <label>초대코드<input required minLength={4} maxLength={64} value={code} onChange={e => setCode(e.target.value)} /></label>
      <label>부서 (선택)<input maxLength={120} value={department} onChange={e => setDepartment(e.target.value)} /></label>
      <label>사번 (선택)<input maxLength={40} value={employeeNo} onChange={e => setEmployeeNo(e.target.value)} /></label>
      <button disabled={busy || code.trim().length < 4}>가입 신청</button>
    </form>}
    {error && <p role="alert">{error}</p>}
  </section>;
}

/* ---------------- 리뷰 (목록 + 작성) ---------------- */
function ReviewForm({ tx, api, onDone, onCancel }) {
  const [rating, setRating] = useState(5), [content, setContent] = useState(''), [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const lock = useRef(false);
  async function submit(e) {
    e.preventDefault(); if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try {
      const urls = [];
      for (const file of files) {
        const form = new FormData(); form.append('file', file, file.name);
        const uploaded = await api('/reviews/images', form);
        if (typeof uploaded?.image_url !== 'string') throw new Error('사진을 올리지 못했어요.');
        urls.push(uploaded.image_url);
      }
      await api('/reviews', reviewPayload(tx.id, rating, content, urls));
      onDone();
    } catch (err) { if (!err.stale) setError(err.message); }
    finally { lock.current = false; setBusy(false); }
  }
  return <form className="purchase-card review-form" onSubmit={submit} aria-label="리뷰 작성">
    <h2>리뷰 작성</h2>
    <p className="muted">{shortDate(tx.created_at)} · {won(tx.amount)}</p>
    <div className="star-row" role="radiogroup" aria-label="별점">
      {[1, 2, 3, 4, 5].map(n => <button type="button" key={n} role="radio" aria-checked={rating === n} aria-label={`${n}점`} onClick={() => setRating(n)}><Star size={26} fill={n <= rating ? 'currentColor' : 'none'} /></button>)}
    </div>
    <label>후기 내용 (선택)<textarea maxLength={2000} rows={4} value={content} onChange={e => setContent(e.target.value)} /></label>
    <div className="review-files">
      {files.map((file, i) => <span key={`${file.name}-${i}`} className="review-file">{file.name}<button type="button" aria-label={`${file.name} 삭제`} onClick={() => setFiles(files.filter((_, j) => j !== i))}><X size={14} /></button></span>)}
      {files.length < 3 && <label className="review-file-add"><ImagePlus size={18} />사진 추가 ({files.length}/3)<input type="file" accept="image/*" multiple hidden onChange={e => { setFiles([...files, ...Array.from(e.target.files || [])].slice(0, 3)); e.target.value = ''; }} /></label>}
    </div>
    <div className="review-actions"><button type="button" className="secondary" onClick={onCancel} disabled={busy}>취소</button><button disabled={busy}>{busy ? '등록 중…' : '등록하기'}</button></div>
    {error && <p role="alert">{error}</p>}
  </form>;
}

export function ReviewBoard({ api }) {
  const [data, setData] = useState(null), [reviewable, setReviewable] = useState([]), [error, setError] = useState(''), [revision, setRevision] = useState(0), [writing, setWriting] = useState(null), [notice, setNotice] = useState('');
  useEffect(() => {
    let alive = true; setError(''); setData(null);
    Promise.all([api('/reviews'), api('/vouchers/reviewable-transactions').catch(() => ({ items: [] }))])
      .then(([reviews, txs]) => { if (alive) { setData(reviews); setReviewable(Array.isArray(txs?.items) ? txs.items : []); } })
      .catch(e => { if (alive && !e.stale) setError(e.message); });
    return () => { alive = false; };
  }, [revision]);
  return <>
    <h1>리뷰</h1>
    {notice && <p role="status">{notice}</p>}
    {error ? <><p role="alert">{error}</p><button onClick={() => setRevision(revision + 1)}>다시 시도</button></> : !data ? <p role="status">불러오는 중…</p> : <>
      <p className="review-average"><Star size={18} fill="currentColor" /> {data.average_rating ?? 0} ({data.review_count ?? 0}개 후기)</p>
      {writing ? <ReviewForm tx={writing} api={api} onCancel={() => setWriting(null)} onDone={() => { setWriting(null); setNotice('리뷰를 등록했어요.'); setRevision(revision + 1); }} /> : reviewable.length > 0 && <>
        <h2>작성 가능한 리뷰</h2>
        {reviewable.map(tx => <article key={tx.id} className="purchase-card"><strong>리뷰 작성 가능</strong><p className="muted">{shortDate(tx.created_at)} · {won(tx.amount)}</p><button onClick={() => { setNotice(''); setWriting(tx); }}>리뷰 쓰기</button></article>)}
      </>}
      {!data.items?.length ? <p className="empty-state">아직 등록된 리뷰가 없어요.</p> : data.items.map(row => <article key={row.id} className="purchase-card">
        <h2>{row.author_name || '사용자'} <span className="review-stars" aria-label={`${row.rating}점`}>{'★'.repeat(row.rating || 0)}{'☆'.repeat(5 - (row.rating || 0))}</span></h2>
        {row.status === 'hidden' && row.is_own && <p className="muted">관리자 숨김 · 나에게만 표시</p>}
        {row.content && <p className="pre-line">{row.content}</p>}
        {Array.isArray(row.image_urls) && row.image_urls.length > 0 && <div className="review-images">{row.image_urls.map(url => <img key={url} src={url} alt="리뷰 사진" loading="lazy" />)}</div>}
        {row.owner_reply && <p className="owner-reply">사장님 답변 · {row.owner_reply}</p>}
      </article>)}
    </>}
  </>;
}

/* ---------------- 제휴 배너 ---------------- */
export function PartnerBanner({ api, placement = 'home_bottom', onCouponIssued }) {
  const [banners, setBanners] = useState(null), [page, setPage] = useState(0), [toast, setToast] = useState('');
  const impressed = useRef(new Set()), lock = useRef(false), box = useRef(null);
  useEffect(() => {
    let alive = true;
    api(`/banners?placement=${placement}`).then(d => { if (alive) setBanners(Array.isArray(d?.items) ? d.items : []); }).catch(() => { if (alive) setBanners([]); });
    return () => { alive = false; };
  }, [placement]);
  useEffect(() => {
    if (!banners || banners.length < 2) return undefined;
    const timer = setInterval(() => setPage(p => (p + 1) % banners.length), 5000);
    return () => clearInterval(timer);
  }, [banners]);
  // Impression after the current banner is >=50% visible for one second (same rule as the app).
  useEffect(() => {
    const current = banners?.[page];
    if (!current || !box.current || typeof IntersectionObserver === 'undefined') return undefined;
    let timer = null;
    const observer = new IntersectionObserver(([entry]) => {
      clearTimeout(timer);
      if (entry.isIntersecting && entry.intersectionRatio >= 0.5 && !impressed.current.has(current.id))
        timer = setTimeout(() => {
          if (impressed.current.has(current.id)) return;
          impressed.current.add(current.id);
          api('/banners/impressions', { items: [{ banner_id: current.id, placement }] }).catch(() => {});
        }, 1000);
    }, { threshold: [0, 0.5, 1] });
    observer.observe(box.current);
    return () => { clearTimeout(timer); observer.disconnect(); };
  }, [banners, page]);
  if (!banners?.length) return null;
  const current = banners[Math.min(page, banners.length - 1)];
  async function click() {
    if (lock.current) return; lock.current = true;
    // Reserve the tab synchronously so popup blockers allow it.
    const opened = window.open('about:blank', '_blank');
    if (opened) opened.opener = null;
    try {
      const result = await api(`/banners/${current.id}/click`, {});
      if (result?.reward_granted) setToast(result.reward_type === 'point' && result.amount != null ? `${result.amount}P가 지급됐어요.` : result.reward_type === 'coupon' || result.user_coupon_id ? '쿠폰이 발급됐어요.' : '리워드가 지급됐어요.');
      if (result?.reward_granted && (result.reward_type === 'coupon' || result.user_coupon_id)) onCouponIssued?.();
      const link = safeBannerLink(result?.link_url);
      if (link && opened) opened.location.replace(link); else opened?.close();
    } catch (e) {
      opened?.close();
      if (e.status === 410) { setToast('종료된 광고예요.'); setBanners(banners.filter(b => b.id !== current.id)); setPage(0); }
      else setToast('네트워크 연결을 확인한 뒤 다시 시도해 주세요.');
    } finally { setTimeout(() => { lock.current = false; }, 1500); }
  }
  const reward = rewardLabel(current.reward);
  return <section className="partner-banner" ref={box} aria-label="제휴 광고">
    <button className="partner-banner-card" onClick={click} aria-label={`광고, ${current.image_alt || current.title || ''}, ${current.partner_name || ''}${reward ? `, ${reward}` : ''}`}>
      <img src={current.image_url} alt="" onError={() => setBanners(banners.filter(b => b.id !== current.id))} />
      <span className="ad-badge">AD</span>
      {reward && <span className="reward-chip">{reward}</span>}
    </button>
    {banners.length > 1 && <div className="banner-dots">{banners.map((b, i) => <button key={b.id} aria-label={`${i + 1}번째 광고`} aria-current={i === page ? 'true' : undefined} onClick={() => setPage(i)} />)}</div>}
    {toast && <p role="status">{toast}</p>}
  </section>;
}
