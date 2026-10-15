import React, { useEffect, useRef, useState } from "react";
import { publishedLegalAvailable } from "./purchaseSafety.js";
import "./purchase.css";

import PurchaseDashboard from "./PurchaseDashboard.jsx";

export function usePublishedLegal() {
  const [legal, setLegal] = useState({ ready: false, terms: "" });
  useEffect(() => {
    let alive = true;
    Promise.all(
      ["/terms.html", "/privacy.html"].map(async (url) => {
        const response = await fetch(url);
        return response.ok
          ? new DOMParser().parseFromString(await response.text(), "text/html")
              .body.textContent
          : "";
      }),
    )
      .then((documents) => {
        if (alive)
          setLegal({
            ready: publishedLegalAvailable(documents),
            terms: documents[0],
          });
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  return legal;
}
export function LegalGate({ ready }) {
  return (
    !ready && (
      <p role="alert">
        이용약관 또는 개인정보 처리방침을 불러오지 못했어요.
        가입·구매를 진행할 수 없어요.
      </p>
    )
  );
}
export default function PurchaseApp({ supabase, apiBaseUrl }) {
  const [session, setSession] = useState(null),
    [booting, setBooting] = useState(true),
    [error, setError] = useState("");
  const scope = useRef({ id: null, generation: 0 });
  useEffect(() => {
    if (!supabase) {
      setBooting(false);
      return;
    }
    let alive = true,
      eventSeen = false;
    const adopt = (next) => {
      if (!alive) return;
      const id = next?.user?.id ?? null;
      if (id !== scope.current.id)
        scope.current = { id, generation: scope.current.generation + 1 };
      setSession(next);
      setBooting(false);
    };
    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      eventSeen = true;
      adopt(next);
    });
    supabase.auth
      .getSession()
      .then((result) => {
        if (!eventSeen) adopt(result.data.session);
      })
      .catch((e) => {
        if (alive) {
          setError(e.message);
          setBooting(false);
        }
      });
    return () => {
      alive = false;
      scope.current.generation++;
      data.subscription.unsubscribe();
    };
  }, [supabase]);
  async function logout() {
    scope.current = { id: null, generation: scope.current.generation + 1 };
    setSession(null);
    const result = await supabase.auth.signOut();
    if (result.error) setError(result.error.message);
  }
  return (
    <main className={`purchase-app ${session ? "signed-in" : "signed-out"}`}>
      {error && <p role="alert">{error}</p>}
      {!supabase || !apiBaseUrl ? (
        <p role="alert">공개 로그인/API 설정이 없어 사용할 수 없어요.</p>
      ) : booting ? (
        <p role="status">로그인 확인 중…</p>
      ) : session ? (
        <Wallet
          key={session.user.id}
          supabase={supabase}
          apiBaseUrl={apiBaseUrl}
          scope={scope}
          userId={session.user.id}
          logout={logout}
        />
      ) : (
        <Login supabase={supabase} />
      )}
      <footer>
        <a href="/terms.html" target="_blank" rel="noreferrer">
          이용약관
        </a>
        <a href="/privacy.html" target="_blank" rel="noreferrer">
          개인정보 처리방침
        </a>
        <a href="/">관리자 화면</a>
      </footer>
    </main>
  );
}
function Login({ supabase }) {
  const [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [joining, setJoining] = useState(false),
    [consent, setConsent] = useState(false),
    [notice, setNotice] = useState("");
  const { ready } = usePublishedLegal();
  async function submit(event) {
    event.preventDefault();
    if (lock.current || (joining && (!consent || !ready))) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const result = joining
        ? await supabase.auth.signUp({
            email,
            password,
            options: { emailRedirectTo: `${window.location.origin}/shop` },
          })
        : await supabase.auth.signInWithPassword({ email, password });
      if (result.error) throw result.error;
      if (joining && !result.data.session)
        setNotice("이메일 인증 링크를 확인한 후 로그인해 주세요.");
    } catch (e) {
      setError(e.message);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="purchase-login">
      <img src="/brand/greeneat_logo_light.png" alt="그린잇" />
      <p className="login-mode">웹 전용 이메일 로그인</p>
      <h1>식권 구매</h1>
      <p className="login-headline">이메일로<br />맛있는 한 끼를 시작하세요</p>
      <p>앱의 휴대폰 인증과 다른 로그인 방식이에요.</p>
      <form onSubmit={submit}>
        <label>
          이메일
          <input
            type="email"
            required
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          비밀번호
          <input
            type="password"
            required
            minLength={joining ? 8 : undefined}
            autoComplete={joining ? "new-password" : "current-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {joining && (
          <>
            <LegalGate ready={ready} />
            <label className="purchase-check">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
              />
              약관 및 개인정보 처리방침 확인
            </label>
          </>
        )}
        <button disabled={busy || (joining && (!consent || !ready))}>
          {joining ? "가입 신청" : "로그인"}
        </button>
      </form>
      <button
        className="secondary"
        disabled={busy}
        onClick={() => {
          setJoining(!joining);
          setError("");
          setNotice("");
        }}
      >
        {joining ? "로그인으로 돌아가기" : "회원가입"}
      </button>
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
function Registration({ api, refresh }) {
  const { ready } = usePublishedLegal();
  const [name, setName] = useState(""),
    [phone, setPhone] = useState(""),
    [consent, setConsent] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const lock = useRef(false);
  const [invite, setInvite] = useState("");
  async function submit(event, employee = false) {
    event.preventDefault();
    if (lock.current || !ready || !consent || (employee && !invite.trim()))
      return;
    const normalized = phone.replace(/[^0-9]/g, "");
    if (!name.trim() || !/^01[016789][0-9]{7,8}$/.test(normalized)) {
      setError("이름과 올바른 휴대폰 번호를 입력해 주세요.");
      return;
    }
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await api(employee ? "/join/request" : "/consumer/register", {
        display_name: name.trim(),
        phone: normalized,
        ...(employee ? { invite_code: invite.trim() } : {}),
      });
      await refresh();
    } catch (e) {
      if (!e.stale) setError(e.message);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="purchase-login">
      <h1>구매자 등록</h1>
      <LegalGate ready={ready} />
      <form onSubmit={submit}>
        <label>
          이름
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label>
          휴대폰 번호
          <input
            type="tel"
            required
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
        </label>
        <label className="purchase-check">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
          />
          약관 및 개인정보 처리방침 확인
        </label>
        <button disabled={busy || !ready || !consent}>
          일반 구매자로 등록
        </button>
        <label>
          회사 초대코드
          <input value={invite} onChange={(e) => setInvite(e.target.value)} />
        </label>
        <button
          type="button"
          disabled={busy || !ready || !consent || !invite.trim()}
          onClick={(event) => submit(event, true)}
        >
          회사 가입 신청
        </button>
      </form>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
function Wallet({ supabase, apiBaseUrl, scope, userId, logout }) {
  const legal = usePublishedLegal();
  const [me, setMe] = useState(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false);
  const version = useRef(0);
  async function api(path, body, options = {}) {
    const generation = scope.current.generation;
    const current = () =>
      scope.current.id === userId && scope.current.generation === generation;
    const result = options.public ? null : await supabase.auth.getSession();
    if (!current() || (!options.public && (result.error || result.data.session?.user.id !== userId)))
      throw Object.assign(new Error("계정이 변경됐어요."), {
        stale: !current(),
      });
    const response = await fetch(`${apiBaseUrl}${path}`, {
      method: body === undefined ? "GET" : "POST",
      ...((options.requestTimeoutMs || (body === undefined && options.readTimeoutMs)) ? { signal: AbortSignal.timeout(options.requestTimeoutMs || options.readTimeoutMs) } : {}),
      headers: {
        ...(!options.public ? { Authorization: `Bearer ${result.data.session.access_token}` } : {}),
        "Content-Type": "application/json",
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const payload = await response.json();
    if (!current())
      throw Object.assign(new Error("계정이 변경됐어요."), { stale: true });
    if (!response.ok || payload.ok === false)
      throw Object.assign(
        new Error(
          payload.detail?.message ||
            payload.error?.message ||
            "요청을 확인하지 못했어요.",
        ),
        {
          code: payload.detail?.code || payload.error?.code,
          status: response.status,
          // Only these actual FastAPI pre-handler refusals prove non-consumption.
          scanNotConsumed: path === '/transactions/scan' && (
            (response.status === 400 && payload.detail?.code === 'INVALID_QR') ||
            (response.status === 422 && Array.isArray(payload.detail) && payload.detail.length > 0 && payload.detail.every(issue =>
              Array.isArray(issue.loc) && issue.loc.length === 2 && issue.loc[0] === 'body' &&
              ['qr_data', 'idempotency_key'].includes(issue.loc[1]) &&
              ['missing', 'string_type', 'string_too_short', 'string_too_long'].includes(issue.type) && typeof issue.msg === 'string'
            ))
          ),
        },
      );
    return payload.data ?? payload;
  }
  async function refresh() {
    const run = ++version.current;
    setLoading(true);
    setError("");
    try {
      const profile = await api("/me");
      if (!profile || (profile.status === 'active' && ['customer', 'employee'].includes(profile.role) && profile.user_id !== userId)) {
        if (run === version.current) setMe(null);
        throw new Error('계정 소유자 정보를 확인하지 못했어요. 계정을 다시 확인해 주세요.');
      }
      if (run === version.current) setMe(profile);
    } catch (e) {
      if (!e.stale && run === version.current) setError(e.message);
    } finally {
      if (run === version.current) setLoading(false);
    }
  }
  useEffect(() => {
    refresh();
    return () => {
      version.current++;
    };
  }, []);
  if (
    me?.status === "no_profile" ||
    (me?.role === "employee" && me.status === "rejected")
  )
    return <><Registration api={api} refresh={refresh} /><button onClick={logout}>로그아웃</button></>;
  if (
    me &&
    !(me.status === "active" && ["customer", "employee"].includes(me.role))
  )
    return (
      <section className="purchase-card">
        <h1>계정 상태</h1>
        <p role="alert">
          {["customer", "employee"].includes(me.role)
            ? `계정 상태: ${me.status}. 승인된 계정만 구매할 수 있어요.`
            : "구매자 계정이 아니에요. 관리자 화면을 이용해 주세요."}
        </p>
        <button onClick={refresh} disabled={loading}>
          새로고침
        </button>
        <button onClick={logout}>로그아웃</button>
      </section>
    );
  return (
    <>
      {error && <p role="alert">{error}</p>}
      {!me && <>{loading ? <p role="status">계정 확인 중…</p> : <p>계정 정보를 불러오지 못했어요.</p>}<button disabled={loading} onClick={refresh}>계정 다시 확인</button><button onClick={logout}>로그아웃</button></>}
      {me && (
        <PurchaseDashboard
          api={api}
          me={me}
          revision={version.current}
          apiBaseUrl={apiBaseUrl}
          legal={legal}
          refresh={refresh}
          logout={logout}
          loading={loading}
        />
      )}
    </>
  );
}
