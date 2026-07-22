import 'package:flutter_test/flutter_test.dart';

import 'package:greeneatgo_customer/auth_helpers.dart';
import 'package:greeneatgo_customer/main.dart';

void main() {
  testWidgets('app shows missing environment guidance when not configured',
      (WidgetTester tester) async {
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
      'kiwoom_pay_method': 'BANK',
      'image_url': 'https://example.com/voucher.jpg',
    });

    expect(product.regularPrice, 80000);
    expect(product.saving, 8000);
    expect(product.totalCount, 11);
    expect(product.imageUrl, isNotNull);
    expect(product.kiwoomPayMethod, 'BANK');
  });

  test('event voucher exposes event flag and D-day label', () {
    final product = VoucherProduct.fromJson({
      'id': 'event-voucher',
      'name': '여름 이벤트',
      'voucher_count': 10,
      'bonus_count': 0,
      'unit_price': 8000,
      'discount_rate': 10,
      'sale_price': 72000,
      'total_count': 10,
      'is_event': true,
      'event_end_at': '2026-07-13T23:59:59',
    });

    expect(product.isEvent, isTrue);
    expect(product.eventEndAt, isNotNull);
    expect(product.eventDdayAt(DateTime(2026, 7, 10, 12)), 'D-3');
    expect(product.eventDdayAt(DateTime(2026, 7, 13, 8)), 'D-DAY');
  });

  test('API exception retains status and no-voucher reason', () {
    const error = ApiException(
        statusCode: 402, reason: 'no_voucher', message: '보유 식권이 없습니다');

    expect(error.statusCode, 402);
    expect(error.reason, 'no_voucher');
    expect(error.isNoVoucher, isTrue);
    expect(error.toString(), '보유 식권이 없습니다');
  });

  test('Firebase auth error codes have safe Korean messages', () {
    expect(friendlyFirebaseAuthCode('invalid-credential'),
        '이메일 또는 비밀번호가 올바르지 않아요.');
    expect(friendlyFirebaseAuthCode('email-already-in-use'),
        contains('이미 가입된 이메일'));
    expect(
        friendlyFirebaseAuthCode('too-many-requests'), contains('요청이 너무 많아요'));
    expect(
        friendlyFirebaseAuthCode('network-request-failed'), contains('네트워크'));
    expect(friendlyFirebaseAuthCode('unknown-code'), contains('잠시 후'));
  });

  test('password reset only exposes operational failures', () {
    expect(isOperationalPasswordResetError('network-request-failed'), isTrue);
    expect(isOperationalPasswordResetError('too-many-requests'), isTrue);
    expect(isOperationalPasswordResetError('quota-exceeded'), isTrue);
    expect(isOperationalPasswordResetError('user-not-found'), isFalse);
    expect(isOperationalPasswordResetError('user-disabled'), isFalse);
    expect(isOperationalPasswordResetError('invalid-credential'), isFalse);
    expect(isOperationalPasswordResetError('unknown-code'), isFalse);
  });

  test('email and phone helpers normalize and validate input', () {
    expect(isValidEmail(' employee@example.com '), isTrue);
    expect(isValidEmail('not-an-email'), isFalse);
    expect(normalizeEmployeePhone('010-1234 5678'), '01012345678');
  });
}
