// Platform admin screen built on the astryx design system (pilot, D-27).
// Loaded lazily from main.jsx so the other admin roles never download astryx.
import { useMemo, useState } from 'react';
import '@astryxdesign/core/reset.css';
import '@astryxdesign/core/astryx.css';
import '@astryxdesign/theme-matcha/theme.css';
import './platformAdmin.css';
import { Theme } from '@astryxdesign/core/theme';
import { matchaTheme } from '@astryxdesign/theme-matcha/built';
import { InternationalizationProvider } from '@astryxdesign/core/i18n';
import koKR from '@astryxdesign/core/locales/ko-KR.json';
import { HStack, VStack } from '@astryxdesign/core/Layout';
import { Heading, Text } from '@astryxdesign/core/Text';
import { Button } from '@astryxdesign/core/Button';
import { Badge } from '@astryxdesign/core/Badge';
import { Banner } from '@astryxdesign/core/Banner';
import { Card } from '@astryxdesign/core/Card';
import { TextInput } from '@astryxdesign/core/TextInput';
import { Table, proportional, pixel } from '@astryxdesign/core/Table';

const EMPTY_FORM = { name: '', owner_phone: '', category: '', avg_price: '' };
const STATUS_LABEL = { active: ['success', '운영 중'], paused: ['warning', '중지'], inactive: ['neutral', '비활성'] };

export function platformMerchantPayload(form) {
  const avg = String(form.avg_price ?? '').replace(/[^0-9]/g, '');
  return {
    name: form.name.trim(),
    owner_phone: form.owner_phone.trim() || null,
    category: form.category.trim() || null,
    avg_price: avg ? Number(avg) : null,
  };
}

function Panel({ children }) {
  return <Card><div style={{ padding: 20 }}>{children}</div></Card>;
}

function Stat({ label, value }) {
  return <Panel>
    <VStack gap={1}>
      <Text color="secondary" size="sm">{label}</Text>
      <Heading level={3}>{value}</Heading>
    </VStack>
  </Panel>;
}

