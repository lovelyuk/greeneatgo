import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/company_meal.dart';
import 'package:greeneatgo_customer/main.dart'
    show LedgerPayChoiceScreen, PaySource, PaySourceToggle, UnifiedQrScanScreen;

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
    // First frame already shows the blocked state (no flash of the company QR).
    expect(find.byKey(const ValueKey('ledger-company-qr')), findsNothing);
    expect(find.byKey(const ValueKey('buy-personal-voucher')), findsOneWidget);
    expect(find.text('지금은 회사 식대를 쓸 수 없어요 · 이번 달 한도 200,000원을 모두 썼어요'),
        findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('pay-source-company')));
    await tester.pump();
    expect(find.byKey(const ValueKey('ledger-company-qr')), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  Map<String, dynamic> code() => {
        'code': '81${'7' * 79}',
        'expires_at': DateTime.now().millisecondsSinceEpoch ~/ 1000 + 60,
        'ttl': 60,
      };

  testWidgets('회사 장부 shows my QR first; the camera is only the fallback',
      (tester) async {
    var used = 0;
    await tester.pumpWidget(MaterialApp(
      home: LedgerPayChoiceScreen(
        session: _FakeUser(),
        personalBalance: 0,
        subsidizedFuture: Future.value(false),
        onBuyVoucher: () async {},
        companyMeal: _status({'windows': [], 'weekend_allowed': true}),
        now: () => _noonKst,
        loadCompanyCode: (_) async => code(),
        readCompanyUsage: () async => -used,
      ),
    ));
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const ValueKey('ledger-company-qr')), findsOneWidget);
    expect(find.byKey(const ValueKey('member-qr-image')), findsOneWidget);
    expect(find.text('회사 장부 QR'), findsOneWidget);
    expect(find.text('회사가 결제해요'), findsOneWidget);
    expect(find.byKey(const ValueKey('pay-source-company-blocked')), findsNothing);
    // No camera on this screen: scanning the store QR is a button below the QR.
    expect(find.byType(UnifiedQrScanScreen), findsNothing);
    await tester.scrollUntilVisible(
        find.byKey(const ValueKey('scan-store-qr-button')), 200);
    expect(find.text('카운터에 스캐너가 없을 때 사용해요'), findsOneWidget);

    // The counter scans it: the company's spending goes up, the screen says paid.
    used = 8300;
    await tester.pump(const Duration(seconds: 5));
    await tester.pump();
    expect(find.byKey(const ValueKey('member-qr-used')), findsOneWidget);
    expect(find.text('회사 장부로 결제 완료'), findsOneWidget);
    expect(find.textContaining('남은 식권'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('subsidized employees also get the QR, without the pay-source switch',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: LedgerPayChoiceScreen(
        session: _FakeUser(),
        personalBalance: 0,
        subsidizedFuture: Future.value(true),
        onBuyVoucher: () async {},
        loadCompanyCode: (_) async => code(),
        readCompanyUsage: () async => 0,
      ),
    ));
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const ValueKey('subsidized-company-qr')), findsOneWidget);
    expect(find.byKey(const ValueKey('member-qr-image')), findsOneWidget);
    expect(find.text('내 식권 QR'), findsOneWidget);
    expect(find.byKey(const ValueKey('pay-source-company')), findsNothing);
    expect(find.byType(UnifiedQrScanScreen), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  Map<String, dynamic> many(int quantity) => {
        'code': '${quantity > 1 ? '83' : '81'}${'7' * 79}',
        'quantity': quantity,
        'expires_at': DateTime.now().millisecondsSinceEpoch ~/ 1000 + 60,
        'ttl': 60,
      };

  testWidgets('회사 장부: choose how many meals, up to what the company still allows today',
      (tester) async {
    var used = 0;
    final asked = <int>[];
    await tester.pumpWidget(MaterialApp(
      home: LedgerPayChoiceScreen(
        session: _FakeUser(),
        personalBalance: 0,
        subsidizedFuture: Future.value(false),
        onBuyVoucher: () async {},
        companyMeal: _status({'windows': [], 'weekend_allowed': true, 'daily_count_limit': 3, 'remaining_today_count': 2}),
        now: () => _noonKst,
        loadCompanyCode: (quantity) async {
          asked.add(quantity);
          return many(quantity);
        },
        readCompanyUsage: () async => -used,
      ),
    ));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('최대 2끼'), findsOneWidget);
    expect(find.text('1끼'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('qr-quantity-plus')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(asked, [1, 2]);
    expect(find.text('카운터 스캐너에 화면을 대 주세요. 회사 장부로 2끼가 결제돼요.'), findsOneWidget);
    expect(find.text('이 QR은 2끼용이에요'), findsOneWidget);
    expect(tester.widget<IconButton>(find.byKey(const ValueKey('qr-quantity-plus'))).onPressed, isNull);
    used = 16600;
    await tester.pump(const Duration(seconds: 5));
    await tester.pump();
    expect(find.text('회사 장부로 2끼 결제 완료'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('회사 장부: one meal left today, or a daily count of one, shows no chooser',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: LedgerPayChoiceScreen(
        session: _FakeUser(),
        personalBalance: 0,
        subsidizedFuture: Future.value(false),
        onBuyVoucher: () async {},
        companyMeal: _status({'windows': [], 'weekend_allowed': true, 'daily_count_limit': 1, 'remaining_today_count': 1}),
        now: () => _noonKst,
        loadCompanyCode: (quantity) async => many(quantity),
        readCompanyUsage: () async => 0,
      ),
    ));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.byKey(const ValueKey('member-qr-image')), findsOneWidget);
    expect(find.byKey(const ValueKey('qr-quantity')), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('회사 장부 with no daily count: up to 10 meals', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: LedgerPayChoiceScreen(
        session: _FakeUser(),
        personalBalance: 0,
        subsidizedFuture: Future.value(false),
        onBuyVoucher: () async {},
        companyMeal: _status({'windows': [], 'weekend_allowed': true}),
        now: () => _noonKst,
        loadCompanyCode: (quantity) async => many(quantity),
        readCompanyUsage: () async => 0,
      ),
    ));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('최대 10끼'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('subsidized vouchers: the chooser is capped by the vouchers held', (tester) async {
    var held = 2;
    await tester.pumpWidget(MaterialApp(
      home: LedgerPayChoiceScreen(
        session: _FakeUser(),
        personalBalance: 0,
        subsidizedFuture: Future.value(true),
        onBuyVoucher: () async {},
        loadCompanyCode: (quantity) async => many(quantity),
        readCompanyUsage: () async => held,
      ),
    ));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('최대 2장'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('qr-quantity-plus')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('카운터 스캐너에 화면을 대 주세요. 한 번에 식권 2장이 사용돼요.'), findsOneWidget);
    held = 0;
    await tester.pump(const Duration(seconds: 5));
    await tester.pump();
    expect(find.text('식권 2장 사용 완료'), findsOneWidget);
    expect(find.text('남은 식권 0장'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });
}
