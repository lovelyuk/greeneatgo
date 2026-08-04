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

  testWidgets('voucher purchase list renders at 360px', (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    const products = [
      VoucherProduct(
        id: 'single',
        name: '돈토식권',
        voucherCount: 1,
        bonusCount: 0,
        unitPrice: 8000,
        discountRate: 0,
        salePrice: 8000,
        totalCount: 1,
        kiwoomPayMethod: 'TOTAL',
        isEvent: false,
      ),
      VoucherProduct(
        id: 'ten-plus-one',
        name: '돈토식권 10장권',
        voucherCount: 10,
        bonusCount: 1,
        unitPrice: 8000,
        discountRate: 0,
        salePrice: 80000,
        totalCount: 11,
        kiwoomPayMethod: 'BANK',
        isEvent: false,
      ),
    ];

    await tester.pumpWidget(
      const MaterialApp(
        debugShowCheckedModeBanner: false,
        home: _VoucherListCapture(products: products),
      ),
    );
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.text('판매 중인 식권'), findsNothing);
    expect(find.text('2종'), findsOneWidget);
    expect(find.textContaining('보너스 0장'), findsNothing);
    expect(find.textContaining('보너스 1장'), findsOneWidget);
    await expectLater(
      find.byKey(const Key('voucher-list-capture')),
      matchesGoldenFile('goldens/voucher_purchase_360.png'),
    );
  });

  testWidgets('event entry shows only event vouchers at 360px', (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    const catalog = VoucherCatalog(
      purchaseMode: VoucherPurchaseMode.voucher,
      items: [
        VoucherProduct(
          id: 'standard',
          name: '일반 식권',
          voucherCount: 1,
          bonusCount: 0,
          unitPrice: 8000,
          discountRate: 0,
          salePrice: 8000,
          totalCount: 1,
          kiwoomPayMethod: 'TOTAL',
          isEvent: false,
        ),
        VoucherProduct(
          id: 'event',
          name: '여름 보너스 이벤트',
          voucherCount: 10,
          bonusCount: 2,
          unitPrice: 8000,
          discountRate: 0,
          salePrice: 80000,
          totalCount: 12,
          kiwoomPayMethod: 'BANK',
          isEvent: true,
        ),
      ],
    );

    await tester.pumpWidget(const MaterialApp(
      debugShowCheckedModeBanner: false,
      home: _VoucherEventCapture(catalog: catalog),
    ));
    await tester.pumpAndSettle();

    expect(find.text('이벤트'), findsOneWidget);
    expect(find.text('일반 식권'), findsNothing);
    expect(find.text('여름 보너스 이벤트'), findsOneWidget);
    expect(find.text('1종'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await expectLater(
      find.byKey(const Key('voucher-event-capture')),
      matchesGoldenFile('goldens/voucher_event_360.png'),
    );
  });

  testWidgets('voucher purchase page keeps dashboard navigation at 360px',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    const catalog = VoucherCatalog(
      purchaseMode: VoucherPurchaseMode.voucher,
      items: [
        VoucherProduct(
          id: 'single',
          name: '돈토식권',
          voucherCount: 1,
          bonusCount: 0,
          unitPrice: 8000,
          discountRate: 0,
          salePrice: 8000,
          totalCount: 1,
          kiwoomPayMethod: 'TOTAL',
          isEvent: false,
        ),
      ],
    );

    await tester.pumpWidget(MaterialApp(
      debugShowCheckedModeBanner: false,
      home: RepaintBoundary(
        key: const Key('voucher-nav-capture'),
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
          purchasePageBuilder: (close) => Scaffold(
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
              title: const Text('식권 구매'),
            ),
            body: VoucherPurchaseContent(
              catalog: catalog,
              filter: VoucherFilter.all,
              onProduct: (_) {},
              onShowAll: () {},
            ),
          ),
          qrPageBuilder: (close) => const SizedBox.shrink(),
        ),
      ),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.text('구매'));
    await tester.pumpAndSettle();

    expect(find.text('식권 구매'), findsOneWidget);
    expect(find.text('돈토식권'), findsOneWidget);
    expect(find.text('홈'), findsOneWidget);
    expect(find.text('QR'), findsOneWidget);
    expect(find.text('내역'), findsOneWidget);
    expect(find.text('내정보'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await expectLater(
      find.byKey(const Key('voucher-nav-capture')),
      matchesGoldenFile('goldens/voucher_purchase_nav_360.png'),
    );
  });

  testWidgets('event entry has an empty state and opens all products',
      (tester) async {
    const catalog = VoucherCatalog(
      purchaseMode: VoucherPurchaseMode.voucher,
      items: [
        VoucherProduct(
          id: 'standard',
          name: '일반 식권',
          voucherCount: 1,
          bonusCount: 0,
          unitPrice: 8000,
          discountRate: 0,
          salePrice: 8000,
          totalCount: 1,
          kiwoomPayMethod: 'TOTAL',
          isEvent: false,
        ),
      ],
    );

    await tester.pumpWidget(
      const MaterialApp(home: _VoucherFilterHarness(catalog: catalog)),
    );
    await tester.pumpAndSettle();

    expect(find.text('이벤트'), findsOneWidget);
    expect(find.text('현재 진행 중인 이벤트가 없어요.'), findsOneWidget);
    expect(find.text('전체 상품 보기'), findsOneWidget);
    expect(find.text('일반 식권'), findsNothing);
    await tester.tap(find.text('전체 상품 보기'));
    await tester.pumpAndSettle();
    expect(find.text('이벤트'), findsNothing);
    expect(find.text('식권 구매'), findsOneWidget);
    expect(find.text('일반 식권'), findsOneWidget);
    expect(find.text('1종'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

class _VoucherFilterHarness extends StatefulWidget {
  const _VoucherFilterHarness({required this.catalog});

  final VoucherCatalog catalog;

  @override
  State<_VoucherFilterHarness> createState() => _VoucherFilterHarnessState();
}

class _VoucherFilterHarnessState extends State<_VoucherFilterHarness> {
  VoucherFilter filter = VoucherFilter.event;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(voucherFilterTitle(filter))),
        body: VoucherPurchaseContent(
          catalog: widget.catalog,
          filter: filter,
          onProduct: (_) {},
          onShowAll: () => setState(() => filter = VoucherFilter.all),
        ),
      );
}

class _VoucherEventCapture extends StatelessWidget {
  const _VoucherEventCapture({required this.catalog});

  final VoucherCatalog catalog;

  @override
  Widget build(BuildContext context) => Theme(
        data: Theme.of(context).copyWith(
          scaffoldBackgroundColor: AppColors.bg,
          textTheme: Theme.of(context).textTheme.apply(
                fontFamily: 'Pretendard',
                bodyColor: AppColors.fg,
                displayColor: AppColors.fg,
              ),
          appBarTheme: const AppBarTheme(
            backgroundColor: AppColors.bg,
            foregroundColor: AppColors.fg,
            surfaceTintColor: AppColors.bg,
          ),
        ),
        child: RepaintBoundary(
          key: const Key('voucher-event-capture'),
          child: Scaffold(
            backgroundColor: AppColors.bg,
            appBar: AppBar(title: const Text('이벤트')),
            body: VoucherPurchaseContent(
              catalog: catalog,
              filter: VoucherFilter.event,
              onProduct: (_) {},
              onShowAll: () {},
            ),
          ),
        ),
      );
}

class _VoucherListCapture extends StatelessWidget {
  const _VoucherListCapture({required this.products});

  final List<VoucherProduct> products;

  @override
  Widget build(BuildContext context) => Theme(
        data: Theme.of(context).copyWith(
          scaffoldBackgroundColor: AppColors.bg,
          textTheme: Theme.of(context).textTheme.apply(
                fontFamily: 'Pretendard',
                bodyColor: AppColors.fg,
                displayColor: AppColors.fg,
              ),
          appBarTheme: const AppBarTheme(
            backgroundColor: AppColors.bg,
            foregroundColor: AppColors.fg,
            surfaceTintColor: AppColors.bg,
          ),
        ),
        child: RepaintBoundary(
          key: const Key('voucher-list-capture'),
          child: Scaffold(
            backgroundColor: AppColors.bg,
            appBar: AppBar(title: const Text('식권 구매')),
            body: VoucherCatalogList(
              catalog: VoucherCatalog(
                purchaseMode: VoucherPurchaseMode.voucher,
                items: products,
              ),
              onProduct: (_) {},
            ),
          ),
        ),
      );
}
