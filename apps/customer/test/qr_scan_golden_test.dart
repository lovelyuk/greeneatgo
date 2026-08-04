import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/main.dart';
import 'package:greeneatgo_customer/screens/user_dashboard_shell.dart';
import 'package:greeneatgo_customer/theme/app_colors.dart';

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

  testWidgets('QR page matches dashboard and keeps bottom navigation at 360px',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(1.2)),
        child: MaterialApp(
          debugShowCheckedModeBanner: false,
          home: RepaintBoundary(
            key: const Key('qr-page-capture'),
            child: UserDashboardShell(
              data: const {
                'display_name': '이용자',
                'role': 'customer',
                'account_type': 'voucher',
                'voucher_balance': 3,
                'recent_transactions': [],
              },
              onRefresh: () async {},
              onScanQr: () async {},
              onBuyVoucher: () async {},
              onCoupons: () async {},
              onEvents: () async {},
              onOpenSettings: () async {},
              onOpenInviteCode: () async {},
              onAnnouncements: () async {},
              onReviews: () async {},
              onTerms: () async {},
              onPrivacy: () async {},
              onSignOut: () async {},
              pendingBanner: null,
              purchasePageBuilder: (close) => const SizedBox.shrink(),
              qrPageBuilder: (close) => Scaffold(
                backgroundColor: AppColors.bg,
                appBar: AppBar(
                  backgroundColor: AppColors.bg,
                  foregroundColor: AppColors.fg,
                  surfaceTintColor: AppColors.bg,
                  leading: IconButton(
                    tooltip: '홈으로',
                    onPressed: close,
                    icon: const Icon(Icons.arrow_back_rounded),
                  ),
                  title: const Text('QR 사용하기'),
                ),
                body: UnifiedQrScanContent(
                  isConsumer: true,
                  onRetry: () {},
                  scanner: const _FakeScanner(),
                ),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('QR'));
    await tester.pumpAndSettle();

    expect(find.text('QR 사용하기'), findsOneWidget);
    expect(find.text('매장 QR을 스캔해요'), findsOneWidget);
    expect(find.text('보유 식권 1장이 사용됩니다.'), findsOneWidget);
    expect(find.text('홈'), findsOneWidget);
    expect(find.text('구매'), findsOneWidget);
    expect(find.text('QR'), findsOneWidget);
    expect(find.text('내역'), findsOneWidget);
    expect(find.text('내정보'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await expectLater(
      find.byKey(const Key('qr-page-capture')),
      matchesGoldenFile('goldens/qr_scan_dashboard_360.png'),
    );
  });
}

class _FakeScanner extends StatelessWidget {
  const _FakeScanner();

  @override
  Widget build(BuildContext context) => ColoredBox(
        color: Colors.black,
        child: Center(
          child: Container(
            width: 220,
            height: 220,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              border: Border.all(color: AppColors.blue, width: 7),
              borderRadius: BorderRadius.circular(14),
            ),
            child: const Icon(
              Icons.qr_code_scanner_rounded,
              color: AppColors.fg2,
              size: 64,
            ),
          ),
        ),
      );
}
