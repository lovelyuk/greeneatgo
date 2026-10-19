import React, { useEffect, useRef, useState } from "react";
import { createPortal } from 'react-dom';
import { verifiedOrderClosure, validLocalAbandonment } from './paymentClosure.js';
import { safeCheckoutUrl } from "./purchaseSafety.js";
import { checkoutPresentation, loadSdk, validateSdkData, openSdkFrame } from './kiwoomSdk.js';
import { validateReceiptUrl } from "./receiptUtils.js";
import { formatKst } from "./purchaseExtras.js";

// A failed storage write must not discard an order already returned by the server.
// This account-scoped fallback also survives checkout remounts in this document.
const pendingMemory = new Map();
const validOrderId = id => typeof id === "string" && /^[A-Za-z0-9_-]{6,64}$/.test(id);
const RECOVERY_TIMEOUT_MS = 30000; // Render cold start can exceed 10s
const USER_CLOSE_SETTLE_MS = 2000;

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
  onCheckoutEnded,
  paymentMethod = 'TOTAL',
  active = true,
  purchaseActive = active,
  recoveryView = false,
  recoveryTarget,
  onRecoveryNeeded,
}) {
  const [closed, setClosed] = useState(null);
  const [abandoned, setAbandoned] = useState(null);
  const [checkoutOpen, setCheckoutOpen] = useState(false);
  const [stopEligible, setStopEligible] = useState(false);
  const [stopWarning, setStopWarning] = useState(false), [stopConsent, setStopConsent] = useState(false);
  const [returnSignal, setReturnSignal] = useState(0);
  const queuedRead = useRef(false);
  const [completion, setCompletion] = useState(null),
    [canceled, setCanceled] = useState(false);
  const [order, setOrder] = useState(null),
    [busy, setBusy] = useState(false),
    [consent, setConsent] = useState(false),
    [error, setError] = useState("");
  const [unknown, setUnknown] = useState(false);
  const [entryError, setEntryError] = useState('');
  const storageKey = `greeneat-purchase-pending:${userId}`;
  const sdkClose = useRef(null), recoveryRef = useRef(null), reservedPopup = useRef(null);
  const bridgeChannel = useRef(null), returnedIntent = useRef(null);
  const liveQuote = useRef(quote), liveLegal = useRef(legalReady), liveConsent = useRef(consent);
  liveQuote.current = quote; liveLegal.current = legalReady; liveConsent.current = consent;
  const lock = useRef(null),
    generation = useRef(0),
    scopeKey = useRef(storageKey),
    popup = useRef(null);
  // Invalidate old closures at render as well as cleanup (including A -> B -> A).
  if (scopeKey.current !== storageKey) {
    scopeKey.current = storageKey;
    generation.current++;
  }
  const autoOrderId = useRef(null), autoAttempt = useRef(null), entry = useRef(0);
  const liveActive = useRef(active);
  const viewEpoch = useRef(0), lastRecoveryView = useRef(recoveryView), livePurchase = useRef(purchaseActive);
  livePurchase.current = purchaseActive;
  if (lastRecoveryView.current !== recoveryView) {
    lastRecoveryView.current = recoveryView;
    viewEpoch.current++;
  }
  useEffect(() => {
    // Fence read/stop responses on navigation, never an admitted purchase POST.
    if (lock.current?.viewEpoch !== undefined) {
      lock.current = null; setBusy(false);
    }
    setStopWarning(false); setStopConsent(false);
  }, [recoveryView]);
  if (liveActive.current !== active) {
    liveActive.current = active;
    entry.current++;
    autoOrderId.current = order?.order_id || null;
  }
  useEffect(() => {
    if (!active) {
      if (lock.current && !lock.current.admission && !order) setError('SDK 로딩 중 견적 또는 구매 조건이 변경됐어요. 주문을 생성하지 않았어요.');
      lock.current = null; queuedRead.current = false; setBusy(false);
    }
  }, [active]);
  useEffect(() => {
    generation.current++;
    lock.current = null;
    queuedRead.current = false;
    returnedIntent.current = null; autoOrderId.current = null; autoAttempt.current = null;
    setCompletion(null); setClosed(null); setAbandoned(null); setCanceled(false); setOrder(null);
    setCheckoutOpen(false); setStopEligible(false); setStopWarning(false); setStopConsent(false);
    setUnknown(false); setBusy(false); setConsent(false); setError(""); setEntryError('');
    try {
      const saved = pendingMemory.get(storageKey) ?? JSON.parse(sessionStorage.getItem(storageKey) || "null");
      if (saved?.local_abandonment_receipt) {
        if (!validLocalAbandonment(saved.local_abandonment_receipt, saved.pending, userId)) {
          setUnknown(true);
        } else {
          // A stored receipt is only a hint. Reauthenticate and reread the exact
          // order before offering a fresh purchase, including after page reload.
          setOrder(saved.pending); autoOrderId.current = saved.pending.order_id; returnedIntent.current = saved.pending.return_intent || null;
        }
      } else if (saved?.completion && pendingMemory.get(storageKey) === saved) {
        // Only this document's authenticated completion cache is trusted. A
        // serialized completion is not a server receipt and cannot prove issue.
        setCompletion(saved.completion);
        setError(saved.storage_error || "");
      } else if (saved?.unknown) setUnknown(true);
      else if (
        saved && validOrderId(saved.order_id) &&
        Number.isSafeInteger(saved.amount) && saved.amount > 0 &&
        ["voucher", "subsidized"].includes(saved.mode)
      ) {
        setOrder(saved); autoOrderId.current = saved.order_id;
        if (['sdk_frame_fail','mobile_fail','mobile_cancel','user_close'].includes(saved.return_intent)) {
          returnedIntent.current = saved.return_intent;
        }
      }
      else if (saved) setUnknown(true);
    } catch {
      setUnknown(true);
    }
    return () => {
      generation.current++;
      bridgeChannel.current?.close(); bridgeChannel.current = null;
      popup.current?.close();
      sdkClose.current?.(); sdkClose.current = null;
    };
  }, [storageKey]);
  function begin() {
    const run = { generation: generation.current, entry: entry.current, key: storageKey, popup: null, presentationEpoch: viewEpoch.current,
      presentation: checkoutPresentation(navigator, paymentMethod) };
    lock.current = run;
    setBusy(true); setError("");
    return run;
  }
  function current(run) {
    return liveActive.current && (run.entry === undefined || run.entry === entry.current) &&
      (run.viewEpoch === undefined || run.viewEpoch === viewEpoch.current) &&
      generation.current === run.generation && scopeKey.current === run.key;
  }
  function finish(run) {
    if (current(run) && lock.current === run) {
      lock.current = null; setBusy(false);
      if (queuedRead.current) { queuedRead.current = false; setReturnSignal(value => value + 1); }
    }
  }
  // Unsafe close authorizes only a read. A matched normal FAIL/CLOSE also
  // carries owner local-stop intent, never provider cancellation or approval.
  function checkoutReturned(run, intent = null, pending = null) {
    if (!current(run)) return;
    if (intent) {
      if (!pending || returnedIntent.current || !['sdk_frame_fail','mobile_fail','mobile_cancel','user_close'].includes(intent)) return;
      returnedIntent.current = intent;
      try { saveOrder({ ...pending, checkout_started: true, return_intent: intent }, run.key); }
      catch (e) { setError(`복귀 안내 저장 오류: ${e.message} 저장된 주문을 유지했어요. 상태 확인으로 다시 시도해 주세요.`); return; }
    }
    setCheckoutOpen(false); setStopEligible(false);
    queuedRead.current = true;
    if (!lock.current) { queuedRead.current = false; setReturnSignal(value => value + 1); }
  }
  useEffect(() => {
    if (!order) return;
    if (order.presentation === 'popup' && /^[0-9a-f]{32}$/.test(order.return_nonce || '') && !order.return_intent && !bridgeChannel.current) {
      connectReturnBridge({ generation: generation.current, key: storageKey }, order);
    }
    if (queuedRead.current && !lock.current) {
      queuedRead.current = false; setReturnSignal(value => value + 1);
    }
    const child = popup.current;
    if (!child) return;
    const run = { generation: generation.current, key: storageKey };
    // Only Window.closed is read. No cross-origin contents or focus heuristics.
    const timer = setInterval(() => {
      if (!child.closed) return;
      clearInterval(timer);
      if (popup.current === child) popup.current = null;
      // The buyer closed the payment window: treat as cancel intent. The server
      // status read below still decides; a paid order completes normally.
      checkoutReturned(run, 'user_close', order);
    }, 350);
    return () => clearInterval(timer);
  }, [order?.order_id, storageKey]);
  useEffect(() => {
    if (active && returnSignal) recoveryRef.current?.();
  }, [returnSignal]);
  // Entry identity is independent of API function identity and same-order updates.
  useEffect(() => {
    if (!active || !order || autoOrderId.current !== order.order_id) return;
    const key = `${storageKey}:${entry.current}:${order.order_id}`;
    if (autoAttempt.current === key) return;
    autoAttempt.current = key;
    // An embedded (PC) payment frame cannot survive a reload/remount, so a
    // restored started frame order was closed by the buyer.
    const frameGone = order.presentation === 'frame' && order.checkout_started && !sdkClose.current && !lock.current;
    recoveryRef.current?.(frameGone ? 'user_close' : null);
  }, [active, storageKey, order?.order_id]);
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
  async function complete(result, run, pending = result) {
    assertMatchingSaved(pending, run);
    setUnknown(false);
    const cleared = clearSaved(run);
    const done = { ...result, storage_blocked: !cleared };
    pendingMemory.set(run.key, { completion: done });
    setCompletion(done); setOrder(null); run.popup?.close();
    sdkClose.current?.(); sdkClose.current = null;
    if (current(run)) await refresh();
  }
  function blankPopup(run) {
    const reserved = reservedPopup.current; reservedPopup.current = null;
    run.popup = reserved && !reserved.closed ? reserved : window.open("about:blank", "_blank");
    popup.current = run.popup;
    if (!run.popup) {
      setError("팝업이 차단됐어요. 팝업을 허용해 주세요.");
      return false;
    }
    run.popup.opener = null;
    return true;
  }
  function connectReturnBridge(run, pending) {
    bridgeChannel.current?.close();
    const channel = new BroadcastChannel(`greeneat-checkout-return:${pending.return_nonce}`);
    bridgeChannel.current = channel;
    let consumed = false;
    channel.onmessage = event => {
      const d = event.data;
      if (consumed || !current(run) || event.origin !== window.location.origin ||
          !d || Object.keys(d).sort().join(',') !== 'kind,nonce,type' ||
          d.type !== 'greeneat_checkout_return' || d.nonce !== pending.return_nonce ||
          !['cancel','fail','success'].includes(d.kind)) return;
      consumed = true; channel.close();
      checkoutReturned(run, d.kind === 'cancel' ? 'mobile_cancel' : d.kind === 'fail' ? 'mobile_fail' : null, pending);
    };
  }
  async function purchase() {
    if (!purchaseActive) return;
    let leftover = !!(order || unknown);
    if (leftover && !completion?.storage_blocked && !lock.current && active && quote && legalReady && consent) {
      // A leftover order from a cancelled/abandoned checkout must not block a new
      // purchase. Re-check it: paid -> show completion; unpaid -> stop it quietly
      // and continue; still undecidable -> set it aside (an unpaid order cannot
      // charge, and a later real approval is still fulfilled by the server).
      // Mobile popup must be reserved inside the click, before any await.
      const reserved = quote.payment_amount > 0 && checkoutPresentation(navigator, paymentMethod) === 'popup'
        ? window.open('about:blank', '_blank') : null;
      if (reserved) reserved.opener = null;
      const outcome = order ? await recover('user_close', { silent: true }) : false;
      if (outcome === 'completed' || (!outcome && !parkLeftover())) {
        reserved?.close();
        if (outcome !== 'completed') onRecoveryNeeded?.();
        return;
      }
      reservedPopup.current = reserved;
      leftover = false;
    }
    if (leftover || completion?.storage_blocked) { onRecoveryNeeded?.(); return; }
    if (!active || lock.current || !quote || !legalReady || !consent)
      return;
    generation.current++; returnedIntent.current = null; setEntryError('');
    const run = begin();
    if (quote.payment_amount > 0 && run.presentation === 'popup' && !blankPopup(run)) { finish(run); return; }
    let sdk;
    if (quote.payment_amount > 0 && run.presentation === 'frame') {
      try { sdk = await loadSdk(); }
      catch (e) { if (current(run)) setError(e.message); finish(run); return; }
      if (!current(run)) return;
      if (liveQuote.current !== quote || !liveLegal.current || !liveConsent.current) {
        setError('SDK 로딩 중 견적 또는 구매 조건이 변경됐어요. 주문을 생성하지 않았어요.');
        finish(run); return;
      }
    }
    try {
      run.admission = crypto.randomUUID();
      const admission = { unknown: true, attempt_id: run.admission };
      sessionStorage.setItem(run.key, JSON.stringify(admission));
      pendingMemory.set(run.key, admission);
      setUnknown(true);
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
        admission_attempt: run.admission,
        presentation: run.presentation,
        return_nonce: [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2,'0')).join(''),
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
      assertMatchingSaved(next, run);
      saveOrder(next, run.key);
      setUnknown(false);
      // Never open a payment presentation after the buyer left purchase.
      if (!livePurchase.current || run.presentationEpoch !== viewEpoch.current) { run.popup?.close(); return; }
      if (result.amount > 0) {
        const url = safeCheckoutUrl(result.checkout_url, apiBaseUrl);
        if (!url) {
          setEntryError("결제 제공자/결제창 URL 정보가 올바르지 않아 결제를 차단했어요.");
          run.popup?.close();
          setError(
            "결제 제공자/결제창 URL 정보가 올바르지 않아 결제를 차단했어요.",
          );
          return;
        }
        if (
          !pricingMatchesQuote ||
          (run.presentation === 'popup' && (!run.popup || run.popup.closed))
        ) {
          run.popup?.close();
          setEntryError("최종 주문 금액 또는 결제창 상태가 변경되어 자동 진입을 차단했어요.");
          setError(
            "최종 주문 금액 또는 결제창 상태가 변경되어 자동 진입을 차단했어요.",
          );
          return;
        }
        saveOrder({ ...next, checkout_started: true }, run.key);
        setCheckoutOpen(true);
        if (run.presentation === 'frame') {
          const basePath = new URL(apiBaseUrl).pathname.replace(/\/$/, '');
          const checkoutPath = new URL(url).pathname.slice(basePath.length);
          const data = await api(`${checkoutPath}/sdk?return_nonce=${next.return_nonce}`, {});
          if (!current(run)) return;
          if (!livePurchase.current || run.presentationEpoch !== viewEpoch.current) {
            setCheckoutOpen(false); return;
          }
          const checked = validateSdkData(data, next);
          sdkClose.current = openSdkFrame(sdk, checked, {
            // The adapter emits one guarded semantic event and suppresses the
            // SDK's accompanying close; ordinary force-close stays uncertain.
            onEvent: event => checkoutReturned({ generation: run.generation, key: run.key }, event.TYPE === 'FAIL' ? 'sdk_frame_fail' : null, next),
            onClose: ({ user } = {}) => { sdkClose.current = null; checkoutReturned({ generation: run.generation, key: run.key }, user ? 'user_close' : null, next); },
          });
        } else {
          connectReturnBridge({ generation: run.generation, key: run.key }, next);
          const correlated = new URL(url); correlated.searchParams.set('return_nonce', next.return_nonce);
          run.popup.location.replace(correlated.href);
        }
      } else run.popup?.close();
    } catch (e) {
      run.popup?.close();
      if (current(run) && !e.stale) {
        setCheckoutOpen(false);
        setEntryError(e.message);
        const known = pendingMemory.get(run.key);
        setUnknown(!known?.order_id || known.amount === 0);
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
  function assertMatchingSaved(pending, run) {
    const stored = JSON.parse(sessionStorage.getItem(run.key) || 'null');
    const memory = pendingMemory.get(run.key);
    const matches = value => {
      const admission = run.admission || pending.admission_attempt;
      if (admission && value?.unknown === true && value.attempt_id === admission) return true;
      const intent = value?.local_abandonment_receipt ? value.pending : value;
      return intent?.order_id === pending.order_id && intent.amount === pending.amount;
    };
    if ((stored && !matches(stored)) || (memory && !matches(memory)))
      throw new Error('저장된 주문이 변경되어 종료 처리를 차단했어요.');
  }
  function retireLocal(result, pending, run, endedKind = null, silent = false) {
    if (!validLocalAbandonment(result, pending, userId)) throw new Error('구매 진행 중단 영수증을 확인하지 못했어요.');
    assertMatchingSaved(pending, run);
    const saved = { local_abandonment_receipt: result, pending };
    // Write the tombstone before changing memory/UI; storage errors fail closed.
    sessionStorage.setItem(run.key, JSON.stringify(saved));
    pendingMemory.set(run.key, saved);
    const rawIntent = endedKind || returnedIntent.current || pending.return_intent;
    const intent = rawIntent === 'user_close' ? 'mobile_cancel' : rawIntent;
    sessionStorage.removeItem(run.key); pendingMemory.delete(run.key);
    returnedIntent.current = null; bridgeChannel.current?.close(); bridgeChannel.current = null;
    setOrder(null); setAbandoned(null); setError(''); setCheckoutOpen(false);
    if (!silent) setConsent(false);
    setStopWarning(false); setStopConsent(false); setStopEligible(false);
    queuedRead.current = false; popup.current?.close(); popup.current = null;
    sdkClose.current?.(); sdkClose.current = null;
    if (!silent) { onCheckoutEnded?.(intent || 'locally_abandoned'); clearQuote(); }
  }
  // Set aside an undecidable leftover so it no longer blocks the buyer.
  function parkLeftover() {
    try { sessionStorage.removeItem(storageKey); } catch { return false; }
    pendingMemory.delete(storageKey);
    returnedIntent.current = null; bridgeChannel.current?.close(); bridgeChannel.current = null;
    setOrder(null); setUnknown(false); setError(''); setStopEligible(false); setStopWarning(false);
    return true;
  }

  async function recover(forcedIntent = null, { silent = false } = {}) {
    if (!active || lock.current || !order) return false;
    const pending = order;
    const run = begin();
    run.viewEpoch = viewEpoch.current;
    setStopEligible(false);
    const read = async () => {
      const value = await api(`/payments/recovery?order_id=${encodeURIComponent(pending.order_id)}&amount=${pending.amount}`, undefined, { readTimeoutMs: RECOVERY_TIMEOUT_MS });
      if (!value || value.resumable === true || value.order_id !== pending.order_id || value.amount !== pending.amount ||
          !["ready", "done", "failed", "canceled", "refund_processing", "refunded", "unknown"].includes(value.status))
        throw new Error("서버 주문 상태 응답을 확인하지 못했어요.");
      return value;
    };
    try {
      let result = await read();
      if (!current(run)) return false;
      const intentNow = forcedIntent || returnedIntent.current || pending.return_intent;
      if (intentNow === 'user_close' && result.status === 'ready' && !result.local_abandonment) {
        // Give a just-finished approval notification time to land before stopping.
        await new Promise(resolve => setTimeout(resolve, USER_CLOSE_SETTLE_MS));
        if (!current(run)) return false;
        result = await read();
        if (!current(run)) return false;
      }
      if (validLocalAbandonment(result, pending, userId)) {
        retireLocal(result, pending, run, null, silent); return 'stopped';
      } else if (verifiedOrderClosure(result, pending, userId)) {
        // Re-read storage at the destructive boundary: a late response cannot
        // remove a newer intent even for the same account/document.
        assertMatchingSaved(pending, run);
        if (!clearSaved(run)) return false;
        setOrder(null); setClosed(null); setError('');
        if (!silent) { setConsent(false); clearQuote(); onCheckoutEnded?.('verified_closed'); }
        popup.current?.close();
        sdkClose.current?.(); sdkClose.current = null;
        return 'stopped';
      } else if (result.recovery_action === "complete" && result.status === "done" &&
          result.checkout_url === null && validCompletion(result.completion, pending)) {
        await complete(result.completion, run, pending); return 'completed';
      } else if (result.recovery_action === "reconcile" && result.status !== "done" &&
          result.checkout_url === null && !result.completion) {
        const intent = forcedIntent || returnedIntent.current || pending.return_intent;
        if (result.status === 'ready' && !result.local_abandonment && ['sdk_frame_fail','mobile_fail','mobile_cancel','user_close'].includes(intent)) {
          assertMatchingSaved(pending, run);
          try {
            const stopped = await api(`/payments/orders/${encodeURIComponent(pending.order_id)}/abandon`, {
              amount: pending.amount,
              ...(['mobile_cancel', 'user_close'].includes(intent) ? { explicit_checkout_cancel_intent: true } : { checkout_return_ended: intent }),
            }, { requestTimeoutMs: RECOVERY_TIMEOUT_MS });
            if (!current(run)) return false;
            retireLocal(stopped, pending, run, intent === 'user_close' ? 'mobile_cancel' : null, silent); return 'stopped';
          } catch (stopError) {
            // Never repeat an automatic stop write in this session; the buyer can
            // re-check or stop manually from history.
            if (intent === 'user_close') {
              returnedIntent.current = null;
              try { const { return_intent, ...rest } = pending; saveOrder(rest, run.key); } catch { /* keep pending */ }
            }
            throw Object.assign(new Error(`구매 중단 결과 확인 필요: ${stopError.message} 저장된 주문은 유지했어요. 상태를 다시 조회해 주세요.`), { stale: stopError.stale, stopFailure: true });
          }
        }
        setStopEligible(result.status === 'ready' && !result.local_abandonment);
        setError(result.local_abandonment
          ? '중단한 주문에 후속 승인 또는 불일치가 있어요. 실제 청구를 확인해야 하며 자동 식권 발급·환불은 하지 않아요. 내역에서 주문 상태를 확인해 주세요.'
          : result.status === 'ready'
            ? '서버 주문 상태: ready. PG 승인 여부는 아직 확정하지 못했어요. 상태를 다시 확인하거나, 안내에 동의하고 이 주문의 구매 진행을 중단할 수 있어요. 실제 청구가 있거나 도움이 필요하면 관리자에게 거래 확인을 요청해 주세요.'
            : `서버 주문 상태: ${result.status}. 결제 여부를 확정하지 못했어요. 조회만 다시 시도할 수 있어요. 관리자에게 거래 확인을 요청해 주세요.`);
      } else throw new Error("서버 결제 복구 응답을 확인하지 못했어요.");
      return false;
    } catch (e) {
      run.popup?.close();
      if (current(run) && !e.stale)
        setError(e.stopFailure ? e.message : `주문 상태 확인 오류: ${e.message} 저장된 주문을 유지했어요. 아래 상태 확인으로 다시 조회해 주세요. 구매나 취소 요청은 자동 재시도하지 않아요.`);
      return false;
    } finally { finish(run); }
  }
  recoveryRef.current = recover;
  useEffect(() => {
    // One authenticated read on history entry; never reopen the old PG flow.
    if (recoveryView && order) recoveryRef.current?.();
  }, [recoveryView]);
  async function abandon() {
    if (!active || lock.current || !order || !stopEligible || !stopConsent) return;
    const pending = order, run = begin();
    run.viewEpoch = viewEpoch.current;
    setStopEligible(false);
    try {
      const result = await api(`/payments/orders/${encodeURIComponent(pending.order_id)}/abandon`, {
        amount: pending.amount, acknowledge_provider_uncertainty: true,
      });
      if (!current(run)) return;
      retireLocal(result, pending, run);
    } catch (e) {
      if (current(run) && !e.stale) setError(`구매 중단 결과 확인 필요: ${e.message} 저장된 주문은 유지했어요. 상태를 다시 조회해 주세요. 중단 요청을 자동 재시도하지 않아요.`);
    } finally { finish(run); }
  }
  async function cancel() {
    if (
      !active || !recoveryView ||
      lock.current ||
      !order ||
      order.mode !== "subsidized" ||
      order.checkout_started
    )
      return;
    const pending = order, run = begin();
    run.viewEpoch = viewEpoch.current;
    try {
      const result = await api(
        `/vouchers/subsidized-orders/${encodeURIComponent(pending.order_id)}/cancel`,
        {},
      );
      if (!current(run)) return;
      if (result?.released !== true && result?.status !== "canceled")
        throw new Error(
          "서버에서 취소를 확인하지 못했어요. 승인 상태를 다시 확인해 주세요.",
        );
      assertMatchingSaved(pending, run);
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
  if (abandoned)
    return <section className="purchase-card">
      <h2>구매 진행 중단 접수</h2>
      <p>주문 {abandoned.order_id} · {abandoned.amount.toLocaleString('ko-KR')}원</p>
      <p>{abandoned.local_abandonment.source === 'manual_database_operator' ? '운영자 판정으로' : '요청에 따라'} 이 주문의 서비스 내 구매 진행을 중단했어요. 기존 주문과 영수증은 내역에 보존되며 기존 결제창은 다시 열 수 없어요.</p>
      <p>PG 취소·환불 확정이 아니에요. 기존 결제창에서 나중에 승인·청구될 가능성이 남아 있어요. 그런 경우 재확인 대상으로 기록하며 식권 발급이나 자동 환불은 하지 않아요. 내역의 ‘중단한 구매 주문’에서 최신 상태를 확인해 주세요.</p>
      <button onClick={() => {
        try {
          const run = { key: storageKey };
          assertMatchingSaved(abandoned, run);
          if (!clearSaved(run)) return;
          setAbandoned(null); setConsent(false); clearQuote(); setError('');
        } catch { setError('저장된 주문을 확인하지 못해 새 구매 준비를 차단했어요. 새로고침 후 다시 조회해 주세요.'); }
      }}>새 견적으로 구매 준비</button>
      {error && <p role="alert">{error}</p>}
    </section>;
  if (closed)
    return <section className="purchase-card">
      <h2>결제 종료 확인</h2>
      <p>주문 {closed.order_id} · 서버 확정 상태: {closed.status}</p>
      <p>해당 주문의 종료를 확인했어요. 기존 결제창은 다시 열 수 없어요.</p>
      <button onClick={() => { setClosed(null); setConsent(false); clearQuote(); }}>새 견적으로 구매 준비</button>
    </section>;
  if (canceled)
    return presentCompletion(
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
  function presentCompletion(content) {
    return recoveryView && recoveryTarget ? createPortal(content, recoveryTarget) : content;
  }
  // Payment completion is a modal over the unchanged purchase screen (user rule);
  // only server-confirmed completion data is shown.
  const closeCompletion = () => {
    pendingMemory.delete(storageKey);
    setCompletion(null);
    setConsent(false);
  };
  const completionClosable = completion && !completion.pricing_discrepancy && !completion.storage_blocked;
  const completionDialog = completion && (
    <div className="done-overlay" onKeyDown={e => { if (e.key === 'Escape' && completionClosable) closeCompletion(); }}>
      <section className="purchase-card done-dialog" role="dialog" aria-modal="true" aria-labelledby="done-title">
        <span className="done-check" aria-hidden="true">✓</span>
        <h2 id="done-title">결제 완료</h2>
        <p className="done-sub">{completion.merchant_name} · {completion.product_name}</p>
        {completion.pricing_discrepancy && (
          <p role="alert">
            견적과 서버 확정 가격이 달라요. 식권은 이미 발급되었으며 아래는 실제
            서버 확정 금액입니다. 중복 구매하지 말고 관리자에게 가격·포인트 차감
            확인을 요청해 주세요. 견적 포인트 {Number(completion.accepted_pricing.point_amount).toLocaleString("ko-KR")}P
            · 견적 카드 {Number(completion.accepted_pricing.payment_amount).toLocaleString("ko-KR")}원
          </p>
        )}
        <div className="done-receipt">
          <p className="done-receipt-amount"><span>결제 금액</span><b>{Number(completion.amount).toLocaleString("ko-KR")}원</b></p>
          <div className="done-receipt-cut" aria-hidden="true" />
          <div className="done-rows">
            <p className="done-row"><span>결제수단</span> <b>{completion.payment?.method_label || completion.payment?.method || "정보 없음"}</b></p>
            <p className="done-row"><span>발급 식권</span> <b>{completion.issued_count ?? "—"}장</b></p>
            {Number.isSafeInteger(completion.pricing?.point_amount) && (
              <p className="done-row"><span>실제 사용 포인트</span> <b>{completion.pricing.point_amount.toLocaleString("ko-KR")}P</b></p>
            )}
            <p className="done-row"><span>승인 시각</span> <b>{formatKst(completion.payment?.approved_at)}</b></p>
          </div>
        </div>
        <div className="done-links">
          {[
            ["sales_slip_url", "매출전표 보기"],
            ["cash_receipt_url", "현금영수증 보기"],
          ].map(([key, label]) =>
            validateReceiptUrl(completion.receipts?.[key]) ? (
              <a key={key} target="_blank" rel="noopener noreferrer" href={validateReceiptUrl(completion.receipts[key])}>{label}</a>
            ) : null,
          )}
        </div>
        {(error || completion.storage_blocked) && <p role="alert">{error || "저장된 주문을 지우지 못했어요. 완료 결과는 유지했어요. 중복 구매하지 말고 관리자에게 확인해 주세요."}</p>}
        {completionClosable && <button className="done-ok" autoFocus onClick={closeCompletion}>확인</button>}
      </section>
    </div>
  );
  // History (recovery) view and a hidden purchase tab show only the dialog;
  // the purchase tab keeps its form underneath (rendered at the end).
  if (completion && (recoveryView || !purchaseActive || !quote))
    return presentCompletion(completionDialog);
  if (unknown && recoveryView)
    return recoveryTarget && createPortal((
      <section className="purchase-card">
        <h2>주문 상태 확인 필요</h2>
        <p role="alert">
          {error ||
            "이전 주문 생성 결과를 확인할 수 없어요. 중복 구매하지 말고 관리자에게 확인해 주세요."}
        </p>
      </section>
    ), recoveryTarget);
  if (order && recoveryView)
    return recoveryTarget && createPortal((
      <section className="purchase-card recovery-card">
        <h2>{busy ? '결제 결과 확인 중' : checkoutOpen ? '진행 중인 결제' : '이전 결제 결과를 확인하지 못했어요.'}</h2>
        {busy ? <p role="status">결제 결과 확인 중…</p> : <p role="alert">{error.startsWith('주문 상태 확인 오류:') ? '주문 상태 확인 오류 · 다시 확인해 주세요.' : error.startsWith('구매 중단 결과 확인 필요:') ? '구매 중단 결과를 확인하지 못했어요. 다시 확인해 주세요.' : checkoutOpen ? '결제창에서 진행해 주세요.' : '결제 여부가 아직 확정되지 않았어요. 청구 내역도 확인해 주세요.'}</p>}
        <button disabled={busy} onClick={recover}>다시 확인</button>
        {stopEligible && !stopWarning && <button disabled={busy} onClick={() => { setStopWarning(true); setStopConsent(false); }}>구매 진행 중단</button>}
        {stopWarning && <section aria-label="구매 진행 중단 안내">
          <p>서비스 내 구매 진행만 중단해요. PG 취소·환불 확정이 아니며, 기존 결제창에서 나중에 승인·청구될 수 있어요. 사용하지 않은 예약 포인트·쿠폰만 해제하고 기존 주문은 내역에 남겨요. 기존 결제창은 다시 이용하지 마세요.</p>
          <label className="purchase-check"><input type="checkbox" checked={stopConsent} onChange={e => setStopConsent(e.target.checked)} />PG 취소·환불 확정이 아님을 이해했습니다</label>
          <button disabled={busy || !stopEligible || !stopConsent} onClick={abandon}>확인하고 구매 진행 중단</button>
          <button disabled={busy} onClick={() => { setStopWarning(false); setStopConsent(false); }}>계속 상태 확인하기</button>
        </section>}
        <details>
          <summary>상세 보기</summary>
          <p>주문 {order.order_id}</p>
          <p>서버 주문 금액 {Number(order.amount).toLocaleString("ko-KR")}원</p>
          <p>결제창은 다시 열지 않아요. 조회는 새 구매나 PG 취소·환불 요청이 아니에요.</p>
          {order.mode === "subsidized" && !order.checkout_started && <button disabled={busy} onClick={cancel}>예약 취소 요청</button>}
          {entryError && <p>{entryError}</p>}
          {error && <p>{error}</p>}
        </details>
      </section>
    ), recoveryTarget);
  if (!purchaseActive || !quote) return null;
  return (
    <>
    {completionDialog}
    <section className="purchase-card">
      <h2>주문 확인</h2>
      {paymentMethod === 'BANK' && <p>계좌이체 전용 상품은 결제수단 제한을 유지하기 위해 기존 새 결제창(팝업)으로 진행해요.</p>}
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
      <p>결제창에서 취소·실패로 정상 복귀하면 서버 확인 후 서비스 내 구매 진행을 중단하고 상품 목록으로 돌아가요. PG 취소·환불 확정은 아니며, 후속 청구는 내역에 재확인 대상으로 보존해요. 새 구매는 새 견적과 동의로 직접 시작해요.</p>
      <button disabled={(busy && !order && !unknown) || !legalReady || !consent} onClick={purchase}>
        구매하기
      </button>
      {error && !order && !unknown && !completion && <p role="alert">{error}</p>}
    </section>
    </>
  );
}
