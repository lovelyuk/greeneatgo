import React, { useEffect, useRef, useState } from "react";
import { verifiedOrderClosure } from './paymentClosure.js';
import { safeCheckoutUrl } from "./purchaseSafety.js";
import { validateReceiptUrl } from "./receiptUtils.js";

// A failed storage write must not discard an order already returned by the server.
// This account-scoped fallback also survives checkout remounts in this document.
const pendingMemory = new Map();
const validOrderId = id => typeof id === "string" && /^[A-Za-z0-9_-]{6,64}$/.test(id);
export default function PurchaseCheckout({
  api,
  apiBaseUrl,
  quote,
  payload,
  mode,
  legalReady,
  refresh,
  userId,
  clearQuote,
}) {
  const [closed, setClosed] = useState(null);
  const [completion, setCompletion] = useState(null),
    [canceled, setCanceled] = useState(false);
  const [order, setOrder] = useState(null),
    [busy, setBusy] = useState(false),
    [consent, setConsent] = useState(false),
    [error, setError] = useState("");
  const [unknown, setUnknown] = useState(false);
  const storageKey = `greeneat-purchase-pending:${userId}`;
  const lock = useRef(null),
    generation = useRef(0),
    scopeKey = useRef(storageKey),
    popup = useRef(null);
  // Invalidate old closures at render as well as cleanup (including A -> B -> A).
  if (scopeKey.current !== storageKey) {
    scopeKey.current = storageKey;
    generation.current++;
  }
  useEffect(() => {
    generation.current++;
    lock.current = null;
    setCompletion(null); setClosed(null); setCanceled(false); setOrder(null);
    setUnknown(false); setBusy(false); setConsent(false); setError("");
    try {
      const saved = pendingMemory.get(storageKey) ?? JSON.parse(sessionStorage.getItem(storageKey) || "null");
      if (saved?.completion) {
        setCompletion(saved.completion);
        setError(saved.storage_error || "");
      } else if (saved?.unknown) setUnknown(true);
      else if (
        saved && validOrderId(saved.order_id) &&
        Number.isSafeInteger(saved.amount) && saved.amount > 0 &&
        ["voucher", "subsidized"].includes(saved.mode)
      ) setOrder(saved);
      else if (saved) setUnknown(true);
    } catch {
      setUnknown(true);
    }
    return () => {
      generation.current++;
      popup.current?.close();
    };
  }, [storageKey]);
  function begin() {
    const run = { generation: generation.current, key: storageKey, popup: null };
    lock.current = run;
    setBusy(true); setError("");
    return run;
  }
  function current(run) {
    return generation.current === run.generation && scopeKey.current === run.key;
  }
  function finish(run) {
    if (current(run) && lock.current === run) { lock.current = null; setBusy(false); }
  }
  function saveOrder(next, key = storageKey) {
    pendingMemory.set(key, next);
    setOrder(next);
    sessionStorage.setItem(key, JSON.stringify(next));
  }
  function clearSaved(run) {
    try {
      sessionStorage.removeItem(run.key);
      pendingMemory.delete(run.key);
      return true;
    } catch {
      setError("완료 결과는 서버에서 확인했지만 저장된 주문을 지우지 못했어요. 중복 구매하지 말고 관리자에게 확인해 주세요.");
      return false;
    }
  }
  async function complete(result, run) {
    const cleared = clearSaved(run);
    const done = { ...result, storage_blocked: !cleared };
    pendingMemory.set(run.key, { completion: done });
    setCompletion(done); setOrder(null); run.popup?.close();
    if (current(run)) await refresh();
  }
  function blankPopup(run) {
    run.popup = window.open("about:blank", "_blank");
    popup.current = run.popup;
    if (!run.popup) {
      setError("팝업이 차단됐어요. 팝업을 허용해 주세요.");
      return false;
    }
    run.popup.opener = null;
    return true;
  }
  async function purchase() {
    if (lock.current || order || unknown || !quote || !legalReady || !consent)
      return;
    const run = begin();
    if (quote.payment_amount > 0 && !blankPopup(run)) { finish(run); return; }
    try {
      sessionStorage.setItem(run.key, JSON.stringify({ unknown: true }));
      pendingMemory.set(run.key, { unknown: true });
      const result = await api(
        mode === "subsidized"
          ? "/vouchers/purchase-subsidized"
          : "/vouchers/purchase",
        payload,
      );
      if (!current(run)) return;
      if (
        !validOrderId(result?.order_id) ||
        !Number.isSafeInteger(result.amount) ||
        result.amount < 0
      )
        throw new Error("주문 응답을 확인하지 못했어요.");
      const next = {
        order_id: result.order_id,
        amount: result.amount,
        mode,
        checkout_started: false,
        product_id: result.product_id,
        accepted_pricing: { ...quote },
        server_pricing: { payment_amount: result.amount, gross_amount: result.gross_amount,
          coupon_discount_amount: result.coupon_discount_amount, point_amount: result.point_amount },
      };
      const pricingMatchesQuote =
        result.product_id === payload.product_id &&
        result.amount === quote.payment_amount &&
        ["gross_amount", "coupon_discount_amount", "point_amount"].every(
          (key) => Number.isSafeInteger(result[key]) && result[key] === quote[key],
        );
      next.resume_allowed = pricingMatchesQuote;
      if (result.amount === 0) {
        // Zero-card orders are already issued atomically by the purchase API.
        // /payments/confirm accepts positive amounts only; never invent a zero
        // confirmation or trust point_only alone without server fulfillment.
        const issued = result.fulfillment;
        if (
          result.product_id !== payload.product_id ||
          mode !== "subsidized" || result.point_only !== true ||
          result.card_amount !== 0 || result.checkout_url !== null ||
          issued?.status !== "done" || issued.order_id !== result.order_id ||
          issued.card_amount !== 0 ||
          !Number.isSafeInteger(issued.issued_count) || issued.issued_count <= 0 ||
          issued.issued_count !== result.total_count ||
          !Number.isSafeInteger(issued.point_amount) || issued.point_amount <= 0
        ) {
          pendingMemory.set(run.key, { ...next, unknown: true });
          sessionStorage.setItem(run.key, JSON.stringify({ ...next, unknown: true }));
          throw new Error("포인트 주문의 서버 발급 결과를 확인하지 못했어요.");
        }
        await complete({
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
        }, run);
        return;
      }
      saveOrder(next, run.key);
      if (result.amount > 0) {
        const url = safeCheckoutUrl(result.checkout_url, apiBaseUrl);
        if (!url) {
          run.popup?.close();
          setError(
            "결제 제공자/결제창 URL 정보가 올바르지 않아 결제를 차단했어요.",
          );
          return;
        }
        if (
          !pricingMatchesQuote ||
          !run.popup ||
          run.popup.closed
        ) {
          run.popup?.close();
          setError(
            "최종 주문 금액 또는 결제창 상태가 변경되어 자동 진입을 차단했어요.",
          );
          return;
        }
        saveOrder({ ...next, checkout_started: true }, run.key);
        run.popup.location.replace(url);
      } else run.popup?.close();
    } catch (e) {
      run.popup?.close();
      if (current(run) && !e.stale) {
        const known = pendingMemory.get(run.key);
        if (!known?.order_id || known.amount === 0) setUnknown(true);
        setError(
          known?.order_id && known.amount > 0
            ? `${e.message} 서버 주문 번호는 이 화면에 유지했지만 저장 또는 결제창 진입을 확인하지 못했어요. 이 화면을 닫지 말고 같은 주문의 상태를 확인해 주세요. 중복 구매하지 마세요.`
            : `${e.message} 주문 생성 결과를 확인할 수 없어요. 중복 구매하지 말고 관리자에게 거래 확인을 요청해 주세요.`,
        );
      }
    } finally {
      finish(run);
    }
  }
  function validCompletion(result, pending) {
    return result?.status === "done" && result.order_id === pending.order_id &&
      result.amount === pending.amount;
  }
  async function recover() {
    if (lock.current || !order) return;
    const pending = order;
    const run = begin();
    try {
      const result = await api(`/payments/recovery?order_id=${encodeURIComponent(pending.order_id)}&amount=${pending.amount}`);
      if (!current(run)) return;
      if (!result || result.resumable === true || result.order_id !== pending.order_id || result.amount !== pending.amount ||
          !["ready", "done", "failed", "canceled", "refund_processing", "refunded", "unknown"].includes(result.status))
        throw new Error("서버 주문 상태 응답을 확인하지 못했어요.");
      if (verifiedOrderClosure(result, pending, userId)) {
        // Re-read storage at the destructive boundary: a late response cannot
        // remove a newer intent even for the same account/document.
        const stored = JSON.parse(sessionStorage.getItem(run.key) || 'null');
        const memory = pendingMemory.get(run.key);
        const matches = value => value?.order_id === pending.order_id && value.amount === pending.amount;
        if ((stored && !matches(stored)) || (memory && !matches(memory)))
          throw new Error('저장된 주문이 변경되어 종료 처리를 차단했어요.');
        if (!clearSaved(run)) return;
        setConsent(false); clearQuote(); setOrder(null); setClosed(result);
        popup.current?.close();
      } else if (result.recovery_action === "complete" && result.status === "done" &&
          result.checkout_url === null && validCompletion(result.completion, pending)) {
        await complete(result.completion, run);
      } else if (result.recovery_action === "reconcile" && result.status !== "done" &&
          result.checkout_url === null && !result.completion) {
        run.popup?.close();
        setError(`서버 주문 상태: ${result.status}. 결제 여부를 확정할 수 없어요. 중복 구매하지 말고 관리자에게 거래 확인을 요청해 주세요.`);
      } else throw new Error("서버 결제 복구 응답을 확인하지 못했어요.");
    } catch (e) {
      run.popup?.close();
      if (current(run) && !e.stale)
        setError(`주문 상태 확인 오류: ${e.message} 저장된 주문을 유지했어요. 중복 구매하지 말고 관리자에게 확인해 주세요.`);
    } finally { finish(run); }
  }
  async function confirm() {
    if (lock.current || !order) return;
    const pending = order;
    const run = begin();
    run.popup = popup.current;
    try {
      const result = await api("/payments/confirm", { order_id: pending.order_id, amount: pending.amount });
      if (!current(run)) return;
      if (!validCompletion(result, pending)) throw new Error("서버 승인 응답을 확인하지 못했어요.");
      await complete(result, run);
    } catch (e) {
      if (current(run) && !e.stale)
        setError(e.code === "PAYMENT_PENDING"
          ? "아직 승인 대기 중이에요. 저장된 주문 상태를 확인해 주세요. 결제창 재진입은 중복 결제 위험 때문에 차단했어요. 중복 구매하지 말고 관리자에게 거래 확인을 요청해 주세요."
          : `승인 상태 확인 오류: ${e.message}`);
    } finally { finish(run); }
  }
  async function cancel() {
    if (
      lock.current ||
      !order ||
      order.mode !== "subsidized" ||
      order.checkout_started
    )
      return;
    const run = begin();
    try {
      const result = await api(
        `/vouchers/subsidized-orders/${encodeURIComponent(order.order_id)}/cancel`,
        {},
      );
      if (!current(run)) return;
      if (result?.released !== true && result?.status !== "canceled")
        throw new Error(
          "서버에서 취소를 확인하지 못했어요. 승인 상태를 다시 확인해 주세요.",
        );
      if (!clearSaved(run)) return;
      setCanceled(true);
      setOrder(null);
      popup.current?.close();
      await refresh();
    } catch (e) {
      if (current(run) && !e.stale) setError(e.message);
    } finally {
      finish(run);
    }
  }
  if (closed)
    return <section className="purchase-card">
      <h2>결제 종료 확인</h2>
      <p>주문 {closed.order_id} · 서버 확정 상태: {closed.status}</p>
      <p>해당 주문의 종료를 확인했어요. 기존 결제창은 다시 열 수 없어요.</p>
      <button onClick={() => { setClosed(null); setConsent(false); clearQuote(); }}>새 견적으로 구매 준비</button>
    </section>;
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
        {(error || completion.storage_blocked) && <p role="alert">{error || "저장된 주문을 지우지 못했어요. 완료 결과는 유지했어요. 중복 구매하지 말고 관리자에게 확인해 주세요."}</p>}
        {!completion.pricing_discrepancy && !completion.storage_blocked && <button
          onClick={() => {
            pendingMemory.delete(storageKey);
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
        <button disabled={busy} onClick={recover}>
          저장된 주문 상태 확인
        </button>
        <p>결제창 재진입은 중복 결제 위험 때문에 차단했어요. 저장된 주문 상태를 확인하고, 결제 여부가 불확실하면 중복 구매하지 말고 관리자에게 거래 확인을 요청해 주세요.</p>
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
