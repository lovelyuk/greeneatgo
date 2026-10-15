// Official merchant-root FRAME integration. No provider callback is payment authority.
export const SDK_URL = 'https://ssl-v2.kiwoompay.co.kr/sdk/v1/latest/kiwoompayEnc.js';
const mobile = /iPhone|iPod|iPad|Android|Windows CE|BlackBerry|Symbian|Windows Phone|webOS|Opera Mini|Opera Mobi|POLARIS|IEMobile|lgtelecom|nokia|SonyEricsson/i;
export function checkoutPresentation(nav, method) {
  return method === 'BANK' || mobile.test(nav.userAgent) || /LG|SAMSUNG|Samsung/.test(nav.userAgent) ||
    (/Macintosh|MacIntel/.test(`${nav.userAgent} ${nav.platform || ''}`) && nav.maxTouchPoints > 1) ? 'popup' : 'frame';
}
const loads = new WeakMap();
function usable(sdk) {
  return sdk && ['f_setInit','f_payTotalLink','f_closeFrame','f_setFrameSize'].every(key => typeof sdk[key] === 'function');
}
export function loadSdk(win = window, doc = document) {
  if (loads.has(win)) return loads.get(win);
  const promise = new Promise((resolve, reject) => {
    const script = doc.createElement('script');
    script.src = SDK_URL; script.async = true;
    const timer = setTimeout(() => reject(new Error('공식 결제 SDK 로딩 시간이 초과됐어요. 주문을 생성하지 않았어요.')), 15000);
    script.onload = () => { clearTimeout(timer); usable(win.KiwoomPaySDK) ? resolve(win.KiwoomPaySDK) : reject(new Error('공식 결제 SDK를 확인하지 못했어요. 주문을 생성하지 않았어요.')); };
    script.onerror = () => { clearTimeout(timer); reject(new Error('공식 결제 SDK를 불러오지 못했어요. 주문을 생성하지 않았어요.')); };
    doc.head.appendChild(script);
  });
  loads.set(win, promise); return promise;
}
export function validateSdkData(data, pending) {
  const f = data?.fields;
  if (!['DEV','REAL'].includes(data?.sdk_mode) || !f || typeof f !== 'object' || Array.isArray(f) ||
      Object.keys(f).some(key => key.startsWith('CALLBACK') || !['string','number'].includes(typeof f[key])) ||
      f.TYPE !== 'P' || f.PAYMETHOD !== 'TOTAL' || typeof f.CPID !== 'string' || !/^[A-Za-z0-9]{8}$/.test(f.CPID) ||
      f.ORDERNO !== pending.order_id || typeof f.AMOUNT !== 'string' || !/^[1-9]\d{0,9}$/.test(f.AMOUNT) || Number(f.AMOUNT) !== pending.amount ||
      typeof f.KIWOOM_ENC !== 'string' || !f.KIWOOM_ENC || f.KIWOOM_ENC.length > 1000 || /[\s|\x00-\x1f\x7f]/.test(f.KIWOOM_ENC) ||
      typeof f.PRODUCTNAME !== 'string' || !f.PRODUCTNAME || typeof f.USERID !== 'string' || !f.USERID)
    throw new Error('서버 SDK 결제 정보를 확인하지 못했어요. 같은 주문의 결제창을 다시 열지 마세요.');
  return { sdk_mode: data.sdk_mode, fields: { ...f } };
}
export function validSdkMessage(event, mode, source, orderId = null) {
  const origin = mode === 'REAL' ? 'https://ssl-v2.kiwoompay.co.kr' : mode === 'DEV' ? 'https://ssltest-v2.kiwoompay.co.kr' : null;
  const d = event.data;
  return !!origin && !!source && event.origin === origin && event.source === source &&
    !!d && typeof d === 'object' && !Array.isArray(d) && ['SUCCESS','FAIL'].includes(d.TYPE) &&
    (d.ORDERNO === undefined || d.ORDERNO === orderId) &&
    (d.RESULTCODE === undefined || (typeof d.RESULTCODE === 'string' && /^\d{4}$/.test(d.RESULTCODE))) &&
    !(d.TYPE === 'FAIL' && d.RESULTCODE === '0000') && !(d.TYPE === 'SUCCESS' && d.RESULTCODE !== undefined && d.RESULTCODE !== '0000');
}
export function openSdkFrame(sdk, data, { onEvent, onClose }, win = window, doc = document) {
  const previousFocus = doc.activeElement;
  let guarded, originalHandler, frame, dimmer, closed = false, acceptedEvent = false;
  const background = [];
  const originalClose = sdk.f_closeFrame;
  const cleanup = (notify = true) => {
    if (closed) return;
    closed = true;
    win.removeEventListener('message', guarded);
    win.removeEventListener('message', originalHandler);
    doc.removeEventListener('keydown', keyboard, true);
    doc.removeEventListener('focusin', focus, true);
    sdk.f_closeFrame = originalClose;
    for (const [element, wasInert] of background) element.inert = wasInert;
    if (previousFocus?.isConnected && previousFocus !== doc.body) previousFocus.focus?.();
    else doc.querySelector('.purchase-card button')?.focus();
    if (notify && !acceptedEvent) onClose();
  };
  const close = () => { acceptedEvent = false; originalClose.call(sdk); cleanup(); };
  const focus = e => { if (!closed && !dimmer?.contains(e.target)) sdk.o_iframeCancel?.focus(); };
  const keyboard = e => {
    if (e.key === 'Escape') { e.preventDefault(); close(); }
    // Tab cannot inspect the cross-origin provider document. Keep merchant focus
    // cycling through the official close control and iframe entry point.
    if (e.key === 'Tab' && (doc.activeElement === frame || doc.activeElement === sdk.o_iframeCancel)) {
      e.preventDefault(); (doc.activeElement === frame ? sdk.o_iframeCancel : frame)?.focus();
    }
  };
  // The official callback is delayed until after f_closeFrame. Emit only at
  // the strict guard, never from an unfenced delayed callback.
  const callback = () => {};
  sdk.f_setInit(data.sdk_mode, 'FRAME');
  sdk.f_setFrameSize(900, 550);
  try {
    sdk.f_payTotalLink({ ...data.fields, CALLBACKSUCC: callback, CALLBACKFAIL: callback });
    frame = sdk.o_iframe; dimmer = sdk.o_div; originalHandler = sdk.f_messageHandler;
    if (!frame?.isConnected || !dimmer?.isConnected || typeof originalHandler !== 'function') throw new Error('공식 SDK FRAME 생성에 실패했어요.');
    // Creation is synchronous: no posted-message task can run between creation
    // and this replacement. Only the SDK listener is removed, never app listeners.
    win.removeEventListener('message', originalHandler);
    guarded = event => {
      if (closed || !validSdkMessage(event, data.sdk_mode, frame.contentWindow, data.fields.ORDERNO)) return;
      acceptedEvent = true;
      onEvent(event.data);
      originalHandler.call(win, event);
    };
    sdk.f_messageHandler = guarded;
    win.addEventListener('message', guarded);
    sdk.f_closeFrame = () => { originalClose.call(sdk); cleanup(); };
    dimmer.setAttribute('role', 'dialog'); dimmer.setAttribute('aria-modal', 'true'); dimmer.setAttribute('aria-label', '키움페이 결제창');
    for (const element of doc.body.children) {
      if (element !== dimmer && !['SCRIPT', 'STYLE'].includes(element.tagName)) {
        background.push([element, element.inert]); element.inert = true;
      }
    }
    frame.tabIndex = 0;
    // Retain the official frame/form; responsive merchant presentation only.
    Object.assign(frame.style, { width:'min(900px, calc(100vw - 24px))', height:'min(550px, calc(100dvh - 100px))', margin:'0', transform:'translate(-50%, -50%)' });
    const button = sdk.o_iframeCancel;
    button.removeAttribute('onclick'); button.onclick = close;
    button.setAttribute('aria-label', '결제창 닫기'); button.textContent = '닫기';
    Object.assign(button.style, { width:'64px', height:'36px', margin:'0', top:'12px', left:'auto', right:'12px', background:'#fff', borderRadius:'6px', color:'#111' });
    doc.addEventListener('keydown', keyboard, true); doc.addEventListener('focusin', focus, true); button.focus();
    return close;
  } catch (e) {
    originalClose.call(sdk); cleanup(false); throw e;
  }
}
