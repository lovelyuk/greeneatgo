import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/main.dart';
import 'package:greeneatgo_customer/theme/app_colors.dart';

void main() {
  setUpAll(() async {
    final loader = FontLoader('Pretendard')
      ..addFont(rootBundle.load('assets/fonts/Pretendard-Regular.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-SemiBold.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-Bold.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-ExtraBold.otf'));
    await loader.load();
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
