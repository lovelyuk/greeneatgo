import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/screens/user_dashboard_shell.dart';
import 'package:greeneatgo_customer/widgets/dashboard_components.dart';

void main() {
  final fixture = <String, dynamic>{
    'display_name': '이용욱',
    'phone': '01012345678',
    'role': 'employee',
    'account_type': 'ledger',
    'company': {'name': '그린잇'},
    'month_used': 56000,
    'monthly_limit': 100000,
    'remaining_limit': 44000,
    'recent_transactions': [
      {
        'id': 1,
        'amount': 7000,
        'kind': 'spend',
        'title': '식대 사용',
        'merchant_name': '돈토식당',
        'created_at': '2026-08-02T12:24:00+09:00',
      },
    ],
  };

  Future<void> pumpDashboard(WidgetTester tester,
      {Map<String, dynamic>? data}) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(1.3)),
        child: MaterialApp(
          home: UserDashboardShell(
            data: data ?? fixture,
            onRefresh: () async {},
            onScanQr: () async {},
            onBuyVoucher: () async {},
            onCoupons: () async {},
            onOpenSettings: () async {},
            onAnnouncements: () async {},
            onReviews: () async {},
            onTerms: () async {},
            onPrivacy: () async {},
            onSignOut: () async {},
            pendingBanner: null,
            todayMenuCard: const Card(child: Text('오늘의 뷔페 메뉴')),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('home matches the ticket-first layout at 360x640 and scale 1.3',
      (tester) async {
    await pumpDashboard(tester);

    expect(find.byType(MealTicketCard), findsOneWidget);
    expect(find.text('남은 식권'), findsOneWidget);
    expect(find.text('이번 달 장부'), findsNothing);
    expect(find.text('회사 지원금'), findsNothing);
    expect(find.text('오늘의 뷔페 메뉴'), findsOneWidget);
    expect(find.byKey(const ValueKey('buy-ticket-button')), findsNothing);
    expect(find.text('이번 달 사용'), findsOneWidget);
    expect(find.text('56,000원'), findsOneWidget);
    expect(find.text('QR 사용하기'), findsOneWidget);
    expect(find.text('홈'), findsOneWidget);
    expect(tester.takeException(), isNull);

    final ticket = tester.getRect(find.byType(MealTicketCard));
    expect(ticket.left, 18);
    expect(ticket.right, 342);
    expect(ticket.height, 226);
  });

  testWidgets(
      'voucher ticket keeps long values and both actions clear at scale 1.3',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(1.3)),
        child: MaterialApp(
          home: Scaffold(
            body: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 18),
              child: MealTicketCard(
                remainingCountLabel: '100',
                caption: '보유 식권',
                monthUsage: '12장 · 84,000원',
                onTapQr: () {},
                onBuyTicket: () {},
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('100'), findsOneWidget);
    expect(find.text('장'), findsOneWidget);
    expect(find.text('12장 · 84,000원'), findsOneWidget);
    expect(find.text('식권 구매'), findsOneWidget);
    expect(find.text('QR 사용하기'), findsOneWidget);
    expect(tester.takeException(), isNull);

    final number =
        tester.getRect(find.byKey(const ValueKey('ticket-balance-number')));
    final unit =
        tester.getRect(find.byKey(const ValueKey('ticket-balance-unit')));
    final buy = tester.getRect(find.byKey(const ValueKey('buy-ticket-button')));
    final usage =
        tester.getRect(find.byKey(const ValueKey('ticket-month-usage')));
    final qr =
        tester.getRect(find.byKey(const ValueKey('use-ticket-qr-button')));
    expect((number.bottom - unit.bottom).abs(), lessThan(8));
    expect(number.right, lessThan(buy.left));
    expect(usage.right, lessThan(qr.left));
  });

  testWidgets(
      'voucher home uses complete server month totals and shows purchase',
      (tester) async {
    await pumpDashboard(tester, data: <String, dynamic>{
      'display_name': '식권 사용자',
      'role': 'customer',
      'account_type': 'voucher',
      'voucher_balance': 100,
      'voucher_month_used_count': 25,
      'voucher_month_used_amount': 175000,
      'voucher_use_history': const [],
    });

    expect(find.text('100'), findsOneWidget);
    expect(find.text('25장 · 175,000원'), findsOneWidget);
    expect(find.byKey(const ValueKey('buy-ticket-button')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('floating navigation opens all four real-data tabs',
      (tester) async {
    await pumpDashboard(tester);

    await tester.tap(find.text('이용내역'));
    await tester.pumpAndSettle();
    expect(find.text('2026년 8월'), findsOneWidget);

    await tester.tap(find.text('장부'));
    await tester.pumpAndSettle();
    expect(find.text('8월 미정산 금액'), findsOneWidget);

    await tester.tap(find.text('내정보'));
    await tester.pumpAndSettle();
    expect(find.text('휴대폰 번호'), findsOneWidget);
    expect(find.text('회사 장부'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
