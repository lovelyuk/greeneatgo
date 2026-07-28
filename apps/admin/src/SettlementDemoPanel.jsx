import React, { useEffect, useRef, useState } from 'react';
import {
  DEMO_ACTIONS, DEMO_STAGES, demoInteractionsLocked, demoLoadStatus, invoiceApprovalLabel, nextDemoAction, optionReason,
  pastMonths, readinessState, stageState, statusLabel,
} from './settlementDemo.js';
import { createSettlementDemoLifecycle, isLifecycleAbort } from './settlementDemoLifecycle.js';

const API_ROOT = '/admin/merchant/settlement-demo';
const READINESS_BADGES = [
  ['configured', '팝빌 설정'], ['is_test', '테스트 환경'], ['certificate', '인증서'],
  ['supplier_ready', '공급자 정보'], ['corp_matches', '사업자번호 일치'],
];
const ACTION_ORDER = ['seeded', 'draft', 'confirmed', 'issued'];
const STALE_AFTER_ACTION_MESSAGE = '작업은 성공했지만 최신 상태를 불러오지 못했습니다. 다시 시도해 최신 상태를 불러와 주세요.';

function idempotencyKey() {
  if (globalThis.crypto?.randomUUID) return `settlement-demo-reset:${globalThis.crypto.randomUUID()}`;
  const bytes = new Uint32Array(4);
  globalThis.crypto?.getRandomValues?.(bytes);
  return `settlement-demo-reset:${Date.now()}:${Array.from(bytes).join('-')}`;
}

function formatDateTime(value) {
  if (!value) return '대기';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('ko-KR');
}

