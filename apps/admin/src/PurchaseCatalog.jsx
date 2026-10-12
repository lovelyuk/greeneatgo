import React, { useEffect, useRef, useState } from "react";
import PurchaseCheckout from "./PurchaseCheckout.jsx";
import { purchaseDisclosuresReady } from "./purchaseSafety.js";
export const won = (amount) => `${Number(amount).toLocaleString("ko-KR")}원`;
export default function PurchaseCatalog({
  api,
  me,
  revision,
  apiBaseUrl,
  legal,
  refresh,
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
  }, [revision]);
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
  return (
    <section className="purchase-card">
      <h2>판매 식권</h2>
      {error && <p role="alert">{error}</p>}
      {!catalog ? (
        error ? <p>상품을 불러오지 못했어요. 새로고침으로 다시 확인해 주세요.</p> : <p role="status">상품 확인 중…</p>
      ) : !eligible ? (
        <p>
          현재 구매 가능한 식권이 없어요. 회사 계약 및 계정 상태를 확인해
          주세요.
        </p>
      ) : (
        <>
          <p>{coupons?.merchant?.name || "식당 정보 확인 불가"}</p>
          {catalog.items.length === 0 && <p>현재 판매 중인 식권 상품이 없어요.</p>}
          <div className="purchase-products">
            {catalog.items.map((product) => (
              <button
                key={product.id}
                className={item?.id === product.id ? "selected" : "secondary"}
                disabled={busy}
                onClick={() =>
                  change(() => {
                    setItem(product);
                    setCoupon("");
                  })
                }
              >
                {product.name} 선택
              </button>
            ))}
          </div>
          {item && (
            <div className="purchase-detail">
              <h3>{item.name}</h3>
              <p>
                유료 {item.voucher_count}장 + 보너스 {item.bonus_count}장
              </p>
              <p>
                정상 단가 {won(item.unit_price)} · 판매가 {won(item.sale_price)}
              </p>
              <p>할인율 {item.discount_rate}%</p>
              <p>
                결제방법{" "}
                {item.kiwoom_pay_method === "BANK"
                  ? "계좌이체 전용"
                  : "통합결제창"}
              </p>
              {item.is_event && (
                <p>판매 종료 {item.event_end_at || "서버 정보 없음"}</p>
              )}
              <p>
                식권 유효기간은 현재 API에서 제공하지 않아요. 임의의 만료일을
                표시하지 않습니다.
              </p>
              {catalog.purchase_mode === "subsidized" && (
                <>
                  <p>직원 부담 {won(item.employee_pay_amount)}</p>
                  <p>회사 지원 합계 {won(item.total_company_subsidy_amount)}</p>
                  <p>
                    식당 지원 합계 {won(item.total_restaurant_subsidy_amount)}
                  </p>
                  <label>
                    사용 포인트
                    <input
                      inputMode="numeric"
                      disabled={busy}
                      value={points}
                      onChange={(e) => change(() => setPoints(e.target.value))}
                    />
                  </label>
                  <p>
                    잔여 포인트 {me.point_balance ?? "—"}P · 실제 사용 가능
                    금액은 서버에서 확인합니다.
                  </p>
                </>
              )}
              <label>
                할인 쿠폰
                <select
                  value={coupon}
                  disabled={busy}
                  onChange={(e) => change(() => setCoupon(e.target.value))}
                >
                  <option value="">사용 안 함</option>
                  {coupons?.items?.map((c) => (
                    <option key={c.id} value={`public:${c.id}`}>
                      {c.name} ({c.valid_until || "종료일 정보 없음"})
                    </option>
                  ))}
                  {coupons?.issued?.map((c) => (
                    <option key={c.id} value={`issued:${c.id}`}>
                      {c.coupon_snapshot?.name || "보유 쿠폰"} (
                      {c.valid_until || "종료일 정보 없음"})
                    </option>
                  ))}
                </select>
              </label>
              <button
                disabled={busy || !coupons?.merchant?.id}
                onClick={getQuote}
              >
                견적 확인
              </button>
              {quote && (
                <div className="purchase-quote" role="status">
                  <p>{quote.merchant_name}</p>
                  <p>쿠폰 할인 {won(quote.coupon_discount_amount)}</p>
                  {catalog.purchase_mode === "subsidized" && (
                    <p>
                      포인트 사용{" "}
                      {Number(quote.point_amount).toLocaleString("ko-KR")}P
                    </p>
                  )}
                  <strong>최종 결제 {won(quote.payment_amount)}</strong>
                  <p>결제 시 서버에서 가격·자격을 다시 확인합니다.</p>
                </div>
              )}
            </div>
          )}
        </>
      )}
      <PurchaseCheckout
        userId={me.user_id}
        refresh={refresh}
        api={api}
        apiBaseUrl={apiBaseUrl}
        payload={
          quote ? { ...payload, requested_point_amount: quote.point_amount } : payload
        }
        quote={quote}
        mode={catalog?.purchase_mode}
        legalReady={
          legal.ready &&
          purchaseDisclosuresReady(
            legal.terms,
            quote?.merchant_name || coupons?.merchant?.name,
          )
        }
      />
    </section>
  );
}
