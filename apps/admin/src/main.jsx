import React from 'react';
import { createRoot } from 'react-dom/client';
import { QrCode, WalletCards, Users, FileSpreadsheet } from 'lucide-react';
import './style.css';

const cards = [
  ['금일 사용액', '428,000원', WalletCards],
  ['직원', '10명', Users],
  ['제휴 식당', '5곳', QrCode],
  ['이번달 정산 예정', '3,920,000원', FileSpreadsheet],
];

function App() {
  return <main className="shell">
    <header>
      <p className="eyebrow">MealLedger Admin</p>
      <h1>밥장부 관리자</h1>
      <p>직원·정책·지급·정산을 한 곳에서 관리하는 초기 화면입니다.</p>
    </header>
    <section className="grid">
      {cards.map(([label, value, Icon]) => <article className="card" key={label}>
        <Icon size={28}/><span>{label}</span><strong>{value}</strong>
      </article>)}
    </section>
    <section className="panel">
      <h2>M1 연결 예정</h2>
      <ul>
        <li>직원 CSV 등록</li>
        <li>식사창구 정책 편집</li>
        <li>식대 포인트 지급</li>
        <li>QR 스티커 PDF 생성</li>
        <li>식당 조회 라우트 /m/:token</li>
      </ul>
    </section>
  </main>;
}

createRoot(document.getElementById('root')).render(<App />);