export default function PlatformAdminScreen({ email, me, merchants, busy, error, message, onCreate, onInvite, onRefresh, onLogout }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [invitePhone, setInvitePhone] = useState({});
  const [invite, setInvite] = useState(null);
  const [copied, setCopied] = useState(false);
  const items = merchants?.items ?? [];
  const activeCount = useMemo(() => items.filter((m) => m.status === 'active').length, [items]);
  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));

  async function submit(event) {
    event.preventDefault();
    if (!form.name.trim()) return;
    if (await onCreate(platformMerchantPayload(form))) setForm(EMPTY_FORM);
  }

  async function sendInvite(merchant) {
    const phone = (invitePhone[merchant.id] ?? '').trim();
    if (!phone) return;
    const row = await onInvite(merchant.id, phone);
    if (row?.token) {
      setInvitePhone((p) => ({ ...p, [merchant.id]: '' }));
      setCopied(false);
      setInvite({ merchant: merchant.name, phone, link: `${window.location.origin}/?invite=${row.token}` });
    }
  }

  async function copyInvite() {
    try { await navigator.clipboard.writeText(invite.link); setCopied(true); } catch { setCopied(false); }
  }

  return <InternationalizationProvider locale="ko-KR" messages={{ 'ko-KR': koKR }}>
    <Theme theme={matchaTheme}>
      <div id="platform-admin"><main style={{ maxWidth: 1040, margin: '0 auto', padding: '24px 20px 48px' }}>
        <VStack gap={5}>
          <HStack gap={3} align="center">
            <img src="/brand/greeneat_logo.png" alt="그린잇" style={{ height: 36 }} />
            <VStack gap={0}>
              <Heading level={1}>플랫폼 관리</Heading>
              <Text color="secondary">식당을 등록하고 사장님에게 식당관리자 초대를 보냅니다.</Text>
            </VStack>
            <div style={{ flex: 1 }} />
            <Button variant="secondary" label="새로고침" onClick={onRefresh} isDisabled={busy} />
            <Button variant="ghost" label="로그아웃" onClick={onLogout} />
          </HStack>

          {error && <Banner status="error" title={error} />}
          {message && <Banner status="success" title={message} />}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
            <Stat label="등록 식당" value={merchants ? `${items.length}곳` : '조회 중'} />
            <Stat label="운영 중" value={merchants ? `${activeCount}곳` : '조회 중'} />
            <Stat label="권한" value="플랫폼관리자" />
          </div>

          <Panel>
            <form onSubmit={submit}>
              <VStack gap={4}>
                <Heading level={2}>식당 등록</Heading>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
                  <TextInput label="식당명" isRequired value={form.name} onChange={set('name')} placeholder="예: 그린잇" />
                  <TextInput label="사장님 연락처" isOptional value={form.owner_phone} onChange={set('owner_phone')} placeholder="010-0000-0000" inputMode="tel" />
                  <TextInput label="카테고리" isOptional value={form.category} onChange={set('category')} placeholder="예: 한식" />
                  <TextInput label="평균가(원)" isOptional value={form.avg_price} onChange={set('avg_price')} placeholder="예: 8000" inputMode="numeric" />
                </div>
                <HStack gap={2}>
                  <Button type="submit" variant="primary" label="식당 등록" isDisabled={busy || !form.name.trim()} />
                </HStack>
              </VStack>
            </form>
          </Panel>

          <Panel>
            <VStack gap={4}>
              <HStack gap={2} align="center">
                <Heading level={2}>식당 목록</Heading>
                <Badge variant="neutral" label={`${items.length}곳`} />
              </HStack>
              {items.length === 0
                ? <Text color="secondary">{merchants ? '등록된 식당이 없어요.' : '불러오는 중이에요.'}</Text>
                : <Table
                    data={items}
                    dividers="rows"
                    hasHover
                    verticalAlign="middle"
                    columns={[
                      { key: 'name', header: '식당', width: proportional(2), renderCell: (m) => <VStack gap={0}><Text weight="semibold">{m.name}</Text><Text color="secondary" size="sm">{m.category ?? '기본'}</Text></VStack> },
                      { key: 'owner_phone', header: '사장님 연락처', width: proportional(2), renderCell: (m) => <Text>{m.owner_phone ?? '-'}</Text> },
                      { key: 'status', header: '상태', width: pixel(110), renderCell: (m) => { const [variant, label] = STATUS_LABEL[m.status] ?? ['neutral', m.status ?? '-']; return <Badge variant={variant} label={label} />; } },
                      { key: 'invite', header: '식당관리자 초대', width: proportional(4), renderCell: (m) => <HStack gap={2} align="center">
                          <div style={{ flex: 1, minWidth: 160 }}><TextInput label={`${m.name} 초대 연락처`} isLabelHidden value={invitePhone[m.id] ?? ''} onChange={(v) => setInvitePhone((p) => ({ ...p, [m.id]: v }))} placeholder="초대할 연락처" inputMode="tel" /></div>
                          <Button variant="secondary" label="초대 링크 만들기" onClick={() => sendInvite(m)} isDisabled={busy || !(invitePhone[m.id] ?? '').trim()} />
                        </HStack> },
                    ]}
                  />}
              {invite && <Banner
                status="info"
                title={`${invite.merchant} 식당관리자 초대 링크 (7일 유효)`}
                description={<VStack gap={2}>
                  <Text>{invite.phone}로 아래 링크를 보내 주세요. 링크에서 이메일·비밀번호를 정하면 식당관리자 계정이 만들어집니다.</Text>
                  <HStack gap={2} align="center">
                    <div style={{ flex: 1 }}><TextInput label="초대 링크" isLabelHidden isReadOnly value={invite.link} /></div>
                    <Button variant="primary" label={copied ? '복사됨' : '링크 복사'} onClick={copyInvite} />
                  </HStack>
                </VStack>}
                isDismissable
                onDismiss={() => setInvite(null)}
              />}
            </VStack>
          </Panel>

          <Panel>
            <VStack gap={3}>
              <Heading level={2}>로그인 정보</Heading>
              <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', rowGap: 10 }}>
                <Text color="secondary">이메일</Text><Text weight="semibold">{email}</Text>
                <Text color="secondary">이름</Text><Text weight="semibold">{me?.display_name ?? '-'}</Text>
                <Text color="secondary">상태</Text><Text weight="semibold">{me?.status === 'active' ? '사용 중' : me?.status ?? '-'}</Text>
              </div>
            </VStack>
          </Panel>

          <HStack gap={2}>
            <a href="/privacy.html" target="_blank" rel="noreferrer"><Text color="secondary" size="sm">개인정보 처리방침</Text></a>
            <Text color="secondary" size="sm">|</Text>
            <a href="/terms.html" target="_blank" rel="noreferrer"><Text color="secondary" size="sm">이용약관</Text></a>
          </HStack>
        </VStack>
      </main></div>
    </Theme>
  </InternationalizationProvider>;
}
