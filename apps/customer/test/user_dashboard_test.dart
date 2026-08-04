import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/screens/user_dashboard_shell.dart';
import 'package:greeneatgo_customer/widgets/dashboard_components.dart';

ThemeData _appButtonTheme() => ThemeData(
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size.fromHeight(54),
        ),
      ),
    );

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
      {Map<String, dynamic>? data,
      Future<void> Function()? onBuyVoucher,
      Future<void> Function()? onScanQr,
      Future<void> Function()? onCoupons,
      Future<void> Function()? onEvents,
      Future<void> Function()? onOpenSettings,
      Future<void> Function()? onOpenInviteCode,
      DashboardPageBuilder? purchasePageBuilder,
      DashboardPageBuilder? qrPageBuilder,
      int? couponCount,
      int? pointBalance}) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(1.3)),
        child: MaterialApp(
          theme: _appButtonTheme(),
          home: UserDashboardShell(
            data: data ?? fixture,
            onRefresh: () async {},
            onScanQr: onScanQr ?? () async {},
            onBuyVoucher: onBuyVoucher ?? () async {},
            onCoupons: onCoupons ?? () async {},
            onEvents: onEvents ?? () async {},
            onOpenSettings: onOpenSettings ?? () async {},
            onOpenInviteCode: onOpenInviteCode ?? () async {},
            onAnnouncements: () async {},
            onReviews: () async {},
            onTerms: () async {},
            onPrivacy: () async {},
            onSignOut: () async {},
            pendingBanner: null,
            todayMenuCard: const Card(child: Text('오늘의 뷔페 메뉴')),
            purchasePageBuilder: purchasePageBuilder,
            qrPageBuilder: qrPageBuilder,
            couponCountFuture:
                couponCount == null ? null : Future<int>.value(couponCount),
            pointBalance: pointBalance,
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
    expect(find.byIcon(Icons.notifications_none_rounded), findsNothing);
    expect(find.text('쿠폰함'), findsOneWidget);
    expect(find.text('이벤트'), findsOneWidget);
    expect(find.text('공지사항'), findsOneWidget);
    expect(find.text('리뷰'), findsOneWidget);
    expect(tester.takeException(), isNull);

    final ticket = tester.getRect(find.byType(MealTicketCard));
    expect(ticket.left, 18);
    expect(ticket.right, 342);
    expect(ticket.height, 226);
    final usageLabel = tester.getRect(find.text('이번 달 사용'));
    final qrButton =
        tester.getRect(find.byKey(const ValueKey('use-ticket-qr-button')));
    expect(usageLabel.width, greaterThan(50));
    expect(qrButton.right, lessThanOrEqualTo(ticket.right));
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
          theme: _appButtonTheme(),
          home: Scaffold(
            body: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 18),
              child: MealTicketCard(
                remainingCountLabel: '100',
                couponCountLabel: '3',
                pointBalanceLabel: '1,200P',
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
    expect(find.text('보유 쿠폰'), findsOneWidget);
    expect(find.text('3장'), findsOneWidget);
    expect(find.text('보유 포인트'), findsOneWidget);
    expect(find.text('1,200P'), findsOneWidget);
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
    final ticket = tester.getRect(find.byType(MealTicketCard));
    final coupon =
        tester.getRect(find.byKey(const ValueKey('ticket-coupon-count')));
    final points =
        tester.getRect(find.byKey(const ValueKey('ticket-point-balance')));
    final numberWidget = tester
        .widget<Text>(find.byKey(const ValueKey('ticket-balance-number')));
    expect((number.bottom - unit.bottom).abs(), lessThan(8));
    expect(numberWidget.style?.fontSize, 25);
    expect(number.top, lessThan(coupon.top));
    expect(coupon.right, lessThan(points.left));
    expect(buy.width, qr.width);
    expect(buy.height, qr.height);
    expect(buy.width, 140);
    expect(buy.height, 48);
    expect(buy.right, qr.right);
    expect(buy.right, lessThanOrEqualTo(ticket.right));
    expect(usage.width, greaterThan(100));
    expect(usage.right, lessThan(qr.left));
    expect(qr.right, lessThanOrEqualTo(ticket.right));
  });

  testWidgets('wallet values format points and keep nullable values as dashes',
      (tester) async {
    final voucherData = <String, dynamic>{
      'display_name': '식권 사용자',
      'role': 'customer',
      'account_type': 'voucher',
      'voucher_balance': 10,
      'voucher_use_history': const [],
    };
    await pumpDashboard(tester,
        data: voucherData, couponCount: 3, pointBalance: 1200);

    expect(find.text('3장'), findsOneWidget);
    expect(find.text('1,200P'), findsOneWidget);

    await pumpDashboard(tester, data: voucherData);
    expect(
      tester
          .widget<Text>(find.byKey(const ValueKey('ticket-coupon-count')))
          .data,
      '-',
    );
    expect(
      tester
          .widget<Text>(find.byKey(const ValueKey('ticket-point-balance')))
          .data,
      '-',
    );
    expect(tester.takeException(), isNull);
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

  testWidgets('five-item navigation invokes actions and preserves content tab',
      (tester) async {
    var buys = 0;
    var scans = 0;
    await pumpDashboard(tester,
        onBuyVoucher: () async => buys++, onScanQr: () async => scans++);

    expect(find.text('장부'), findsNothing);
    expect(find.text('홈'), findsOneWidget);
    expect(find.text('구매'), findsOneWidget);
    expect(find.text('QR'), findsOneWidget);
    expect(find.text('내역'), findsOneWidget);
    expect(find.text('내정보'), findsOneWidget);

    await tester.tap(find.text('내역'));
    await tester.pumpAndSettle();
    expect(find.text('2026년 8월'), findsOneWidget);

    await tester.tap(find.text('구매'));
    await tester.pumpAndSettle();
    expect(buys, 1);
    expect(find.text('2026년 8월'), findsOneWidget);

    await tester.tap(find.text('QR'));
    await tester.pumpAndSettle();
    expect(scans, 1);
    expect(find.text('2026년 8월'), findsOneWidget);

    await tester.tap(find.text('내정보'));
    await tester.pumpAndSettle();
    expect(find.text('휴대폰 번호'), findsOneWidget);
    expect(find.text('휴대폰'), findsOneWidget);
    expect(find.text('초대코드 입력'), findsOneWidget);
    expect(find.text('이메일'), findsNothing);
    expect(find.textContaining('비밀번호'), findsNothing);
    expect(find.text('회사 장부'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('purchase and QR pages stay inside the five-item navigation',
      (tester) async {
    await pumpDashboard(
      tester,
      purchasePageBuilder: (close) => Scaffold(
        appBar: AppBar(
          leading:
              IconButton(onPressed: close, icon: const Icon(Icons.arrow_back)),
        ),
        body: const Text('구매 탭 화면'),
      ),
      qrPageBuilder: (close) => Scaffold(
        appBar: AppBar(
          leading:
              IconButton(onPressed: close, icon: const Icon(Icons.arrow_back)),
        ),
        body: const Text('QR 탭 화면'),
      ),
    );

    await tester.tap(find.text('구매'));
    await tester.pumpAndSettle();
    expect(find.text('구매 탭 화면'), findsOneWidget);
    expect(find.text('홈'), findsOneWidget);
    expect(find.text('구매'), findsOneWidget);
    expect(find.text('QR'), findsOneWidget);

    await tester.tap(find.text('QR'));
    await tester.pumpAndSettle();
    expect(find.text('QR 탭 화면'), findsOneWidget);
    expect(find.text('홈'), findsOneWidget);
    expect(find.text('내역'), findsOneWidget);
    expect(find.text('내정보'), findsOneWidget);

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text('QR 탭 화면'), findsNothing);
    expect(find.byType(MealTicketCard), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('My Info invite row and payment alert use separate callbacks',
      (tester) async {
    var settingsOpens = 0;
    var inviteOpens = 0;
    await pumpDashboard(
      tester,
      onOpenSettings: () async => settingsOpens++,
      onOpenInviteCode: () async => inviteOpens++,
    );

    await tester.tap(find.text('내정보'));
    await tester.pumpAndSettle();
    expect(find.text('계정 설정'), findsNothing);
    expect(find.text('초대코드 입력'), findsOneWidget);

    await tester.tap(find.text('결제 알림'));
    await tester.pump();
    expect(settingsOpens, 1);
    expect(inviteOpens, 0);

    await tester.tap(find.text('초대코드 입력'));
    await tester.pump();
    expect(settingsOpens, 1);
    expect(inviteOpens, 1);
  });

  testWidgets('home shortcuts invoke coupon and event actions', (tester) async {
    var coupons = 0;
    var events = 0;
    await pumpDashboard(tester,
        onCoupons: () async => coupons++, onEvents: () async => events++);

    await tester.tap(find.text('쿠폰함'));
    await tester.tap(find.text('이벤트'));
    await tester.pump();
    expect(coupons, 1);
    expect(events, 1);
    expect(tester.takeException(), isNull);
  });

  testWidgets('purchase action ignores rapid duplicate taps', (tester) async {
    final gate = Completer<void>();
    var buys = 0;
    await pumpDashboard(tester, onBuyVoucher: () {
      buys++;
      return gate.future;
    });

    await tester.tap(find.text('구매'));
    await tester.pump();
    await tester.tap(find.text('구매'));
    await tester.pump();
    expect(buys, 1);

    gate.complete();
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}
