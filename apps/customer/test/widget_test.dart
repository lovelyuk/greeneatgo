import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:greeneatgo_customer/auth_helpers.dart';
import 'package:greeneatgo_customer/main.dart';
import 'package:greeneatgo_customer/payment_completion.dart';
import 'package:greeneatgo_customer/theme/app_colors.dart';

void main() {
  test('daily menu client uses the server primary merchant endpoint', () async {
    Uri? requestedUri;
    final client = MockClient((request) async {
      requestedUri = request.url;
      return http.Response(
        jsonEncode({
          'ok': true,
          'data': {
            'today_menu': {
              'title': '오늘 뷔페 메뉴',
              'menu_text': '돼지김치찌개',
              'image_url': null,
            },
          },
          'error': null,
        }),
        200,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
    });

    final menu = await DailyMenuClient(client: client).getTodayMenu();

    expect(requestedUri?.path, '/daily-menu');
    expect(menu?.menuText, '돼지김치찌개');
  });

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

  testWidgets('purchase list ticket fits at 360 and uses server values',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
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

    var purchased = false;
    await tester.pumpWidget(MediaQuery(
      data: const MediaQueryData(textScaler: TextScaler.linear(1.3)),
      child: MaterialApp(
        home: Scaffold(
          backgroundColor: AppColors.bg,
          body: VoucherProductCard(
            product: product,
            purchaseMode: VoucherPurchaseMode.subsidized,
            onBuy: () => purchased = true,
          ),
        ),
      ),
    ));

    expect(find.text('11장 식권'), findsOneWidget);
    expect(find.text('50,000원'), findsOneWidget);
    expect(find.text('결제방법  계좌이체 전용  ·  보너스 1장'), findsOneWidget);
    expect(find.textContaining('유효'), findsNothing);
    expect(find.textContaining('90일'), findsNothing);
    expect(find.byKey(const Key('product-thumbnail')), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.tap(find.byType(VoucherProductCard));
    expect(purchased, isTrue);
  });

  testWidgets('product detail is multiline-safe with fixed blue purchase bar',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    const product = VoucherProduct(
      id: 'event-product',
      name: '회사를 위한 아주 긴 이름의 특별 식권 패키지',
      voucherCount: 20,
      bonusCount: 3,
      unitPrice: 8000,
      discountRate: 12,
      salePrice: 140000,
      totalCount: 23,
      kiwoomPayMethod: 'BANK',
      isEvent: true,
      totalCompanySubsidyAmount: 30000,
      totalRestaurantSubsidyAmount: 10000,
    );
    await tester.pumpWidget(MediaQuery(
      data: const MediaQueryData(textScaler: TextScaler.linear(1.3)),
      child: MaterialApp(
        home: VoucherProductDetailScreen(
          product: product,
          purchaseMode: VoucherPurchaseMode.voucher,
          onBuy: () async {},
        ),
      ),
    ));

    expect(find.byKey(const Key('product-detail-ticket')), findsOneWidget);
    expect(find.text('식권 구성'), findsOneWidget);
    expect(find.text('정보'), findsOneWidget);
    expect(find.text('상품 할인'), findsOneWidget);
    expect(find.text('-20,000원'), findsOneWidget);
    expect(find.text('회사 지원'), findsOneWidget);
    expect(find.text('30,000원'), findsOneWidget);
    expect(find.text('식당 지원'), findsOneWidget);
    expect(find.text('10,000원'), findsOneWidget);
    expect(find.text('사용처'), findsNothing,
        reason: 'catalog API does not supply an authoritative merchant name');
    expect(find.textContaining('유효'), findsNothing);
    expect(find.textContaining('90일'), findsNothing);
    final button =
        tester.widget<FilledButton>(find.byKey(const Key('detail-buy-button')));
    expect(button.style?.backgroundColor?.resolve({}), AppColors.blue);
    expect(tester.takeException(), isNull);
  });

  testWidgets('CARD completion shows only the card sales slip', (tester) async {
    final payment = PaymentCompletionData.fromConfirmDto({
      'data': {
        'amount': 72000,
        'payment': {
          'method': 'CARD',
          'method_label': '신용카드',
          'approved_at': '2026-07-27T13:14:15',
          'transaction_id': 'CARD-TRX-1',
          'issuer_name': '그린카드',
          'masked_card_number': '1234-****-****-5678',
          'authorization_number': '12345678',
          'cash_receipt_status': 'ISSUED',
        },
        'receipts': {
          'sales_slip_url': 'https://example.com/card-slip',
          'cash_receipt_url': 'https://example.com/invalid-card-cash',
        },
      },
    });

    await tester.pumpWidget(MaterialApp(
      theme: ThemeData(colorSchemeSeed: kOrange),
      home: PaymentCompletionScreen(payment: payment, onDone: () {}),
    ));

    expect(find.text('결제 완료'), findsOneWidget);
    expect(find.text('결제가 완료되었습니다'), findsOneWidget);
    expect(find.text('72,000원'), findsOneWidget);
    expect(find.text('신용카드'), findsOneWidget);
    expect(find.text('그린카드 1234-****-****-5678'), findsOneWidget);
    expect(find.text('카드 매출전표 보기'), findsOneWidget);
    expect(find.text('계좌이체 전표 보기'), findsNothing);
    expect(find.text('현금영수증 보기'), findsNothing,
        reason: 'CARD must never expose a cash receipt');
    expect(find.byType(BackButton), findsNothing);
  });

  test('CARD completion hides a previously corrupted issuer prefix', () {
    final payment = PaymentCompletionData.fromConfirmDto({
      'data': {
        'amount': 72000,
        'payment': {
          'method': 'CARD',
          'issuer_name': '\ufffd\ufffd\ufffd\ufffd카드',
          'masked_card_number': '****-****-****-5678',
        },
      },
    });

    expect(payment.accountValue, '****-****-****-5678');
    expect(payment.accountValue, isNot(contains('\ufffd')));
  });

  test('voucher purchase completion refreshes only after successful payment',
      () async {
    var refreshCount = 0;
    Future<void> refresh() async => refreshCount++;

    await notifyVoucherPurchaseCompleted(false, refresh);
    await notifyVoucherPurchaseCompleted(null, refresh);
    expect(refreshCount, 0);

    await notifyVoucherPurchaseCompleted(true, refresh);
    expect(refreshCount, 1);
  });

  testWidgets('NAVERPAY completion uses the card sales slip', (tester) async {
    final payment = PaymentCompletionData.fromConfirmDto({
      'data': {
        'amount': 8000,
        'payment': {
          'method': 'NAVERPAY',
          'method_label': '네이버페이',
          'issuer_name': '신한카드 - 체크',
          'masked_card_number': '****-****-****-8900',
          'cash_receipt_status': 'ISSUED',
        },
        'receipts': {
          'sales_slip_url': 'https://example.com/naver-card-slip',
          'cash_receipt_url': 'https://example.com/invalid-naver-cash',
        },
      },
    });

    await tester.pumpWidget(MaterialApp(
      home: PaymentCompletionScreen(payment: payment, onDone: () {}),
    ));

    expect(find.text('네이버페이'), findsOneWidget);
    expect(find.text('신한카드 - 체크 ****-****-****-8900'), findsOneWidget);
    expect(find.text('카드 매출전표 보기'), findsOneWidget);
    expect(find.text('계좌이체 전표 보기'), findsNothing);
    expect(find.text('현금영수증 보기'), findsNothing);
  });

  testWidgets('BANK completion shows transfer slip without cash receipt',
      (tester) async {
    final payment = PaymentCompletionData.fromConfirmDto({
      'data': {
        'amount': 50000,
        'payment': {
          'method': 'BANK',
          'method_label': '계좌이체',
          'approved_at': '2026-07-27T14:15:16',
          'transaction_id': 'BANK-TRX-1',
          'bank_name': '그린은행',
          'authorization_number': '87654321',
          'cash_receipt_status': 'NOT_ISSUED',
        },
        'receipts': {
          'sales_slip_url': 'https://example.com/bank-slip',
          'cash_receipt_url': 'https://example.com/unissued-cash',
        },
      },
    });

    await tester.pumpWidget(MaterialApp(
      home: PaymentCompletionScreen(payment: payment, onDone: () {}),
    ));

    expect(find.text('50,000원'), findsOneWidget);
    expect(find.text('이용은행'), findsOneWidget);
    expect(find.text('그린은행'), findsOneWidget);
    expect(find.text('계좌이체 전표 보기'), findsOneWidget);
    expect(find.text('카드 매출전표 보기'), findsNothing);
    expect(find.text('현금영수증 보기'), findsNothing);
  });

  testWidgets('BANK completion exposes issued cash receipt with URL',
      (tester) async {
    final payment = PaymentCompletionData.fromConfirmDto({
      'data': {
        'amount': 80000,
        'payment': {
          'method': 'bank',
          'method_label': '실시간 계좌이체',
          'approved_at': '2026-07-27T15:16:17',
          'transaction_id': 'BANK-TRX-2',
          'bank_name': '푸른은행',
          'authorization_number': '11223344',
          'cash_receipt_authorization_number': 'CASH-9988',
          'cash_receipt_status': 'issued',
        },
        'receipts': {
          'sales_slip_url': 'https://example.com/bank-slip-2',
          'cash_receipt_url': 'https://example.com/cash-receipt',
        },
      },
    });

    await tester.pumpWidget(MaterialApp(
      home: PaymentCompletionScreen(payment: payment, onDone: () {}),
    ));

    expect(payment.cashReceiptAuthorizationNumber, 'CASH-9988');
    expect(find.text('계좌이체 전표 보기'), findsOneWidget);
    expect(find.text('현금영수증 보기'), findsOneWidget);
    expect(find.text('BANK-TRX-2'), findsOneWidget);
    expect(find.text('2026.07.27 15:16:17'), findsOneWidget);
  });

  testWidgets('completion remains overflow-free at 360x640 and text scale 1.2',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final payment = PaymentCompletionData.fromConfirmDto({
      'amount': 80000,
      'payment': {
        'method': 'BANK',
        'method_label': '계좌이체',
        'approved_at': '2026-07-27T06:16:17Z',
        'transaction_id': 'BANK-TRX-LONG-1234567890',
        'bank_name': '그린잇 테스트은행',
        'authorization_number': 'BANK-AUTH-1234',
        'cash_receipt_status': 'ISSUED',
      },
      'receipts': {
        'sales_slip_url': 'https://example.com/bank-slip',
        'cash_receipt_url': 'https://example.com/cash-receipt',
      },
    });

    await tester.pumpWidget(MediaQuery(
      data: const MediaQueryData(textScaler: TextScaler.linear(1.2)),
      child: MaterialApp(
        home: PaymentCompletionScreen(payment: payment, onDone: () {}),
      ),
    ));

    expect(tester.takeException(), isNull);
    expect(find.text('80,000원'), findsOneWidget);
    expect(find.text('확인'), findsOneWidget);
    expect(find.text('현금영수증 보기'), findsOneWidget);
  });

  test('point-only completion displays the actual point amount', () {
    final payment = PaymentCompletionData.pointOnly({
      'amount': 0,
      'point_amount': 28500,
      'order_id': 'POINT-ORDER-1',
    });

    expect(payment.amount, 28500);
    expect(payment.displayedMethod, '포인트');
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

  test('API exception identifies payment-pending responses', () {
    const pending = ApiException(
        statusCode: 409, reason: 'PAYMENT_PENDING', message: '결제 승인 확인 중이에요');
    const other =
        ApiException(statusCode: 409, reason: 'OTHER', message: '다른 오류');

    expect(pending.isPaymentPending, isTrue);
    expect(other.isPaymentPending, isFalse);
    expect(shouldRetryPaymentConfirmation(pending, 0), isTrue);
    expect(
        shouldRetryPaymentConfirmation(
            pending, paymentConfirmationMaxAttempts - 2),
        isTrue);
    expect(
        shouldRetryPaymentConfirmation(
            pending, paymentConfirmationMaxAttempts - 1),
        isFalse);
    expect(shouldRetryPaymentConfirmation(other, 0), isFalse);
  });

  test('external payment app resume does not imply payment approval', () {
    expect(
      shouldConfirmPaymentOnResume(
        externalAppOpened: true,
        approvalPending: false,
      ),
      isFalse,
      reason: 'card security-program return must continue the provider WebView',
    );
    expect(
      shouldConfirmPaymentOnResume(
        externalAppOpened: true,
        approvalPending: true,
      ),
      isFalse,
      reason: 'an external return can also be a user cancellation',
    );
    expect(
      shouldConfirmPaymentOnResume(
        externalAppOpened: false,
        approvalPending: true,
      ),
      isTrue,
    );
  });

  test('payment WebView log labels redact session and query data', () {
    final label = paymentWebUriLogLabel(
      'https://vbv.shinhancard.com/mobilev2/VCRUN.jsp;JSESSIONID=secret'
      '?callback_token=secret-token#private',
    );
    expect(label, 'https://vbv.shinhancard.com/mobilev2/VCRUN.jsp');
    expect(label, isNot(contains('secret')));
    expect(label, isNot(contains('callback_token')));
  });

  test('only the exact mVaccine intent uses history restoration', () {
    expect(
      isMVaccineIntent(
        Uri.parse(
          'intent://mvaccine?siteid=shinhancard'
          '#Intent;scheme=mvaccinestart;package=com.TouchEn.mVaccine.webs;end',
        ),
      ),
      isTrue,
    );
    expect(
      isMVaccineIntent(
        Uri.parse(
          'intent://mvaccine?siteid=shinhancard'
          '#Intent;scheme=mvaccinestart;package=com.evil.fake;end',
        ),
      ),
      isFalse,
    );
    expect(
      isMVaccineIntent(
        Uri.parse(
          'intent://other#Intent;package=com.TouchEn.mVaccine.webs;end',
        ),
      ),
      isFalse,
    );
  });

  test('payment redirects are accepted only from the configured API origin',
      () {
    const base = 'https://greeneatgo-api.onrender.com/v1';

    expect(
      trustedPaymentRedirectOutcome(
        Uri.parse('https://greeneatgo-api.onrender.com/p'),
        base,
      ),
      PaymentRedirectOutcome.success,
    );
    expect(
      trustedPaymentRedirectOutcome(
        Uri.parse(
            'https://greeneatgo-api.onrender.com/v1/payments/redirect/close'),
        base,
      ),
      PaymentRedirectOutcome.close,
    );
    expect(
      trustedPaymentRedirectOutcome(
        Uri.parse('https://pay.kiwoompay.co.kr/p'),
        base,
      ),
      isNull,
      reason:
          'a provider/security-program path named /p is not our success URL',
    );
    expect(
      trustedPaymentRedirectOutcome(
        Uri.parse('https://greeneatgo-api.onrender.com.evil.example/p'),
        base,
      ),
      isNull,
    );
    expect(
      trustedPaymentRedirectOutcome(
        Uri.parse('https://greeneatgo-api.onrender.com:444/p'),
        base,
      ),
      isNull,
    );
    expect(
      trustedPaymentRedirectOutcome(
        Uri.parse('https://greeneatgo-api.onrender.com/not/p'),
        base,
      ),
      isNull,
    );
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
    expect(
        friendlyFirebaseAuthCode('custom-token-mismatch'), contains('앱 인증 설정'));
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
