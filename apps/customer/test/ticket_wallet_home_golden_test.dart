import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/screens/user_dashboard_shell.dart';

void main() {
  setUpAll(() async {
    final loader = FontLoader('Pretendard')
      ..addFont(rootBundle.load('assets/fonts/Pretendard-Regular.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-SemiBold.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-Bold.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-ExtraBold.otf'));
    await loader.load();
    final icons = FontLoader('MaterialIcons')
      ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await icons.load();
  });

  testWidgets('ticket wallet card renders at 360x640 and text scale 1.3',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(1.3)),
        child: MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: ThemeData(
            filledButtonTheme: FilledButtonThemeData(
              style: FilledButton.styleFrom(
                minimumSize: const Size.fromHeight(54),
              ),
            ),
          ),
          home: RepaintBoundary(
            key: const Key('ticket-wallet-home-capture'),
            child: UserDashboardShell(
              data: const {
                'display_name': '이용욱',
                'role': 'customer',
                'account_type': 'voucher',
                'voucher_balance': 10,
                'voucher_month_used_count': 0,
                'voucher_month_used_amount': 0,
                'voucher_use_history': [],
              },
              couponCountFuture: Future<int>.value(3),
              pointBalance: 1200,
              onRefresh: () async {},
              onScanQr: () async {},
              onBuyVoucher: () async {},
              onCoupons: () async {},
              onEvents: () async {},
              onOpenSettings: () async {},
              onAnnouncements: () async {},
              onReviews: () async {},
              onTerms: () async {},
              onPrivacy: () async {},
              onSignOut: () async {},
              pendingBanner: null,
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('10'), findsOneWidget);
    expect(find.text('3장'), findsOneWidget);
    expect(find.text('1,200P'), findsOneWidget);
    expect(find.text('식권 구매'), findsOneWidget);
    expect(find.text('QR 사용하기'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await expectLater(
      find.byKey(const Key('ticket-wallet-home-capture')),
      matchesGoldenFile('goldens/ticket_wallet_home_360.png'),
    );
  });
}
