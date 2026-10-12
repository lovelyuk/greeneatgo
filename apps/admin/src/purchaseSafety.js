// Existing legal sources only: never supply substitute business/provider facts.
export function safeCheckoutUrl(raw, apiBase) {
  try {
    if (typeof raw !== "string" || /[\\\s%]/.test(raw)) return null;
    const base = new URL(apiBase),
      url = new URL(raw);
    const local = ["127.0.0.1", "localhost", "[::1]"].includes(base.hostname);
    if (base.protocol !== "https:" && !(local && base.protocol === "http:"))
      return null;
    if (
      base.username ||
      base.password ||
      base.search ||
      base.hash ||
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      url.origin !== base.origin
    )
      return null;
    const prefix = `${base.pathname.replace(/\/$/, "")}/payments/checkout/`;
    if (
      !url.pathname.startsWith(prefix) ||
      !/^[A-Za-z0-9_-]{43}$/.test(url.pathname.slice(prefix.length))
    )
      return null;
    return url.href;
  } catch {
    return null;
  }
}
export function purchaseDisclosuresReady(text, merchantName) {
  return (
    typeof text === "string" &&
    typeof merchantName === "string" &&
    merchantName.trim().length > 0 &&
    text.includes(merchantName) &&
    /사업자등록번호\s*[0-9]{3}-[0-9]{2}-[0-9]{5}/.test(text) &&
    ["대표자", "주소", "연락처", "키움페이"].every((field) =>
      text.includes(field),
    ) &&
    !/【|】|YYYY|TODO|PLACEHOLDER/i.test(text)
  );
}
export function legalDocumentsReady(documents) {
  return (
    Array.isArray(documents) &&
    documents.length === 2 &&
    documents.every(
      (text, index) =>
        typeof text === "string" &&
        text.includes(index ? "개인정보" : "이용약관") &&
        text.length >= 20 &&
        !/【|】|YYYY|TODO|PLACEHOLDER/i.test(text),
    )
  );
}
