// Restaurant dashboard: revenue on the paid/issued basis next to the usage basis,
// a per-partner table, and a detail popup per partner.
import React, { useEffect, useRef, useState } from 'react';
import { mapRevenueDetail, mapRevenueSummary, partyByName, won } from './revenueBasis.js';
import './revenueBasis.css';

function Card({ tone, label, value, lines }) {
  return <article className={`dash-card revenue-basis-card revenue-basis-${tone}`}>
    <span className="revenue-basis-label">{label}</span>
    <strong className="revenue-basis-value">{won(value)}</strong>
    {lines.map((line) => <small key={line}>{line}</small>)}
  </article>;
}

function DetailDialog({ party, period, fetcher, onClose }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('paid');
  const [attempt, setAttempt] = useState(0);
  const closeRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    setDetail(null); setError('');
    fetcher(`/admin/merchant/revenue/detail?from=${encodeURIComponent(period.from)}&to=${encodeURIComponent(period.to)}&party=${encodeURIComponent(party.key)}`)
      .then((data) => { if (!cancelled) setDetail(mapRevenueDetail(data)); })
      .catch((loadError) => { if (!cancelled) setError(loadError.message || '세부 내역을 불러오지 못했어요.'); });
    return () => { cancelled = true; };
  }, [party.key, period.from, period.to, attempt]);
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return <div className="modal-backdrop" onClick={onClose}>
    <section className="revenue-detail" role="dialog" aria-modal="true" aria-labelledby="revenue-detail-title" onClick={(event) => event.stopPropagation()}>
      <header className="revenue-detail-head">
        <div><h2 id="revenue-detail-title">{party.name} 매출 세부 내역</h2><p>{period.from} ~ {period.to}</p></div>
        <button ref={closeRef} type="button" className="ghost" onClick={onClose} aria-label="닫기">닫기</button>
      </header>
      {error && <div className="alert error" role="alert">{error} <button type="button" className="ghost" onClick={() => setAttempt((value) => value + 1)}>다시 시도</button></div>}
      {!detail && !error && <p className="revenue-detail-loading" role="status">세부 내역을 불러오는 중입니다.</p>}
      {detail && <>
        <div className="revenue-detail-totals">
          <div><span>매출 (결제·발행 기준)</span><strong>{won(detail.paid.revenue)}</strong><small>결제 {won(detail.paid.payment)} − 환불 {won(detail.paid.refund)} + 세금계산서 {won(detail.paid.invoice)}</small></div>
          <div><span>식사 제공 (사용 기준)</span><strong>{won(detail.usage.amount)}</strong><small>{detail.usage.count.toLocaleString('ko-KR')}끼{detail.usage.cancelCount ? ` · 취소 ${detail.usage.cancelCount}건` : ''}</small></div>
          <div><span>미청구 장부 금액</span><strong>{won(detail.unbilled.amount)}</strong><small>{detail.unbilled.settlements.length ? detail.unbilled.settlements.map((row) => `${row.month} ${won(row.amount)}`).join(' · ') : '세금계산서 발행 전 금액 없음'}</small></div>
        </div>
        <div className="revenue-detail-tabs" role="tablist" aria-label="세부 내역 구분">
          <button type="button" role="tab" aria-selected={tab === 'paid'} className={tab === 'paid' ? 'active' : ''} onClick={() => setTab('paid')}>결제·발행 내역 ({detail.paid.entryCount})</button>
          <button type="button" role="tab" aria-selected={tab === 'daily'} className={tab === 'daily' ? 'active' : ''} onClick={() => setTab('daily')}>날짜별 식사 ({detail.usage.daily.length})</button>
          <button type="button" role="tab" aria-selected={tab === 'meals'} className={tab === 'meals' ? 'active' : ''} onClick={() => setTab('meals')}>식사 건 목록 ({detail.usage.itemCount})</button>
        </div>
        <div className="revenue-detail-body" role="tabpanel">
          {tab === 'paid' && (detail.paid.entries.length === 0 ? <p className="dash-empty">이 기간에 결제나 세금계산서 발행이 없습니다.</p> : <table>
            <thead><tr><th>날짜</th><th>시간</th><th>구분</th><th>내역</th><th>결제자</th><th>결제수단 / 승인번호</th><th className="money">금액</th></tr></thead>
            <tbody>{detail.paid.entries.map((row, index) => <tr key={`${row.kind}-${index}`} className={row.amount < 0 ? 'revenue-negative' : undefined}><td>{row.date}</td><td>{row.time}</td><td>{row.kindLabel}</td><td>{row.label}</td><td>{row.who || '-'}</td><td>{row.note || '-'}</td><td className="money">{won(row.amount)}</td></tr>)}</tbody>
          </table>)}
          {tab === 'daily' && (detail.usage.daily.length === 0 ? <p className="dash-empty">이 기간에 식사 기록이 없습니다.</p> : <table>
            <thead><tr><th>날짜</th><th className="money">식사</th><th className="money">취소</th><th className="money">금액</th></tr></thead>
            <tbody>{detail.usage.daily.map((row) => <tr key={row.date}><td>{row.date}</td><td className="money">{row.count.toLocaleString('ko-KR')}끼</td><td className="money">{row.cancelCount ? `${row.cancelCount}건` : '-'}</td><td className="money">{won(row.amount)}</td></tr>)}</tbody>
          </table>)}
          {tab === 'meals' && (detail.usage.items.length === 0 ? <p className="dash-empty">이 기간에 식사 기록이 없습니다.</p> : <>
            <table>
              <thead><tr><th>날짜</th><th>시간</th><th>이름</th><th>부서</th><th>사번</th><th>구분</th><th>내역</th><th className="money">금액</th></tr></thead>
              <tbody>{detail.usage.items.map((row) => <tr key={row.id} className={row.amount < 0 ? 'revenue-negative' : undefined}><td>{row.date}</td><td>{row.time}</td><td>{row.name}</td><td>{row.department}</td><td>{row.employeeNo}</td><td>{row.kindLabel}</td><td>{row.item}</td><td className="money">{won(row.amount)}</td></tr>)}</tbody>
            </table>
            {detail.usage.itemCount > detail.usage.items.length && <p className="revenue-detail-note">최근 {detail.limit.toLocaleString('ko-KR')}건만 표시했어요. 전체 {detail.usage.itemCount.toLocaleString('ko-KR')}건은 기간을 줄여 조회해 주세요.</p>}
          </>)}
        </div>
      </>}
    </section>
  </div>;
}

