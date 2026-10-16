// Pure helpers for purchaser-web parity features (banner, review, account settings).

export function safeBannerLink(raw) {
  if (typeof raw !== 'string' || !raw.trim()) return null;
  try {
    const url = new URL(raw);
    return url.protocol === 'https:' && url.hostname ? url.href : null;
  } catch {
    return null;
  }
}

export function rewardLabel(reward) {
  if (!reward || reward.type === 'none') return '';
  return reward.available ? reward.label || '' : '지급 완료';
}

export function reviewPayload(transactionId, rating, content, imageUrls = []) {
  const id = Number(transactionId);
  if (!Number.isSafeInteger(id)) throw new Error('리뷰할 거래를 확인하지 못했어요.');
  if (!Number.isInteger(rating) || rating < 1 || rating > 5) throw new Error('별점을 선택해 주세요.');
  const text = typeof content === 'string' ? content.trim() : '';
  return { transaction_id: id, rating, content: text || null, image_urls: imageUrls.slice(0, 3) };
}

export function validateNewPassword(current, next, confirm) {
  if (!current) return '현재 비밀번호를 입력해 주세요.';
  if (!next || next.length < 8) return '새 비밀번호는 8자 이상이어야 해요.';
  if (next !== confirm) return '새 비밀번호 확인이 일치하지 않아요.';
  if (next === current) return '현재 비밀번호와 다른 비밀번호를 입력해 주세요.';
  return '';
}

// Header subtitle: never invent a merchant name.
export function headerSubtitle(companyName, merchantName) {
  return [companyName, merchantName].filter(v => typeof v === 'string' && v.trim()).join(' · ');
}
