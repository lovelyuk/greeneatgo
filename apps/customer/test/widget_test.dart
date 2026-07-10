import 'package:flutter_test/flutter_test.dart';

import 'package:greeneatgo_customer/main.dart';

void main() {
  testWidgets('app shows missing environment guidance when not configured', (WidgetTester tester) async {
    await tester.pumpWidget(const GreeneatGoApp());
    await tester.pump();

    expect(find.text('잠깐, 문제가 생겼어요'), findsOneWidget);
    expect(find.textContaining('앱 환경값이 누락됐어요'), findsOneWidget);
  });

  test('voucher product exposes package totals and savings', () {
    final product = VoucherProduct.fromJson({
      'id': 'voucher-10',
      'name': '식권 10+1',
      'voucher_count': 10,
      'bonus_count': 1,
      'unit_price': 8000,
      'discount_rate': 10,
      'sale_price': 72000,
      'total_count': 11,
      'image_url': 'https://example.com/voucher.jpg',
    });

    expect(product.regularPrice, 80000);
    expect(product.saving, 8000);
    expect(product.totalCount, 11);
    expect(product.imageUrl, isNotNull);
  });

  test('API exception retains status and no-voucher reason', () {
    const error = ApiException(statusCode: 402, reason: 'no_voucher', message: '보유 식권이 없습니다');

    expect(error.statusCode, 402);
    expect(error.reason, 'no_voucher');
    expect(error.isNoVoucher, isTrue);
    expect(error.toString(), '보유 식권이 없습니다');
  });
}
