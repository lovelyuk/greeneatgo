import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';

const mainUrl = new URL('../src/main.jsx', import.meta.url);
const styleUrl = new URL('../src/style.css', import.meta.url);

test('prepurchase is the company-info tab after 업체 추가 and is not a sidebar screen', async () => {
  const source = await readFile(mainUrl, 'utf8');
  assert.match(source, /\['companies', '업체 추가'\],\s*\['prepurchase', '선구매'\]/);
  assert.doesNotMatch(source, /\['prepurchase', '선구매 관리'/);
  assert.doesNotMatch(source, /MerchantPrepurchaseMock/);
});

test('prepurchase UI uses exact API contracts, table columns, and stable logical-request UUID', async () => {
  const source = await readFile(mainUrl, 'utf8');
  assert.match(source, /apiFetch\('\/admin\/merchant\/prepurchases', token/);
  assert.match(source, /`\/admin\/merchant\/companies\/\$\{encodeURIComponent\(chargeItem\.company_id\)\}\/prepurchases`/);
  assert.match(source, /function openCharge[\s\S]*chargeRequestKeyRef\.current = crypto\.randomUUID\(\)/);
  assert.match(source, /function updateChargeField[\s\S]*chargeRequestKeyRef\.current = crypto\.randomUUID\(\)/);
  assert.match(source, /prepurchaseChargePayload\(chargeForm\.quantity, chargeForm\.unit_price, chargeRequestKeyRef\.current\)/);
  const submitSource = source.slice(source.indexOf('async function submitCharge'), source.indexOf('const displayNumber', source.indexOf('async function submitCharge')));
  assert.doesNotMatch(submitSource, /randomUUID/);
  assert.match(source, /<th>업체명<\/th><th>최근 구매일<\/th><th>구매 수량<\/th><th>단가<\/th><th>잔여량<\/th><th>충전 버튼<\/th>/);
});

test('prepurchase keeps list and charge errors separate and refreshes from Dashboard', async () => {
  const source = await readFile(mainUrl, 'utf8');
  assert.match(source, /const \[loadState, setLoadState\] = useState\('loading'\)/);
  assert.match(source, /const \[chargeError, setChargeError\] = useState\(''\)/);
  assert.match(source, /chargeError && <div className="alert error" role="alert">/);
  assert.match(source, /같은 요청을 안전하게 다시 시도할 수 있습니다/);
  assert.match(source, /\[token, refreshVersion\]/);
  assert.match(source, /setPrepurchaseRefreshVersion\(\(version\) => version \+ 1\)/);
  assert.match(source, /refreshVersion=\{prepurchaseRefreshVersion\}/);
});

test('prepurchase modal exposes bounded validation and basic keyboard/focus accessibility', async () => {
  const source = await readFile(mainUrl, 'utf8');
  assert.match(source, /aria-describedby="prepurchase-charge-description"/);
  assert.match(source, /quantityInputRef\.current\?\.focus\(\)/);
  assert.match(source, /event\.key === 'Escape'/);
  assert.match(source, /chargeTriggerRef\.current\?\.focus\(\)/);
  assert.match(source, /max=\{PREPURCHASE_MAX_QUANTITY\}/);
  assert.match(source, /max=\{PREPURCHASE_MAX_UNIT_PRICE\}/);
  assert.match(source, /aria-invalid=\{chargeTouched\.quantity && quantityInvalid\}/);
  assert.match(source, /aria-invalid=\{chargeTouched\.unit_price && unitPriceInvalid\}/);
});

test('contract payload persists prepurchase flag immediately after subsidy toggle', async () => {
  const source = await readFile(mainUrl, 'utf8');
  assert.match(source, /subsidy_enabled: contractForm\.subsidy_enabled,\s*prepurchase_enabled: contractForm\.prepurchase_enabled,/);
  assert.match(source, /보조금 계약<\/label>\s*<label className="subsidy-toggle">.*prepurchase_enabled.*선구매<\/label>/s);
});

test('prepurchase table owns mobile overflow and charge modal inputs stay at 16px', async () => {
  const style = await readFile(styleUrl, 'utf8');
  assert.match(style, /\.prepurchase-table-wrap[^}]*overflow-x:\s*auto/);
  assert.match(style, /\.prepurchase-table-wrap table\s*\{[^}]*min-width:/);
  assert.match(style, /\.prepurchase-charge-form input\s*\{[^}]*font-size:\s*16px/);
  assert.match(style, /@media \(max-width:\s*360px\)/);
});
