import React, { useEffect, useRef, useState } from "react";
import { safeCheckoutUrl } from "./purchaseSafety.js";
import { validateReceiptUrl } from "./receiptUtils.js";

export default function PurchaseCheckout({
  api,
  apiBaseUrl,
  quote,
  payload,
  mode,
  legalReady,
  refresh,
  userId,
}) {
  const [completion, setCompletion] = useState(null),
    [canceled, setCanceled] = useState(false);
  const [order, setOrder] = useState(null),
    [busy, setBusy] = useState(false),
    [consent, setConsent] = useState(false),
    [error, setError] = useState("");
  const [unknown, setUnknown] = useState(false);
  const storageKey = `greeneat-purchase-pending:${userId}`;
  const lock = useRef(false),
    alive = useRef(true),
    popup = useRef(null);
  useEffect(() => {
    alive.current = true;
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
      if (saved?.unknown) setUnknown(true);
      else if (
        saved &&
        typeof saved.order_id === "string" &&
        Number.isSafeInteger(saved.amount) &&
        saved.amount > 0 &&
        ["voucher", "subsidized"].includes(saved.mode)
      )
        setOrder(saved);
      else if (saved) setUnknown(true);
    } catch {
      setUnknown(true);
    }
    return () => {
      alive.current = false;
      popup.current?.close();
    };
  }, [storageKey]);
  function saveOrder(next) {
    sessionStorage.setItem(storageKey, JSON.stringify(next));
    setOrder(next);
  }
  async function purchase() {
    if (lock.current || order || unknown || !quote || !legalReady || !consent)
      return;
    lock.current = true;
    setBusy(true);
    setError("");
    if (quote.payment_amount > 0) {
      popup.current = window.open("about:blank", "_blank");
      if (!popup.current) {
        setError("팝업이 차단됐어요. 팝업을 허용해 주세요.");
        lock.current = false;
        setBusy(false);
        return;
      }
      popup.current.opener = null;
    }
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({ unknown: true }));
      const result = await api(
        mode === "subsidized"
          ? "/vouchers/purchase-subsidized"
          : "/vouchers/purchase",
        payload,
      );
      if (!alive.current) return;
      if (
        !result.order_id ||
        !Number.isSafeInteger(result.amount) ||
        result.amount < 0 ||
        result.product_id !== payload.product_id
      )
        throw new Error("주문 응답을 확인하지 못했어요.");
      const next = {
        order_id: result.order_id,
        amount: result.amount,
        mode,
        checkout_started: false,
      };
      const pricingMatchesQuote =
        result.amount === quote.payment_amount &&
        ["gross_amount", "coupon_discount_amount", "point_amount"].every(
          (key) => Number.isSafeInteger(result[key]) && result[key] === quote[key],
        );
      if (result.amount === 0) {
        // Zero-card orders are already issued atomically by the purchase API.
        // /payments/confirm accepts positive amounts only; never invent a zero
        // confirmation or trust point_only alone without server fulfillment.
        const issued = result.fulfillment;
        if (
          mode !== "subsidized" || result.point_only !== true ||
          result.card_amount !== 0 || result.checkout_url !== null ||
          issued?.status !== "done" || issued.order_id !== result.order_id ||
          issued.card_amount !== 0 ||
          !Number.isSafeInteger(issued.issued_count) || issued.issued_count <= 0 ||
          issued.issued_count !== result.total_count ||
          !Number.isSafeInteger(issued.point_amount) || issued.point_amount <= 0
        ) {
          sessionStorage.setItem(storageKey, JSON.stringify({ ...next, unknown: true }));
          throw new Error("포인트 주문의 서버 발급 결과를 확인하지 못했어요.");
        }
        popup.current?.close();
        sessionStorage.removeItem(storageKey);
        setOrder(null);
        setCompletion({
          order_id: result.order_id,
          status: issued.status,
          amount: result.amount,
          product_name: result.product_name,
          merchant_name: quote.merchant_name,
          issued_count: issued.issued_count,
          payment: { method: "POINT", method_label: "포인트" },
          pricing: { point_amount: issued.point_amount },
          pricing_discrepancy: !pricingMatchesQuote || issued.point_amount !== result.point_amount,
          accepted_pricing: quote,
        });
        await refresh();
        return;
      }
      saveOrder(next);
      if (result.amount > 0) {
        const url = safeCheckoutUrl(result.checkout_url, apiBaseUrl);
        if (!url) {
          popup.current?.close();
          setError(
            "결제 제공자/결제창 URL 정보가 올바르지 않아 결제를 차단했어요.",
          );
          return;
        }
        if (
          !pricingMatchesQuote ||
          !popup.current ||
          popup.current.closed
        ) {
          popup.current?.close();
          setError(
            "최종 주문 금액 또는 결제창 상태가 변경되어 자동 진입을 차단했어요.",
          );
          return;
        }
        saveOrder({ ...next, checkout_started: true });
        popup.current.location.replace(url);
      } else popup.current?.close();
    } catch (e) {
      popup.current?.close();
      if (alive.current && !e.stale) {
        setUnknown(true);
        setError(
          `${e.message} 주문 생성 결과를 확인할 수 없어요. 중복 구매하지 말고 관리자에게 거래 확인을 요청해 주세요.`,
        );
      }
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function confirm() {
    if (lock.current || !order) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api("/payments/confirm", {
        order_id: order.order_id,
        amount: order.amount,
      });
      if (!alive.current) return;
      if (
        result?.status !== "done" ||
        result.order_id !== order.order_id ||
        result.amount !== order.amount
      )
        throw new Error("서버 승인 응답을 확인하지 못했어요.");
      sessionStorage.removeItem(storageKey);
      setCompletion(result);
      setOrder(null);
      popup.current?.close();
      await refresh();
    } catch (e) {
      if (alive.current && !e.stale && e.code !== "PAYMENT_PENDING")
        setError(`승인 상태 확인 오류: ${e.message}`);
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function cancel() {
    if (
      lock.current ||
      !order ||
      order.mode !== "subsidized" ||
      order.checkout_started
    )
      return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api(
        `/vouchers/subsidized-orders/${encodeURIComponent(order.order_id)}/cancel`,
        {},
      );
      if (!alive.current) return;
      if (result?.released !== true && result?.status !== "canceled")
        throw new Error(
          "서버에서 취소를 확인하지 못했어요. 승인 상태를 다시 확인해 주세요.",
        );
      sessionStorage.removeItem(storageKey);
      setCanceled(true);
      setOrder(null);
      popup.current?.close();
      await refresh();
    } catch (e) {
      if (alive.current && !e.stale) setError(e.message);
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  }
  if (canceled)
    return (
      <section className="purchase-card">
        <h2>결제 취소 확인</h2>
        <p>서버에서 예약 취소를 확인했어요.</p>
        <button
          onClick={() => {
            setCanceled(false);
            setConsent(false);
          }}
        >
          다른 식권 구매
        </button>
      </section>
    );
  if (completion)
    return (
      <section className="purchase-card">
        <h2>결제 완료</h2>
        {completion.pricing_discrepancy && (
          <p role="alert">
            견적과 서버 확정 가격이 달라요. 식권은 이미 발급되었으며 아래는 실제
            서버 확정 금액입니다. 중복 구매하지 말고 관리자에게 가격·포인트 차감
            확인을 요청해 주세요. 견적 포인트 {Number(completion.accepted_pricing.point_amount).toLocaleString("ko-KR")}P
            · 견적 카드 {Number(completion.accepted_pricing.payment_amount).toLocaleString("ko-KR")}원
          </p>
        )}
        <p>
          {completion.merchant_name} · {completion.product_name}
        </p>
        <p>
          서버 승인 금액 {Number(completion.amount).toLocaleString("ko-KR")}원
        </p>
        <p>
          결제수단{" "}
          {completion.payment?.method_label ||
            completion.payment?.method ||
            "정보 없음"}
        </p>
        <p>발급 식권 {completion.issued_count ?? "—"}장</p>
        {Number.isSafeInteger(completion.pricing?.point_amount) && (
          <p>실제 사용 포인트 {completion.pricing.point_amount.toLocaleString("ko-KR")}P</p>
        )}
        <p>승인 시각 {completion.payment?.approved_at || "정보 없음"}</p>
        {[
          ["sales_slip_url", "매출전표"],
          ["cash_receipt_url", "현금영수증"],
        ].map(([key, label]) =>
          validateReceiptUrl(completion.receipts?.[key]) ? (
            <a
              key={key}
              target="_blank"
              rel="noopener noreferrer"
              href={validateReceiptUrl(completion.receipts[key])}
            >
              {label}
            </a>
          ) : null,
        )}
        {!completion.pricing_discrepancy && <button
          onClick={() => {
            setCompletion(null);
            setConsent(false);
          }}
        >
          다른 식권 구매
        </button>}
      </section>
    );
  if (unknown)
    return (
      <section className="purchase-card">
        <h2>주문 상태 확인 필요</h2>
        <p role="alert">
          {error ||
            "이전 주문 생성 결과를 확인할 수 없어요. 중복 구매하지 말고 관리자에게 확인해 주세요."}
        </p>
      </section>
    );
  if (order)
    return (
      <section className="purchase-card">
        <h2>진행 중인 결제</h2>
        <p>주문 {order.order_id}</p>
        <p>서버 주문 금액 {Number(order.amount).toLocaleString("ko-KR")}원</p>
        <p role="status">결제 승인 확인 중</p>
        <p>결제창 종료·실패·성공 안내만으로는 승인 여부를 알 수 없어요.</p>
        <button disabled={busy} onClick={confirm}>
          승인 상태 확인
        </button>
        {order.mode === "subsidized" && !order.checkout_started && (
          <button disabled={busy} onClick={cancel}>
            예약 취소 요청
          </button>
        )}
        {error && <p role="alert">{error}</p>}
      </section>
    );
  if (!quote) return null;
  return (
    <section className="purchase-card">
      <h2>주문 확인</h2>
      {!legalReady && (
        <p role="alert">
          이용약관 또는 개인정보 처리방침을 불러오지 못했어요.
          구매를 진행할 수 없어요.
        </p>
      )}
      <label className="purchase-check">
        <input
          type="checkbox"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
        />
        구매 조건 확인
      </label>
      <p>
        선택한 상품 수량·가격과 기존 이용약관/개인정보 처리방침을 확인했습니다.
      </p>
      <button disabled={busy || !legalReady || !consent} onClick={purchase}>
        구매하기
      </button>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
