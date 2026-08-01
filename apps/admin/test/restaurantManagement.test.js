import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8');

test('restaurant management exposes coupon and payment QR tabs', () => {
  assert.match(source, /\['coupons', '쿠폰 관리'\]/);
  assert.match(source, /\['payment-qr', '결제 QR'\]/);
  assert.match(source, /merchantContentSection === 'coupons'.*CouponManagementPanel/);
  assert.match(source, /merchantContentSection === 'payment-qr'.*PaymentQrPanel/);
  assert.doesNotMatch(source, /merchantSection === 'main' && <section className="two-col merchant-main-panels"/);
  assert.match(source, /merchantSection === 'restaurant-management' && merchantContentSection === 'payment-qr'/);
  assert.match(source, /id === 'restaurant-management' && unreadPaymentCount > 0/);
});

test('product management has fixed discount, sold-out switch, and delete', () => {
  assert.match(source, /discount_amount_per_voucher/);
  assert.match(source, /role="switch" aria-checked=\{item\.status === 'active'\}/);
  assert.match(source, /'sold_out'/);
  assert.match(source, /apiFetch\(`\/admin\/voucher-products\/\$\{item\.id\}`.*method: 'DELETE'/s);
});

test('announcement edit/delete and review visibility controls are wired', () => {
  assert.match(source, /apiFetch\(`\/admin\/announcements\/\$\{item\.id\}`.*method: 'DELETE'/s);
  assert.match(source, /const \[editingAnnouncementId, setEditingAnnouncementId\] = useState\(''\)/);
  assert.match(source, /method: editingAnnouncementId \? 'PATCH' : 'POST'/);
  assert.match(source, /editingAnnouncementId \? '수정 저장' : '게시하기'/);
  assert.match(source, />수정<\/button>/);
  assert.doesNotMatch(source, /'노출로 복원' : '숨김'/);
  assert.match(source, /<option value="unanswered">미답변<\/option>/);
  assert.match(source, /<option value="hidden">숨김<\/option>/);
  assert.match(source, /사용자 앱에서 숨김/);
  assert.match(source, /글쓴이와 관리자만 볼 수 있음/);
});