/**
 * fetcher(path) resolves the API `data`. `openName` (a company name clicked in
 * the dashboard's ranking tables) opens that partner's popup.
 */
export default function RevenueBasisPanel({ period, fetcher, openName = '', onOpened }) {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setSummary(null); setError(''); setSelected(null);
    fetcher(`/admin/merchant/revenue/summary?from=${encodeURIComponent(period.from)}&to=${encodeURIComponent(period.to)}`)
      .then((data) => { if (!cancelled) setSummary(mapRevenueSummary(data)); })
      .catch((loadError) => { if (!cancelled) setError(loadError.message || '매출 현황을 불러오지 못했어요.'); });
    return () => { cancelled = true; };
  }, [period.from, period.to, attempt]);
  useEffect(() => {
    if (!openName || !summary) return;
    const party = partyByName(summary.parties, openName);
    if (party) setSelected(party);
    onOpened?.();
  }, [openName, summary]);

  if (error) return <div className="dash-error" role="alert">{error}<button type="button" className="ghost" onClick={() => setAttempt((value) => value + 1)}>다시 시도</button></div>;
  if (!summary) return <div className="revenue-basis revenue-basis-loading" role="status" aria-label="매출 현황을 불러오는 중"><div className="dash-card dash-skeleton"/><div className="dash-card dash-skeleton"/><div className="dash-card dash-skeleton"/></div>;
  const { paid, usage, unbilled, parties } = summary;
  return <section className="revenue-basis-section" aria-label="매출 기준별 현황">
    <div className="revenue-basis">
      <Card tone="paid" label="매출 (결제·발행 기준)" value={paid.revenue} lines={[
        `식권 결제 ${won(paid.payment)} − 환불 ${won(paid.refund)}`,
        `세금계산서 발행 ${won(paid.invoice)} (${paid.invoiceCount}건)`,
      ]}/>
      <Card tone="usage" label="식사 제공 (사용 기준)" value={usage.amount} lines={[`${usage.count.toLocaleString('ko-KR')}끼 · 식사한 날 기준`, '아래 그래프와 순위표는 이 기준입니다']}/>
      <Card tone="unbilled" label="미청구 장부 금액" value={unbilled.amount} lines={[unbilled.count ? `세금계산서 발행 전 정산 ${unbilled.count}건` : '세금계산서 발행 전 금액 없음', '조회 기간과 관계없는 현재 잔액']}/>
    </div>
    <article className="dash-card dash-detail-card revenue-basis-table">
      <div className="dash-table-heading"><h3>거래처별 매출</h3><span>거래처를 누르면 세부 내역이 열려요 · 단위: 원</span></div>
      {parties.length === 0 ? <p className="dash-empty">조회 기간의 데이터가 없습니다.</p> : <div className="dash-table-wrap"><table>
        <thead><tr><th>거래처</th><th className="money">결제·발행 기준</th><th className="money">사용 기준</th><th className="money">미청구</th></tr></thead>
        <tbody>{parties.map((party) => <tr key={party.key}>
          <td><button type="button" className="revenue-party-link" onClick={() => setSelected(party)} aria-label={`${party.name} 세부 내역 보기`}>{party.name}</button></td>
          <td className="money">{won(party.revenue_amount)}</td>
          <td className="money">{won(party.usage_amount)}<small> · {party.usage_count.toLocaleString('ko-KR')}끼</small></td>
          <td className="money">{party.unbilled_amount ? won(party.unbilled_amount) : '-'}</td>
        </tr>)}</tbody>
      </table></div>}
    </article>
    {selected && <DetailDialog party={selected} period={period} fetcher={fetcher} onClose={() => setSelected(null)}/>}
  </section>;
}
