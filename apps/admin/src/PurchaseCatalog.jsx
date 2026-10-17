import React, { useEffect, useMemo, useRef, useState } from "react";
import PurchaseCheckout from "./PurchaseCheckout.jsx";
import { ArrowLeft, CheckCircle2 } from 'lucide-react';

// Native ticket values are presentation only; every payable amount still comes from /quote.
const paymentMethod = product => product.kiwoom_pay_method === 'BANK' ? '계좌이체 전용' : '통합결제창';
const totalCount = product => product.total_count ?? product.voucher_count + product.bonus_count;
function couponBenefit(data) {
  // The API serializes issued snapshot decimals as strings.
  const value = typeof data.discount_value === 'number' || typeof data.discount_value === 'string'
    ? Number(data.discount_value) : NaN;
  if (!Number.isFinite(value) || value <= 0) return '할인 쿠폰';
  return data.discount_type === 'percent' ? `${value}%` : won(Math.floor(value));
}

export const won = (amount) => `${Number(amount).toLocaleString("ko-KR")}원`;
export default function PurchaseCatalog({
  api,
  me,
  revision,
  apiBaseUrl,
  legal,
  refresh,
  onClose,
  eventsOnly = false,
  active = true,
  purchaseActive = active,
  recoveryView = false,
  recoveryTarget,
  onRecoveryNeeded,
  onRecoveryEnded,
  onCatalog,
}) {
  const [catalog, setCatalog] = useState(null),
    [coupons, setCoupons] = useState(null),
    [item, setItem] = useState(null);
  const [coupon, setCoupon] = useState(""),
    [priced, setQuote] = useState(null),
    [error, setError] = useState("");
  const [sourceScope, setSourceScope] = useState(null);
  const [retry, setRetry] = useState(0);
  const accountScope = JSON.stringify([me.user_id, me.role, me.status, me.company_id, revision, eventsOnly]);
  const liveScope = useRef(accountScope);
  liveScope.current = accountScope;
  const [points, setPoints] = useState("0");
  const [returnNotice, setReturnNotice] = useState('');
  const generation = useRef(0);
  useEffect(() => {
    let active = true;
    setSourceScope(null);
    setCatalog(null);
    setCoupons(null);
    setItem(null);
    setCoupon("");
    setPoints('0');
    setQuote(null);
    setError("");
    Promise.all([api("/vouchers/products"), api("/coupons")])
      .then(([products, wallet]) => {
        if (active && liveScope.current === accountScope) {
          setCatalog(products);
          onCatalog?.(products);
          setCoupons(wallet);
          setSourceScope(accountScope);
        }
      })
      .catch((e) => {
        if (active && liveScope.current === accountScope && !e.stale) setError(e.message);
      });
    return () => { active = false; };
  }, [accountScope]);
  function change(action) {
    generation.current++;
    setReturnNotice('');
    setQuote(null);
    setError("");
    action();
  }
  const [kind, couponId] = coupon.split(":");
  const payload = item
    ? {
        product_id: item.id,
        requested_point_amount:
          catalog?.purchase_mode === "subsidized" ? Number(points) : 0,
        ...(couponId
          ? { [kind === "issued" ? "user_coupon_id" : "coupon_id"]: couponId }
          : {}),
      }
    : null;
  const validPoints = /^[0-9]+$/.test(points) && Number.isSafeInteger(Number(points)) && Number(points) <= 100000000;
  const eligible =
    (catalog?.purchase_mode === "voucher" && me.role === "customer") ||
    (catalog?.purchase_mode === "subsidized" && me.role === "employee");
  // Bind display and checkout in render, not only in an effect: an old amount
  // must never remain payable for a render after any source/input changes.
  const signature = item && eligible && sourceScope === accountScope && coupons?.merchant?.id && validPoints
    ? JSON.stringify([accountScope, item, catalog.purchase_mode, coupons.merchant, coupon, points]) : null;
  const currentSignature = useRef(signature);
  currentSignature.current = purchaseActive ? signature : null;
  const quote = signature && priced?.signature === signature ? priced.result : null;
  // A tab round-trip retains displayed pricing/consent, but changes the quote
  // identity observed by the SDK preload guard so a hidden attempt cannot resume.
  const checkoutQuote = useMemo(() => purchaseActive && quote ? { ...quote } : null, [purchaseActive, quote]);
  const busy = Boolean(signature && !quote && !error);
  useEffect(() => {
    const run = ++generation.current;
    let alive = true, timeout;
    if (!purchaseActive || (signature && priced?.signature === signature)) return;
    setQuote(null);
    setError('');
    if (item && !validPoints) {
      setError('포인트는 0 이상의 정수(최대 100,000,000)로 입력해 주세요.');
      return;
    }
    if (!signature) return;
    const current = () => alive && run === generation.current && currentSignature.current === signature;
    // /quote is a read-only pricing POST. It creates/reserves no orders or funds.
    // Debounce intent, never normalize the input from the returned point amount.
    const timer = setTimeout(async () => {
      try {
        const result = await Promise.race([
          api('/vouchers/quote', payload, { requestTimeoutMs: 10000 }),
          new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error('금액 확인 시간이 초과됐어요. 다시 확인해 주세요.')), 10000); }),
        ]);
        if (!current()) return;
        if (result.product_id !== item.id || result.purchase_mode !== catalog.purchase_mode ||
            result.merchant_id !== coupons.merchant.id || !result.merchant_name)
          throw new Error('상품·식당 견적 정보를 확인할 수 없어요.');
        if (!['gross_amount', 'coupon_discount_amount', 'point_amount', 'payment_amount'].every(key => Number.isSafeInteger(result[key]) && result[key] >= 0) ||
            result.gross_amount <= 0 || result.gross_amount - result.coupon_discount_amount - result.point_amount !== result.payment_amount ||
            result.point_amount > payload.requested_point_amount ||
            (catalog.purchase_mode === 'voucher' && (result.point_amount !== 0 || result.payment_amount === 0)))
          throw new Error('견적 금액 정보를 확인하지 못했어요.');
        setQuote({ signature, result });
      } catch (e) {
        if (current()) setError(e.message || '금액을 확인하지 못했어요. 다시 확인해 주세요.');
      } finally { clearTimeout(timeout); }
    }, 250);
    return () => { alive = false; clearTimeout(timer); clearTimeout(timeout); };
  }, [signature, retry, purchaseActive]);
  const visibleProducts = catalog?.items.filter(product => !eventsOnly || product.is_event) || [];
  const choices = [
    ...(coupons?.issued || []).map(c => ({ ...c, value: `issued:${c.id}`, data: c.coupon_snapshot || {}, issued: true })),
    ...(coupons?.items || []).map(c => ({ ...c, value: `public:${c.id}`, data: c, issued: false })),
  ];
  return (
    <section className="purchase-catalog">
      <header className="catalog-header">
        {item && <button className="catalog-back" aria-label="상품 다시 선택" onClick={() => change(() => { setItem(null); setCoupon(''); })}><ArrowLeft size={24} /></button>}
        {!item && onClose && <button className="catalog-back" aria-label="홈으로" onClick={onClose}><ArrowLeft size={24} /></button>}
        <h2>{item ? '할인 선택' : eventsOnly ? '이벤트 식권' : '식권 구매'}</h2>
      </header>
      {!item && catalog && eligible && <p className="catalog-count">{visibleProducts.length}종</p>}
      {(item && !validPoints) ? <p role="alert">포인트는 0 이상의 정수(최대 100,000,000)로 입력해 주세요.</p> : error && <p role="alert">{error}</p>}
      {returnNotice && <p role="status">{returnNotice}</p>}
      {!catalog ? (
        error ? <p>상품을 불러오지 못했어요. 새로고침으로 다시 확인해 주세요.</p> : <p role="status">상품 확인 중…</p>
      ) : !eligible ? (
        <p>현재 구매 가능한 식권이 없어요. 회사 계약 및 계정 상태를 확인해 주세요.</p>
      ) : (
        <>
          {catalog.items.length === 0 && <p>현재 판매 중인 식권 상품이 없어요.</p>}
          {eventsOnly && catalog.items.length > 0 && visibleProducts.length === 0 && <p>현재 판매 중인 이벤트 식권이 없어요. 구매 탭에서 전체 상품을 확인하세요.</p>}
          {!item && <div className="purchase-products">
            {visibleProducts.map(product => (
              <button key={product.id} aria-label={`${product.name} 선택`} className={`product-ticket ${product.is_event ? 'event' : ''}`} onClick={() => change(() => { setItem(product); setCoupon(''); })}>
                <span className="product-rail" aria-hidden="true"><span>TICKET</span></span>
                <span className="product-copy">
                  <span className="product-ticket-top"><span>{totalCount(product)}장 식권</span><span className="purchase-pill" aria-hidden="true">구매하기 ›</span></span>
                  <b className="product-price">{won(catalog.purchase_mode === 'subsidized' ? product.employee_pay_amount ?? product.sale_price : product.sale_price)}</b>
                  <strong>{product.name}</strong>
                  <span className="product-payment">결제방법 {paymentMethod(product)}{product.bonus_count > 0 ? ` · 보너스 ${product.bonus_count}장` : ''}</span>
                </span>
              </button>
            ))}
          </div>}
          {item && (
            <div className="purchase-detail">
              <h3 className="discount-product-title">{item.name}</h3>
              <p className="discount-caption">결제 전에 쿠폰과 포인트를 선택해 주세요.</p>
              <fieldset className="coupon-options">
                <legend>쿠폰</legend>
                <label className={`no-coupon-tile ${coupon === '' ? 'selected' : ''}`}>
                  <input type="radio" name="catalog-coupon" aria-label="쿠폰 사용 안 함" checked={coupon === ''} onChange={() => change(() => setCoupon(''))} />
                  <span>쿠폰 사용 안 함</span>
                </label>
                {choices.map(c => <label key={c.value} className={`selection-coupon-ticket ${c.data.discount_type === 'percent' ? 'percent' : ''} ${c.issued ? 'issued' : ''} ${coupon === c.value ? 'selected' : ''}`}>
                  <input type="radio" name="catalog-coupon" aria-label={c.data.name || '보유 쿠폰'} checked={coupon === c.value} onChange={() => change(() => setCoupon(c.value))} />
                  <span className="product-rail" aria-hidden="true"><span>COUPON</span></span>
                  <span className="selection-coupon-copy">
                    <span className="coupon-merchant">{coupons?.merchant?.name || '식당 정보 확인 불가'}{coupon === c.value && <CheckCircle2 size={20} aria-hidden="true" />}</span>
                    <b>{couponBenefit(c.data)}</b>
                    <strong>{c.data.name || '보유 쿠폰'}</strong>
                    {c.issued && <span className="issued-caption">보유 쿠폰</span>}
                    <span className="coupon-validity">유효기간 {c.valid_until || c.data.valid_until || '종료일 정보 없음'}</span>
                  </span>
                </label>)}
              </fieldset>
              <label className="catalog-select-compat">
                할인 쿠폰
                <select aria-label="할인 쿠폰" value={coupon} onChange={e => change(() => setCoupon(e.target.value))}>
                  <option value="">사용 안 함</option>
                  {choices.map(c => <option key={c.value} value={c.value}>{c.data.name || '보유 쿠폰'} ({c.valid_until || c.data.valid_until || '종료일 정보 없음'})</option>)}
                </select>
              </label>
              {catalog.purchase_mode === 'subsidized' && <div className="catalog-points">
                <div className="points-heading"><h3>포인트</h3><span>보유 {me.point_balance ?? '—'}P</span></div>
                <label>사용 포인트<input inputMode="numeric" value={points} onChange={e => change(() => setPoints(e.target.value))} /></label>
                <p>실제 사용 가능 금액은 서버에서 확인합니다.</p>
                <div className="product-terms"><p>직원 부담 {won(item.employee_pay_amount)}</p><p>회사 지원 합계 {won(item.total_company_subsidy_amount)}</p><p>식당 지원 합계 {won(item.total_restaurant_subsidy_amount)}</p></div>
              </div>}
              {busy && <p role="status">금액 확인 중…</p>}
              {error && signature && <button onClick={() => { setError(''); setRetry(value => value + 1); }}>금액 다시 확인</button>}
              {quote && <div className="purchase-quote" role="status">
                <p className="quote-merchant">{quote.merchant_name}</p>
                <p className="quote-row"><span>상품 금액</span>{' '}<b>{won(quote.gross_amount)}</b></p>
                <p className="quote-row quote-discount"><span>쿠폰 할인</span>{' '}<b>{won(quote.coupon_discount_amount)}</b></p>
                {catalog.purchase_mode === 'subsidized' && <p className="quote-row quote-discount"><span>포인트 사용</span>{' '}<b>{Number(quote.point_amount).toLocaleString('ko-KR')}P</b></p>}
                <strong className="quote-row quote-total"><span>최종 결제</span>{' '}<b>{won(quote.payment_amount)}</b></strong>
                <p className="quote-authority">결제 시 서버에서 가격·자격을 다시 확인합니다.</p>
              </div>}
              <div className="product-terms">
                <p>유료 {item.voucher_count}장 + 보너스 {item.bonus_count}장</p>
                <p>정상 단가 {won(item.unit_price)} · 판매가 {won(item.sale_price)}</p>
                <p>할인율 {item.discount_rate}%</p>
                <p>결제방법 {paymentMethod(item)}</p>
                {item.is_event && <p>판매 종료 {item.event_end_at || '서버 정보 없음'}</p>}
                <p>식권 유효기간은 현재 API에서 제공하지 않아요. 임의의 만료일을 표시하지 않습니다.</p>
              </div>
            </div>
          )}
        </>
      )}
      <div className="catalog-checkout">
      <PurchaseCheckout
        active={active}
        purchaseActive={purchaseActive}
        recoveryView={recoveryView}
        recoveryTarget={recoveryTarget}
        onRecoveryNeeded={onRecoveryNeeded}
        onCheckoutEnded={kind => {
          generation.current++; setQuote(null); setItem(null); setCoupon(''); setPoints('0'); setError('');
          setReturnNotice(kind === 'mobile_cancel' ? '구매 진행을 취소했어요' : kind === 'locally_abandoned' ? '구매 진행을 중단했어요. PG 취소·환불 확정은 아니에요.' : kind === 'verified_closed' ? '이전 주문의 종료를 확인했어요.' : '구매 진행이 종료됐어요');
          onRecoveryEnded?.();
        }}
        clearQuote={() => { generation.current++; setQuote(null); setItem(null); setCoupon(''); setPoints('0'); }}
        userId={me.user_id}
        refresh={refresh}
        api={api}
        apiBaseUrl={apiBaseUrl}
        payload={
          quote ? { ...payload, requested_point_amount: quote.point_amount } : payload
        }
        quote={checkoutQuote}
        paymentMethod={item?.kiwoom_pay_method || 'TOTAL'}
        mode={catalog?.purchase_mode}
        legalReady={legal.ready}
      />
      </div>
    </section>
  );
}
