import React, { useEffect, useRef, useState } from "react";
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
}) {
  const [catalog, setCatalog] = useState(null),
    [coupons, setCoupons] = useState(null),
    [item, setItem] = useState(null);
  const [coupon, setCoupon] = useState(""),
    [quote, setQuote] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [points, setPoints] = useState("0");
  const generation = useRef(0),
    lock = useRef(false);
  useEffect(() => {
    const run = ++generation.current;
    setCatalog(null);
    setCoupons(null);
    setItem(null);
    setCoupon("");
    setQuote(null);
    setError("");
    Promise.all([api("/vouchers/products"), api("/coupons")])
      .then(([products, wallet]) => {
        if (generation.current === run) {
          setCatalog(products);
          setCoupons(wallet);
        }
      })
      .catch((e) => {
        if (generation.current === run && !e.stale) setError(e.message);
      });
    return () => {
      generation.current++;
    };
  }, [revision, eventsOnly]);
  function change(action) {
    generation.current++;
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
  async function getQuote() {
    if (!/^[0-9]+$/.test(points) || !Number.isSafeInteger(Number(points))) {
      setError("포인트는 0 이상의 정수로 입력해 주세요.");
      return;
    }
    if (lock.current || !item) return;
    const run = generation.current;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api("/vouchers/quote", payload);
      if (run !== generation.current) return;
      if (
        result.product_id !== item.id ||
        result.purchase_mode !== catalog.purchase_mode ||
        result.merchant_id !== coupons?.merchant?.id ||
        !result.merchant_name
      )
        throw new Error("상품·식당 견적 정보를 확인할 수 없어요.");
      if (
        ![
          "gross_amount",
          "coupon_discount_amount",
          "point_amount",
          "payment_amount",
        ].every(
          (key) => Number.isSafeInteger(result[key]) && result[key] >= 0,
        ) ||
        result.gross_amount <= 0 ||
        result.gross_amount -
          result.coupon_discount_amount -
          result.point_amount !==
          result.payment_amount ||
        (catalog.purchase_mode === "voucher" &&
          (result.point_amount !== 0 || result.payment_amount === 0))
      )
        throw new Error("견적 금액 정보를 확인하지 못했어요.");
      setQuote(result);
    } catch (e) {
      if (!e.stale && run === generation.current) setError(e.message);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  const eligible =
    (catalog?.purchase_mode === "voucher" && me.role === "customer") ||
    (catalog?.purchase_mode === "subsidized" && me.role === "employee");
  const visibleProducts = catalog?.items.filter(product => !eventsOnly || product.is_event) || [];
  const choices = [
    ...(coupons?.issued || []).map(c => ({ ...c, value: `issued:${c.id}`, data: c.coupon_snapshot || {}, issued: true })),
    ...(coupons?.items || []).map(c => ({ ...c, value: `public:${c.id}`, data: c, issued: false })),
  ];
  return (
    <section className="purchase-catalog">
      <header className="catalog-header">
        {item && <button className="catalog-back" aria-label="상품 다시 선택" disabled={busy} onClick={() => change(() => { setItem(null); setCoupon(''); })}><ArrowLeft size={24} /></button>}
        {!item && onClose && <button className="catalog-back" aria-label="홈으로" onClick={onClose}><ArrowLeft size={24} /></button>}
        <h2>{item ? '할인 선택' : eventsOnly ? '이벤트 식권' : '식권 구매'}</h2>
      </header>
      {!item && catalog && eligible && <p className="catalog-count">{visibleProducts.length}종</p>}
      {error && <p role="alert">{error}</p>}
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
              <button key={product.id} aria-label={`${product.name} 선택`} className={`product-ticket ${product.is_event ? 'event' : ''}`} disabled={busy} onClick={() => change(() => { setItem(product); setCoupon(''); })}>
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
              <fieldset className="coupon-options" disabled={busy}>
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
                <select aria-label="할인 쿠폰" value={coupon} disabled={busy} onChange={e => change(() => setCoupon(e.target.value))}>
                  <option value="">사용 안 함</option>
                  {choices.map(c => <option key={c.value} value={c.value}>{c.data.name || '보유 쿠폰'} ({c.valid_until || c.data.valid_until || '종료일 정보 없음'})</option>)}
                </select>
              </label>
              {catalog.purchase_mode === 'subsidized' && <div className="catalog-points">
                <div className="points-heading"><h3>포인트</h3><span>보유 {me.point_balance ?? '—'}P</span></div>
                <label>사용 포인트<input inputMode="numeric" disabled={busy} value={points} onChange={e => change(() => setPoints(e.target.value))} /></label>
                <p>실제 사용 가능 금액은 서버에서 확인합니다.</p>
                <div className="product-terms"><p>직원 부담 {won(item.employee_pay_amount)}</p><p>회사 지원 합계 {won(item.total_company_subsidy_amount)}</p><p>식당 지원 합계 {won(item.total_restaurant_subsidy_amount)}</p></div>
              </div>}
              <button className="quote-request" disabled={busy || !coupons?.merchant?.id} onClick={getQuote}>견적 확인</button>
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
        clearQuote={() => { generation.current++; setQuote(null); }}
        userId={me.user_id}
        refresh={refresh}
        api={api}
        apiBaseUrl={apiBaseUrl}
        payload={
          quote ? { ...payload, requested_point_amount: quote.point_amount } : payload
        }
        quote={quote}
        mode={catalog?.purchase_mode}
        legalReady={legal.ready}
      />
      </div>
    </section>
  );
}
