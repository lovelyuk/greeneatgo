import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const main = await readFile(new URL('../src/main.jsx', import.meta.url), 'utf8');
const css = await readFile(new URL('../src/style.css', import.meta.url), 'utf8');
const dashboardMain = main.slice(main.indexOf('const dashColors'), main.indexOf('function CompanyDashboard'));

test('merchant and company dashboards use the shared dashboard and strict API contract', () => {
  for (const name of ['SummaryCard', 'DonutCard', 'RankTable', 'TrendChart', 'PeriodPicker', 'DashboardView', 'mapDashboardSummary']) {
    assert.match(main, new RegExp(`function ${name}\\b`));
  }
  assert.match(main, /\/admin\/dashboard\/summary\?/);
  assert.match(main, /merchant_id/);
  assert.match(main, /company_id/);
  assert.match(main, /history\.replaceState/);
  assert.match(main, /\.then\(mapDashboardSummary\)/);
  assert.match(main, /typeof value !== 'number' \|\| !Number\.isFinite\(value\)/);
  assert.match(main, /Number\.isInteger\(value\)/);
  assert.match(main, /!Array\.isArray\(data\.by_meal_type\)/);
  assert.match(main, /validDashboardDate\(row\.date\)/);
  assert.match(main, /value === null \? null/);
  assert.match(main, /row\.label/);
  assert.match(main, /row\.rank/);
  assert.match(main, /row\.name/);
  assert.doesNotMatch(main, /row\.meal_type/);
  assert.doesNotMatch(main, /row\.company_name/);
  assert.doesNotMatch(dashboardMain, /total_amount \?\? 0/);
  assert.match(dashboardMain, /assertDashboardKeys\(data,/);
});

test('summary is exactly amount, meal ratio, and count with required presentation', () => {
  assert.match(main, /title="대시보드"/);
  assert.match(main, /기간 설정에 따른 매출 및 수량 현황을 한눈에 확인할 수 있습니다\./);
  assert.match(main, /기간 설정에 따른 식당 이용 현황을 한눈에 확인할 수 있습니다\./);
  assert.match(main, /<section className="dash-summary-grid"><SummaryCard[\s\S]*?<DonutCard[\s\S]*?<SummaryCard/);
  assert.match(main, /식사 구분/);
  assert.match(main, /row\.ratio\.toLocaleString/);
  assert.match(css, /\.dash-icon-green/);
  assert.match(css, /\.dash-icon-blue/);
  assert.match(css, /\.dash-icon-orange/);
  assert.match(main, /\[0, 1, 2\]\.map/);
  assert.match(main, /전 기간 대비/);
  assert.match(main, /'↑'/);
  assert.match(main, /'↓'/);
  assert.doesNotMatch(main, /▲|▼/);
});

test('ranking tables preserve actual rows and use role-specific contracts', () => {
  assert.match(main, /\(단위: \{money \? '원' : '건'\}\)/);
  assert.match(main, /<th>순위<\/th><th>\{secondHeader\}<\/th><th className="money">값<\/th>/);
  assert.match(main, /merchant \? '거래처명' : '구분'/);
  assert.match(main, /rank: index \+ 1, name: row\.label/);
  assert.match(main, /name: '합계', amount: summary\.total_amount, isTotal: true/);
  assert.match(main, /name: '합계', count: summary\.total_count, isTotal: true/);
  assert.doesNotMatch(dashboardMain, /total_amount[^\n]*<= 0 \? \[\]/);
  assert.doesNotMatch(dashboardMain, /total_count[^\n]*<= 0 \? \[\]/);
});

test('all-zero dashboard data renders empty tables and charts instead of believable zero rows', () => {
  assert.match(dashboardMain, /const hasDashboardData = Boolean\(summary && \(/);
  assert.match(dashboardMain, /mealRows\.some\(\(row\) => row\.amount !== 0 \|\| row\.count !== 0\)/);
  assert.match(dashboardMain, /summary\.series\.some\(\(row\) => row\.amount !== 0 \|\| row\.count !== 0\)/);
  assert.match(dashboardMain, /const amountRank = !hasDashboardData \? \[\]/);
  assert.match(dashboardMain, /const countRank = !hasDashboardData \? \[\]/);
  assert.match(dashboardMain, /series=\{hasDashboardData \? summary\.series : \[\]\}/);
});

test('charts have independent gradients and explicit amount/count colors', () => {
  assert.match(main, /function TrendChart\(\{ title, series, valueKey, money = false, color \}\)/);
  assert.match(main, /useId\(\)/);
  assert.match(main, /const gradientId = `dash-area-/);
  assert.match(main, /style=\{\{ stroke: color \}\}/);
  assert.match(main, /color="#2FB865"/);
  assert.match(main, /color="#4C8BF5"/);
  assert.match(main, /compactMoneyTick/);
  assert.match(main, /Math\.ceil\(series\.length \/ 6\)/);
});

test('dashboard breakpoints keep summary at three columns and details stacked until desktop', () => {
  assert.match(css, /@media \(min-width: 768px\)[\s\S]*?\.dash-summary-grid \{ grid-template-columns: repeat\(3,/);
  assert.match(css, /@media \(min-width: 1200px\)[\s\S]*?\.dash-two-grid \{ grid-template-columns: repeat\(2,/);
  assert.match(css, /@media \(max-width: 767px\)[\s\S]*?\.dash-period \{ align-items: stretch; flex-direction: column; \}/);
  assert.match(css, /\.dash-page/);
  assert.match(css, /\.dash-card-title/);
  assert.match(css, /\.dash-table-heading/);
});