export default function SettlementDemoPanel({ token, apiFetch, openDocumentInNewWindow, krw }) {
  const months = useState(() => pastMonths(12))[0];
  const [state, setState] = useState(null);
  const [companyId, setCompanyId] = useState('');
  const [periodYm, setPeriodYm] = useState(months[0] ?? '');
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reloadRequired, setReloadRequired] = useState(false);
  const lifecycleRef = useRef(null);
  lifecycleRef.current ??= createSettlementDemoLifecycle();

  function publish(capture, update) {
    if (lifecycleRef.current.isCurrent(capture)) update();
  }

  async function load({ quiet = false } = {}) {
    const lifecycle = lifecycleRef.current;
    const request = lifecycle.beginRead('state');
    if (!lifecycle.isCurrent(request.capture)) {
      request.finish();
      return null;
    }
    if (!quiet) publish(request.capture, () => setLoading(true));
    publish(request.capture, () => setError(''));
    try {
      const data = await apiFetch(API_ROOT, token, { signal: request.signal });
      if (!lifecycle.isCurrent(request.capture)) return null;
      if (data === null || typeof data !== 'object') throw new Error('시연 상태 응답이 올바르지 않습니다.');
      publish(request.capture, () => {
        setState(data);
        setReloadRequired(false);
        if (!data?.seeded) {
          setCompanyId((current) => {
            if (!lifecycle.isCurrent(request.capture)) return current;
            return data?.options?.some((option) => option.company_id === current && option.eligible) ? current : '';
          });
        }
      });
      return data;
    } catch (loadError) {
      if (!lifecycle.isCurrent(request.capture) || isLifecycleAbort(loadError)) return null;
      publish(request.capture, () => {
        setReloadRequired(true);
        setError(loadError.message || '시연 상태를 불러오지 못했습니다.');
      });
      throw loadError;
    } finally {
      request.finish();
      publish(request.capture, () => setLoading(false));
    }
  }

  useEffect(() => {
    const lifecycle = lifecycleRef.current;
    lifecycle.activate(token);
    setState(null);
    setCompanyId('');
    setPeriodYm(months[0] ?? '');
    setLoading(true);
    setPending('');
    setError('');
    setNotice('');
    setReloadRequired(false);
    load().catch(() => {});
    return () => { lifecycle.invalidate(); };
    // token identifies the authenticated screen lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const readiness = readinessState(state?.readiness);
  const loadStatus = demoLoadStatus(state, loading, error, reloadRequired);
  const hasDisplayableState = loadStatus === 'loaded' || loadStatus === 'stale';
  const selectedOption = state?.options?.find((option) => option.company_id === companyId);
  const action = nextDemoAction(state?.stage, state?.readiness);
  const mutationDisabled = demoInteractionsLocked(state, {
    loading, reloadRequired, pending: lifecycleRef.current.locked,
  });
  const controlsDisabled = mutationDisabled || readiness.production;

  async function mutate(endpoint, body, headers) {
    if (reloadRequired || state === null) return;
    const lifecycle = lifecycleRef.current;
    const mutation = lifecycle.acquireAction();
    if (!mutation) return;
    publish(mutation, () => {
      setPending(endpoint);
      setError('');
      setNotice('');
    });
    try {
      await apiFetch(`${API_ROOT}/${endpoint}`, token, {
        method: 'POST', headers, body: body ? JSON.stringify(body) : undefined,
      });
      // A completed POST may have committed. Never abort it; only the generation
      // that submitted it may refresh or publish its result.
      if (!lifecycle.isCurrent(mutation)) return;
      try {
        const refreshedState = await load({ quiet: true });
        if (refreshedState === null) return;
      } catch {
        publish(mutation, () => {
          setNotice('');
          setReloadRequired(true);
          setError(STALE_AFTER_ACTION_MESSAGE);
        });
        return;
      }
      publish(mutation, () => setNotice(endpoint === 'reset' ? '시연을 초기화했습니다. 자동 실행하지 않습니다.' : '단계가 완료되었습니다.'));
    } catch (actionError) {
      publish(mutation, () => setError(actionError.message || '요청을 처리하지 못했습니다.'));
    } finally {
      lifecycle.releaseAction(mutation);
      publish(mutation, () => setPending(''));
    }
  }

  function seed() {
    if (!selectedOption?.eligible || !periodYm || controlsDisabled) return;
    mutate('seed', { company_id: companyId, period_ym: periodYm });
  }

  function reset() {
    if (mutationDisabled || !state?.seeded) return;
    if (!window.confirm('현재 시연 데이터와 선택을 초기화할까요? 발행된 문서는 보존될 수 있습니다.')) return;
    mutate('reset', null, { 'Idempotency-Key': idempotencyKey() });
  }

  async function openDocument(kind) {
    if (mutationDisabled || readiness.production || !state?.settlement?.id) return;
    const lifecycle = lifecycleRef.current;
    const documentAction = lifecycle.acquireAction();
    if (!documentAction) return;
    const documentRequest = lifecycle.beginRead('document');
    publish(documentAction, () => {
      setPending(kind);
      setError('');
    });
    try {
      await openDocumentInNewWindow(window.open.bind(window), async () => {
        const data = await apiFetch(`/admin/merchant/settlements/${encodeURIComponent(state.settlement.id)}/tax-invoice/${kind}-url`, token, {
          signal: documentRequest.signal,
        });
        // Throwing here makes openDocumentInNewWindow close its already-opened
        // blank popup and prevents navigation for an obsolete token/component.
        lifecycle.requireCurrent(documentAction);
        lifecycle.requireCurrent(documentRequest.capture);
        return data?.url;
      });
    } catch (documentError) {
      if (!isLifecycleAbort(documentError)) {
        publish(documentAction, () => setError(documentError.message || '문서를 열지 못했습니다.'));
      }
    } finally {
      documentRequest.finish();
      lifecycle.releaseAction(documentAction);
      publish(documentAction, () => setPending(''));
    }
  }

  const settlement = state?.settlement;
  const issued = ['issued', 'nts_sending', 'nts_accepted'].includes(settlement?.tax_invoice_status);

  return <section className={`panel settlement-demo-panel${readiness.production ? ' production' : ''}${loadStatus === 'stale' ? ' stale' : ''}`} aria-labelledby="settlement-demo-title">
    <div className="panel-title settlement-demo-heading">
      <div>
        <h2 id="settlement-demo-title">정산·세금계산서 시연</h2>
        <p className="settlement-demo-warning">팝빌 테스트 환경에서만 동작 · 실제 돈 이동 없음</p>
      </div>
      <button type="button" className="ghost" onClick={() => load().catch(() => {})} disabled={loading || Boolean(pending)} aria-label="시연 상태 새로고침">
        {loading ? '불러오는 중' : loadStatus === 'failed' || reloadRequired ? '다시 시도' : '새로고침'}
      </button>
    </div>

    <div className="settlement-demo-readiness" aria-label="팝빌 시연 준비 상태" aria-busy={loading}>
      {READINESS_BADGES.map(([key, label]) => <span key={key} className={`badge readiness-${loadStatus === 'loaded' ? readiness[key] ? 'ready' : 'not-ready' : 'loading'}`}>
        {label}: {loadStatus === 'loading' ? '확인 중' : loadStatus === 'failed' ? '확인 실패' : loadStatus === 'stale' ? '최신 상태 필요' : readiness[key] ? '준비됨' : '미준비'}
      </span>)}
    </div>
    {state?.readiness?.certificate_expires_on && <p className="panel-note">인증서 만료일: {state.readiness.certificate_expires_on}</p>}
    {readiness.production && <div className="alert error" role="alert">실제 발행 위험을 막기 위해 운영 모드에서는 시연 단계 버튼을 사용할 수 없습니다. 초기화만 가능합니다.</div>}
    {error && <div className="alert error" role="alert" aria-live="assertive">{error}</div>}
    {loadStatus === 'stale' && <div className="alert warning" role="status">표시된 정보는 이전 상태입니다. 최신 상태를 성공적으로 불러올 때까지 모든 작업과 문서 열기를 사용할 수 없습니다.</div>}
    {loadStatus === 'failed' && <p className="empty-state">시연 상태를 확인할 수 없습니다. 위의 다시 시도 버튼으로 재시도해 주세요.</p>}
    <div className="sr-only" aria-live="polite">{notice || (loading ? '시연 상태를 불러오는 중입니다.' : '')}</div>
    {notice && <div className="alert success" role="status">{notice}</div>}

    {hasDisplayableState && !state.seeded && <div className="settlement-demo-seed">
      <label htmlFor="settlement-demo-company">시연 회사
        <select id="settlement-demo-company" value={companyId} onChange={(event) => setCompanyId(event.target.value)} disabled={controlsDisabled}>
          <option value="">회사를 선택해 주세요</option>
          {(state?.options ?? []).map((option) => <option key={option.company_id} value={option.company_id} disabled={!option.eligible}>
            {option.company_name} · 임직원 {option.active_employee_customer_count}명 · 관리자 {option.active_company_admin_available ? '준비' : '미준비'} · 사업자정보 {option.invoice_legal_profile_complete ? '준비' : '미준비'}{option.eligible ? '' : ` · ${optionReason(option)}`}
          </option>)}
        </select>
      </label>
      <label htmlFor="settlement-demo-month">시연 대상 월 (지난달 이전)
        <select id="settlement-demo-month" value={periodYm} onChange={(event) => setPeriodYm(event.target.value)} disabled={controlsDisabled}>
          {months.map((month) => <option value={month} key={month}>{month}</option>)}
        </select>
      </label>
      <button type="button" className="primary" onClick={seed} disabled={controlsDisabled || !selectedOption?.eligible || !periodYm}>
        {pending === 'seed' ? '시연 거래 생성 중' : '시연 거래 생성 (데이터 심기)'}
      </button>
      {(state.options ?? []).length === 0 && <p className="empty-state">연결된 활성 회사가 없습니다.</p>}
      {companyId && <p className="panel-note">선택 조건: {optionReason(selectedOption)}</p>}
    </div>}

    {hasDisplayableState && state.seeded && <>
      <dl className="settlement-demo-summary">
        <div><dt>선택 회사</dt><dd>{state.company_name}</dd></div>
        <div><dt>대상 월</dt><dd>{state.period_ym}</dd></div>
        <div><dt>무작위 시연 거래</dt><dd>{state.transaction_count ?? state.aggregate?.transaction_count ?? 0}건</dd></div>
        <div><dt>공급가액 합계</dt><dd>{krw(state.aggregate?.supply_amount)}</dd></div>
        <div><dt>부가세 합계</dt><dd>{krw(state.aggregate?.vat_amount)}</dd></div>
        <div><dt>거래 합계</dt><dd>{krw(state.aggregate?.total_amount)}</dd></div>
      </dl>

      <ol className="settlement-demo-timeline" aria-label="시연 단계">
        {DEMO_STAGES.map((item) => <li key={item.key} className={stageState(state.stage, item.key)} aria-current={state.stage === item.key ? 'step' : undefined}>
          <span aria-hidden="true" />{item.label}
        </li>)}
      </ol>

      <div className="settlement-demo-actions" aria-label="시연 단계 작업">
        {ACTION_ORDER.map((stage) => {
          const item = DEMO_ACTIONS[stage];
          const exactNext = action?.endpoint === item.endpoint && action.enabled;
          return <button type="button" className="primary" key={item.endpoint} onClick={() => mutate(item.endpoint)} disabled={!exactNext || controlsDisabled}>
            {pending === item.endpoint ? `${item.label} 처리 중` : item.label}
          </button>;
        })}
      </div>

      {settlement && <div className="settlement-demo-details">
        <h3>정산·발행 실제 응답 상태</h3>
        <dl className="settlement-demo-status-grid">
          <div><dt>기존 정산 상태</dt><dd>{statusLabel('legacy', settlement.status)}</dd></div>
          <div><dt>정산 워크플로</dt><dd>{statusLabel('workflow', settlement.settlement_status)}</dd></div>
          <div><dt>세금계산서</dt><dd>{statusLabel('tax', settlement.tax_invoice_status)}</dd></div>
          <div><dt>입금</dt><dd>{statusLabel('payment', settlement.payment_status)}</dd></div>
          <div><dt>공급가액</dt><dd>{krw(settlement.supply_amount)}</dd></div>
          <div><dt>부가세</dt><dd>{krw(settlement.vat_amount)}</dd></div>
          <div><dt>합계</dt><dd>{krw(settlement.total_amount)}</dd></div>
          <div><dt>발행 일시</dt><dd>{formatDateTime(settlement.issued_at)}</dd></div>
          <div className="wide"><dt>국세청 승인번호</dt><dd>{invoiceApprovalLabel(settlement, state.stage)}</dd></div>
        </dl>
        <div className="row-actions">
          {settlement.can_view_tax_invoice && <button type="button" className="ghost" disabled={mutationDisabled || readiness.production} onClick={() => openDocument('view')}>{pending === 'view' ? '여는 중' : '테스트 세금계산서 보기'}</button>}
          {settlement.can_download_tax_invoice_pdf && <button type="button" className="ghost" disabled={mutationDisabled || readiness.production} onClick={() => openDocument('pdf')}>{pending === 'pdf' ? '여는 중' : '테스트 세금계산서 PDF'}</button>}
          {issued && !settlement.nts_confirm_num && <span className="panel-note">테스트 발행 완료 / 국세청 승인번호 없음</span>}
        </div>
      </div>}

      <button type="button" className="reject settlement-demo-reset" disabled={mutationDisabled} onClick={reset}>
        {pending === 'reset' ? '초기화 중' : '시연 초기화'}
      </button>
    </>}
  </section>;
}
