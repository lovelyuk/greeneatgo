import React, { useEffect, useRef, useState } from "react";
import { legalDocumentsReady } from "./purchaseSafety.js";
import "./purchase.css";
import PurchaseCatalog from "./PurchaseCatalog.jsx";
import PurchaseHistory from "./PurchaseHistory.jsx";

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
            ready: legalDocumentsReady(documents),
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
        사업자·결제 제공자 고지 또는 약관 정보가 미게시/미확정 상태예요.
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
    <main className="purchase-app">
      <header>
        <a href="/shop" aria-label="그린잇 구매 홈">
          <img src="/brand/greeneat_logo.png" alt="그린잇" />
        </a>
        <span>GREEN EAT · 식권</span>
        {session && <button onClick={logout}>로그아웃</button>}
      </header>
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
      <h1>식권 구매</h1>
      <p>개인 식권 및 회사 보조금 식권을 확인하세요.</p>
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
function Wallet({ supabase, apiBaseUrl, scope, userId }) {
  const legal = usePublishedLegal();
  const [me, setMe] = useState(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false);
  const version = useRef(0);
  async function api(path, body) {
    const generation = scope.current.generation;
    const current = () =>
      scope.current.id === userId && scope.current.generation === generation;
    const result = await supabase.auth.getSession();
    if (result.error || !current() || result.data.session?.user.id !== userId)
      throw Object.assign(new Error("계정이 변경됐어요."), {
        stale: !current(),
      });
    const response = await fetch(`${apiBaseUrl}${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        Authorization: `Bearer ${result.data.session.access_token}`,
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
        { code: payload.detail?.code || payload.error?.code },
      );
    return payload.data;
  }
  async function refresh() {
    const run = ++version.current;
    setLoading(true);
    setError("");
    try {
      const profile = await api("/me");
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
    return <Registration api={api} refresh={refresh} />;
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
      </section>
    );
  return (
    <>
      <section className="purchase-hero">
        <p className="eyebrow">나의 식권</p>
        <h1>식권 구매</h1>
        <p>{me?.display_name || "구매자"}님, 오늘도 맛있는 한 끼</p>
        <button onClick={refresh} disabled={loading}>
          새로고침
        </button>
      </section>
      {error && <p role="alert">{error}</p>}
      {me && (
        <section className="purchase-card">
          <h2>내 지갑</h2>
          <p>보유 식권 {me.voucher_balance ?? "—"}장</p>
          <p>포인트 {me.point_balance ?? "—"}P</p>
        </section>
      )}
      {me && (
        <PurchaseCatalog
          api={api}
          me={me}
          revision={version.current}
          apiBaseUrl={apiBaseUrl}
          legal={legal}
          refresh={refresh}
        />
      )}
      {me && <PurchaseHistory me={me} />}
    </>
  );
}
