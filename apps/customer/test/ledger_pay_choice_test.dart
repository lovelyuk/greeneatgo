import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/company_meal.dart';
import 'package:greeneatgo_customer/main.dart'
    show LedgerPayChoiceScreen, PaySource, PaySourceToggle;

class _FakeUser implements User {
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

CompanyMealStatus _status(Map<String, dynamic> meal) =>
    CompanyMealStatus.fromMe({'company_meal': meal})!;

// Wednesday 2026-11-25 12:00 KST.
final _noonKst = DateTime.utc(2026, 11, 25, 3);

void main() {
  group('companyMealBlockReason', () {
    test('no status from the server: company stays usable', () {
      expect(companyMealBlockReason(null, _noonKst), isNull);
    });

    test('limit used up: the server message is the reason', () {
      final status = _status({
        'limit_block': {'code': 'DAILY_LIMIT', 'message': '오늘 한도 10,000원을 모두 썼어요'},
        'windows': [],
        'weekend_allowed': true,
      });
      expect(companyMealBlockReason(status, _noonKst), '오늘 한도 10,000원을 모두 썼어요');
    });

    test('outside meal hours: the hours are the reason', () {
      final status = _status({
        'windows': [
          {'name': '점심', 'start': '11:30', 'end': '13:30'}
        ],
        'weekend_allowed': true,
      });
      expect(companyMealBlockReason(status, _noonKst), isNull);
      expect(companyMealBlockReason(status, DateTime.utc(2026, 11, 25, 6)),
          '사용 시간 · 점심\u00A011:30~13:30');
    });

    test('weekend not allowed', () {
      final status = _status({'windows': [], 'weekend_allowed': false});
      // Saturday 2026-11-28 12:00 KST.
      expect(companyMealBlockReason(status, DateTime.utc(2026, 11, 28, 3)),
          '주말에는 사용할 수 없어요');
    });
  });

  testWidgets('blocked 회사 장부 option is grey, cannot be chosen, and says why',
      (tester) async {
    PaySource? chosen;
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: PaySourceToggle(
      value: PaySource.personal,
      personalBalance: 2,
      companyBlockedReason: '오늘 한도 10,000원을 모두 썼어요',
      onChanged: (source) => chosen = source,
    ))));
    expect(find.text('지금 사용 불가'), findsOneWidget);
    expect(find.text('회사가 결제해요'), findsNothing);
    expect(find.byKey(const ValueKey('pay-source-company-blocked')),
        findsOneWidget);
    expect(find.text('지금은 회사 식대를 쓸 수 없어요 · 오늘 한도 10,000원을 모두 썼어요'),
        findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('pay-source-company')));
    expect(chosen, isNull);
    final ink = tester.widget<InkWell>(find.byKey(const ValueKey('pay-source-company')));
    expect(ink.onTap, isNull);
  });

  testWidgets('usable company: toggle behaves as before', (tester) async {
    PaySource? chosen;
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: PaySourceToggle(
      value: PaySource.personal,
      personalBalance: 2,
      onChanged: (source) => chosen = source,
    ))));
    expect(find.text('회사가 결제해요'), findsOneWidget);
    expect(find.byKey(const ValueKey('pay-source-company-blocked')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('pay-source-company')));
    expect(chosen, PaySource.company);
  });

  testWidgets('QR tab opens on 내 식권 when the company cannot pay now',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: LedgerPayChoiceScreen(
        session: _FakeUser(),
        personalBalance: 0,
        subsidizedFuture: Future.value(false),
        onBuyVoucher: () async {},
        companyMeal: _status({
          'limit_block': {'code': 'MONTHLY_LIMIT', 'message': '이번 달 한도 200,000원을 모두 썼어요'},
          'windows': [],
          'weekend_allowed': true,
        }),
        now: () => _noonKst,
      ),
    ));
    // First frame already shows the blocked state (no flash of the camera).
    expect(find.byKey(const ValueKey('ledger-company-scan')), findsNothing);
    expect(find.byKey(const ValueKey('buy-personal-voucher')), findsOneWidget);
    expect(find.text('지금은 회사 식대를 쓸 수 없어요 · 이번 달 한도 200,000원을 모두 썼어요'),
        findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('pay-source-company')));
    await tester.pump();
    expect(find.byKey(const ValueKey('ledger-company-scan')), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('QR tab opens on 회사 장부 when the company can pay', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: LedgerPayChoiceScreen(
        session: _FakeUser(),
        personalBalance: 0,
        subsidizedFuture: Future.value(false),
        onBuyVoucher: () async {},
        companyMeal: _status({'windows': [], 'weekend_allowed': true}),
        now: () => _noonKst,
      ),
    ));
    expect(find.byKey(const ValueKey('ledger-company-scan')), findsOneWidget);
    expect(find.text('회사가 결제해요'), findsOneWidget);
    expect(find.byKey(const ValueKey('pay-source-company-blocked')), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });
}
