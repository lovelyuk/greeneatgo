import 'package:flutter/material.dart';
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

  test('subsidized 10+1 catalog uses server-provided prices and mode', () {
    final catalog = VoucherCatalog.fromJson({
      'purchase_mode': 'subsidized',
      'items': [
        {
          'id': 'subsidized-10-plus-1',
          'name': '지원 식권 10+1',
          'voucher_count': 10,
          'bonus_count': 1,
          'unit_price': 8000,
          'discount_rate': 0,
          'sale_price': 80000,
          'total_count': 11,
          'employee_pay_amount': 50000,
          'per_voucher_company_subsidy_amount': 2000,
          'per_voucher_restaurant_subsidy_amount': 1000,
          'total_company_subsidy_amount': 20000,
          'total_restaurant_subsidy_amount': 10000,
          'kiwoom_pay_method': 'bank',
        }
      ],
    });

    expect(catalog.purchaseMode, VoucherPurchaseMode.subsidized);
    expect(catalog.items, hasLength(1));
    final product = catalog.items.single;
    expect(product.voucherCount, 10);
    expect(product.bonusCount, 1);
    expect(product.totalCount, 11);
    expect(product.salePrice, 80000);
    expect(product.employeePayAmount, 50000);
    expect(product.companySubsidyAmount, 2000);
    expect(product.restaurantSubsidyAmount, 1000);
    expect(product.totalCompanySubsidyAmount, 20000);
    expect(product.totalRestaurantSubsidyAmount, 10000);
    expect(product.kiwoomPayMethod, 'BANK');
  });

  test('none purchase mode never exposes products', () {
    final catalog = VoucherCatalog.fromJson({
      'purchase_mode': 'none',
      'items': [
        {
          'id': 'must-not-be-exposed',
          'name': '숨겨진 상품',
        }
      ],
    });

    expect(catalog.purchaseMode, VoucherPurchaseMode.none);
    expect(catalog.items, isEmpty);
  });

  test('subsidized reservation release policy protects settling payments', () {
    bool release({
      bool subsidized = true,
      bool hasOrder = true,
      bool completed = false,
      bool attempted = false,
      bool external = false,
      bool approval = false,
      bool checkoutStarted = false,
      bool explicit = false,
    }) =>
        shouldReleaseSubsidizedReservation(
          isSubsidized: subsidized,
          hasOrder: hasOrder,
          completed: completed,
          cancellationAttempted: attempted,
          externalPaymentActive: external,
          approvalPending: approval,
          checkoutStarted: checkoutStarted,
          explicitCheckoutTermination: explicit,
        );

    expect(release(), isTrue, reason: 'plain screen abandonment releases');
    expect(release(subsidized: false), isFalse,
        reason: 'ordinary voucher orders are untouched');
    expect(release(completed: true), isFalse);
    expect(release(attempted: true), isFalse);
    expect(release(external: true), isFalse,
        reason: 'an external payment app may still settle');
    expect(release(approval: true), isFalse,
        reason: 'an uncertain confirmation may still settle');
    expect(release(checkoutStarted: true), isFalse,
        reason: 'disposing a presented provider checkout is conservative');
    expect(release(external: true, approval: true, explicit: true), isTrue,
        reason: 'provider fail/cancel/close is authoritative');
  });

  testWidgets('subsidized product card shows server totals and BANK mode',
      (tester) async {
    final product = VoucherCatalog.fromJson({
      'purchase_mode': 'subsidized',
      'items': [
        {
          'id': 'subsidized-10-plus-1',
          'name': '지원 식권 10+1',
          'voucher_count': 10,
          'bonus_count': 1,
          'unit_price': 8000,
          'discount_rate': 0,
          'sale_price': 80000,
          'total_count': 11,
          'employee_pay_amount': 50000,
          'per_voucher_company_subsidy_amount': 2000,
          'per_voucher_restaurant_subsidy_amount': 1000,
          'total_company_subsidy_amount': 20000,
          'total_restaurant_subsidy_amount': 10000,
          'kiwoom_pay_method': 'BANK',
        }
      ],
    }).items.single;

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: VoucherProductCard(
            product: product,
            purchaseMode: VoucherPurchaseMode.subsidized,
            onBuy: () {},
          ),
        ),
      ),
    ));

    expect(find.text('10장 + 보너스 1장 · 총 11장 지급'), findsOneWidget);
    expect(find.text('정상 판매가 80,000원'), findsOneWidget);
    expect(find.text('회사 총 지원 20,000원'), findsOneWidget);
    expect(find.text('식당 총 지원 10,000원'), findsOneWidget);
    expect(find.text('직원 부담 50,000원'), findsOneWidget);
    expect(find.text('BANK · 계좌이체 전용'), findsOneWidget);
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

  test('pending sign-up profile key and JSON contain only reusable fields', () {
    expect(pendingSignupProfileKey(' Employee@Example.COM '),
        'pending_signup_profile:employee@example.com');

    const profile = PendingSignupProfile(
        uid: 'firebase-user-1', displayName: ' 홍길동 ', phone: '010-1234 5678');
    final serialized = profile.toJson();
    final restored = PendingSignupProfile.fromJson(serialized);

    expect(serialized, contains('firebase-user-1'));
    expect(serialized, contains('display_name'));
    expect(serialized, contains('phone'));
    expect(serialized, isNot(contains('password')));
    expect(serialized, isNot(contains('token')));
    expect(restored?.uid, 'firebase-user-1');
    expect(restored?.displayName, '홍길동');
    expect(restored?.phone, '01012345678');
    expect(PendingSignupProfile.fromJson('{"phone":"invalid"}'), isNull);
  });

  test(
      'profile fallback prefers trusted account data and permits phone recovery',
      () {
    expect(
        signupDisplayName(
          sessionDisplayName: ' Firebase 이름 ',
          meDisplayName: 'API 이름',
          pendingDisplayName: '기기 이름',
        ),
        'Firebase 이름');
    expect(
        signupDisplayName(
          sessionDisplayName: ' ',
          meDisplayName: ' API 이름 ',
          pendingDisplayName: '기기 이름',
        ),
        'API 이름');
    expect(signupDisplayName(pendingDisplayName: ' 기기 이름 '), '기기 이름');

    final missingPhone = PendingSignupProfile.fromJson(
        '{"uid":"firebase-user-1","display_name":"홍길동","phone":"corrupt"}');
    expect(missingPhone?.displayName, '홍길동');
    expect(isValidSignupPhone(missingPhone?.phone ?? ''), isFalse);
    expect(isValidSignupPhone('010-1234 5678'), isTrue);
    expect(normalizeSignupPhone('010-1234 5678'), '01012345678');
  });
}
