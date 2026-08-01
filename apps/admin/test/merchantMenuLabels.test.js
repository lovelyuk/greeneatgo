import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('merchant navigation uses 업체 정보 and 매출 정산 without changing route ids', async () => {
  const source = await readFile(new URL('../src/main.jsx', import.meta.url), 'utf8');
  assert.match(source, /\['companies', '업체 정보', Building2\]/);
  assert.match(source, /\['settlements-by-company', '매출 정산', WalletCards\]/);
  assert.match(source, /aria-label="업체 정보 페이지"/);
  assert.equal(source.includes("['companies', '업체 관리', Building2]"), false);
  assert.equal(source.includes("['settlements-by-company', '업체별 정산', WalletCards]"), false);
});
