import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/screens/coupon_wallet.dart';
import 'package:greeneatgo_customer/theme/app_colors.dart';

void main() {
  const coupon = CouponItem(
    id: 'coupon-1',
    name: '첫 구매 웰컴 할인',
    discountType: 'percent',
    discountValue: 15,
    validUntil: null,
  );
  const wallet = CouponWallet(merchantName: '돈토식당', items: [coupon]);

  test('API decimal strings and payment_amount parse without losing value', () {
    final parsedCoupon = CouponItem.fromJson({
      'id': 'coupon-decimal',
      'name': '소수 할인',
      'discount_type': 'percent',
      'discount_value': '12.50',
    });
    final quote = VoucherQuote.fromJson({
      'gross_amount': 10000,
      'coupon_discount_amount': 1250,
      'point_amount': 1500,
      'payment_amount': 7250,
    });
    expect(parsedCoupon.benefit, '12.5%');
    expect(quote.amount, 7250);
  });

  Future<void> pumpAtPhoneSize(WidgetTester tester, Widget child) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MediaQuery(
      data: const MediaQueryData(textScaler: TextScaler.linear(1.3)),
      child: MaterialApp(home: child),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('coupon wallet renders ticket hierarchy at 360x640 scale 1.3',
      (tester) async {
    await pumpAtPhoneSize(
        tester, CouponWalletScreen(loadCoupons: () async => wallet));

    expect(find.text('쿠폰함'), findsOneWidget);
    expect(find.byType(CouponTicketCard), findsOneWidget);
    expect(find.text('15%'), findsOneWidget);
    expect(find.text('첫 구매 웰컴 할인'), findsOneWidget);
    expect(find.textContaining('유효기간'), findsOneWidget);
    expect(tester.takeException(), isNull);

    final ticket = tester.getRect(find.byType(CouponTicketCard));
    expect(ticket.left, 18);
    expect(ticket.right, 342);
    expect(ticket.height, 154);
  });

  testWidgets('checkout requotes coupon and exact/max point intents',
      (tester) async {
    final calls = <(String?, int)>[];
    Future<VoucherQuote> quote({
      required String productId,
      String? couponId,
      required int pointAmount,
    }) async {
      calls.add((couponId, pointAmount));
      final discount = couponId == null ? 0 : 1500;
      return VoucherQuote(
        grossAmount: 10000,
        couponDiscountAmount: discount,
        pointAmount: pointAmount,
        amount: 10000 - discount - pointAmount,
      );
    }

    await pumpAtPhoneSize(
      tester,
      CheckoutOptionsScreen(
        productId: 'product-1',
        productName: '돈토 식권 10장',
        pointBalance: 3000,
        loadCoupons: () async => wallet,
        loadQuote: quote,
      ),
    );
    expect(calls, [(null, 0)]);

    await tester.tap(find.byType(CouponTicketCard));
    await tester.pumpAndSettle();
    expect(calls.last, ('coupon-1', 0));

    await tester.drag(find.byType(ListView), const Offset(0, -420));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('server-quote')), findsOneWidget);
    expect(find.text('상품 금액'), findsOneWidget);
    expect(find.byKey(const Key('point-entry')), findsOneWidget);
    await tester.enterText(find.byKey(const Key('point-entry')), '1250');
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();
    expect(calls.last, ('coupon-1', 1250));
    expect(find.text('-1,250원'), findsOneWidget);

    await tester.tap(find.byKey(const Key('max-points')));
    await tester.pumpAndSettle();
    expect(calls.last, ('coupon-1', 3000));
    expect(tester.takeException(), isNull);
  });

  testWidgets('coupon outage still allows a server-quoted purchase',
      (tester) async {
    var quoteCalls = 0;
    await pumpAtPhoneSize(
      tester,
      CheckoutOptionsScreen(
        productId: 'product-1',
        productName: '돈토 식권 10장',
        pointBalance: 0,
        loadCoupons: () async => throw Exception('coupon service unavailable'),
        loadQuote: ({
          required String productId,
          String? couponId,
          required int pointAmount,
        }) async {
          quoteCalls++;
          return const VoucherQuote(
            grossAmount: 10000,
            couponDiscountAmount: 0,
            pointAmount: 0,
            amount: 10000,
          );
        },
      ),
    );

    expect(quoteCalls, 1);
    expect(find.byKey(const Key('coupon-warning')), findsOneWidget);
    final button = tester
        .widget<FilledButton>(find.byKey(const Key('continue-to-payment')));
    expect(button.onPressed, isNotNull);
    expect(button.style?.backgroundColor?.resolve({}), AppColors.blue);
    expect(find.text('10,000원 결제하기'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('coupon wallet renders issued and public coupon sections',
      (tester) async {
    final parsed = CouponWallet.fromJson({
      'merchant': {'name': '돈토식당'},
      'issued': [
        {
          'id': 'user-coupon-1',
          'coupon_id': 'coupon-issued',
          'coupon_snapshot': {
            'name': '발급 쿠폰',
            'discount_type': 'fixed',
            'discount_value': 2000,
            'source': '배너',
          },
        },
      ],
      'items': [
        {
          'id': 'coupon-public',
          'name': '공개 쿠폰',
          'discount_type': 'percent',
          'discount_value': 10,
        },
      ],
    });

    await pumpAtPhoneSize(
      tester,
      CouponWalletScreen(loadCoupons: () async => parsed),
    );

    expect(find.text('2장의 쿠폰'), findsOneWidget);
    expect(find.text('내 쿠폰'), findsOneWidget);
    expect(find.text('공개 쿠폰'), findsNWidgets(2));
    expect(find.text('발급 쿠폰'), findsOneWidget);
    expect(find.byType(CouponTicketCard), findsNWidgets(2));
    expect(parsed.availableCount, 2);
    expect(parsed.issued.single.id, 'coupon-issued');
    expect(parsed.issued.single.userCouponId, 'user-coupon-1');
    expect(parsed.issued.single.source, '배너');
  });

  testWidgets('issued coupon checkout sends user_coupon_id to quote',
      (tester) async {
    const issued = CouponItem(
      id: 'coupon-template',
      name: '배너 발급 쿠폰',
      discountType: 'fixed',
      discountValue: 1000,
      userCouponId: 'user-coupon-77',
    );
    String? quotedUserCouponId;
    await pumpAtPhoneSize(
      tester,
      CheckoutOptionsScreen(
        productId: 'product-1',
        productName: '돈토 식권 10장',
        pointBalance: 0,
        loadCoupons: () async => const CouponWallet(
          merchantName: '돈토식당',
          items: [],
          issued: [issued],
        ),
        loadQuote: ({
          required String productId,
          String? couponId,
          required int pointAmount,
        }) async =>
            const VoucherQuote(
          grossAmount: 10000,
          couponDiscountAmount: 0,
          pointAmount: 0,
          amount: 10000,
        ),
        loadIssuedQuote: ({
          required String productId,
          String? couponId,
          String? userCouponId,
          required int pointAmount,
        }) async {
          quotedUserCouponId = userCouponId;
          return const VoucherQuote(
            grossAmount: 10000,
            couponDiscountAmount: 1000,
            pointAmount: 0,
            amount: 9000,
          );
        },
      ),
    );

    await tester.tap(find.byType(CouponTicketCard));
    await tester.pumpAndSettle();

    expect(quotedUserCouponId, 'user-coupon-77');
    expect(find.text('9,000원 결제하기'), findsOneWidget);
  });
}
