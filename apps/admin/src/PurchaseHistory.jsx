import React from "react";
export default function PurchaseHistory({ me }) {
  const sections = [
    [
      "식권 사용 내역",
      me.voucher_use_history,
      (row) =>
        `${row.title} · ${row.merchant_name}${row.is_bonus ? " · 보너스" : ""}`,
    ],
    [
      "최근 이용 내역",
      me.recent_transactions,
      (row) => `${row.title} · ${row.merchant_name}`,
    ],
    [
      "포인트 내역",
      me.point_transactions,
      (row) => `${row.reason} · ${row.amount}P · 잔액 ${row.balance_after}P`,
    ],
  ];
  return (
    <section className="purchase-card">
      {sections.map(([heading, rows, title]) => (
        <div key={heading}>
          <h2>{heading}</h2>
          {!rows?.length ? (
            <p>내역이 없어요.</p>
          ) : (
            <ul>
              {rows.map((row) => (
                <li key={row.id}>
                  <strong>{title(row)}</strong>
                  <p>
                    {row.created_at
                      ? new Date(row.created_at).toLocaleString("ko-KR")
                      : "시각 정보 없음"}
                    {heading !== "포인트 내역" &&
                      ` · ${Number(row.amount).toLocaleString("ko-KR")}원`}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
      <p>
        개별 미사용 식권 만료일 및 전체 주문 내역은 현재 API에서 제공하지
        않아요.
      </p>
    </section>
  );
}
