import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/main.dart'
    show ApiException, PaySource, PaySourceToggle, shouldOfferPersonalVoucher;
import 'package:greeneatgo_customer/restaurants.dart';
import 'package:greeneatgo_customer/screens/user_dashboard_shell.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _one = [
  Restaurant(id: 'm1', name: '가산 한식뷔페', address: '가산디지털1로 145', voucherBalance: 3, voucherPrice: 8000),
];
const _three = [
  Restaurant(id: 'm1', name: '가산 한식뷔페', address: '가산디지털1로 145', voucherBalance: 3, voucherPrice: 8000),
  Restaurant(id: 'm2', name: '디지털 국수집', address: '디지털로 9길', voucherBalance: 5, voucherPrice: 7500),
  Restaurant(id: 'm3', name: '구로 덮밥', address: '구로동', category: '일식', voucherPrice: 9000),
];

Future<void> _noop() async {}

Widget _shell(List<Restaurant> restaurants, {Map<String, dynamic>? data}) => MaterialApp(
      home: UserDashboardShell(
        data: data ??
            const {'display_name': '김식권', 'role': 'customer', 'account_type': 'voucher', 'voucher_balance': 3},
        onRefresh: _noop, onScanQr: _noop, onBuyVoucher: _noop, onCoupons: _noop, onEvents: _noop,
        onOpenSettings: _noop, onOpenInviteCode: _noop, onAnnouncements: _noop, onReviews: _noop,
        onTerms: _noop, onPrivacy: _noop, onSignOut: _noop,
        pendingBanner: null,
        restaurantsLoader: () async => restaurants,
      ),
    );

Future<void> _pump(WidgetTester tester, Widget widget) async {
  tester.view.physicalSize = const Size(1080, 2340);
  tester.view.devicePixelRatio = 2.75;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(widget);
  await tester.pumpAndSettle();
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('parses the list and keeps a saved choice only while it is still listed', () {
    final parsed = restaurantsFromResponse({
      'items': [
        {'id': 'm1', 'name': ' 가산 한식뷔페 ', 'address': '가산디지털1로 145', 'voucher_balance': 2, 'voucher_price': 7200},
        {'id': '', 'name': '이름만'},
        {'id': 'm9', 'name': ''},
      ],
    });
    expect(parsed.map((r) => r.id), ['m1']);
    expect(parsed.single.subtitle, '가산디지털1로 145 · 식권 7,200원');
    expect(restaurantsFromResponse({'items': null}), isEmpty);
    expect(pickRestaurant(_three, 'm2')!.id, 'm2');
    expect(pickRestaurant(_three, 'gone')!.id, 'm1');
    expect(pickRestaurant(const [], 'm1'), isNull);
  });

  test('a company refusal offers the personal voucher only when one is held', () {
    ApiException refusal(Map<String, dynamic> details, {String? reason = 'DAILY_LIMIT'}) =>
        ApiException(statusCode: 400, message: '오늘 식대 한도를 초과했어요', reason: reason, details: details);
    expect(shouldOfferPersonalVoucher(refusal({'personal_voucher_balance': 2}), null), isTrue);
    expect(shouldOfferPersonalVoucher(refusal({'personal_voucher_balance': 2}), PaySource.company), isTrue);
    expect(shouldOfferPersonalVoucher(refusal({'personal_voucher_balance': 0}), null), isFalse);
    expect(shouldOfferPersonalVoucher(refusal(const {}), null), isFalse);
    // Already paying with the personal voucher: never ask again.
    expect(shouldOfferPersonalVoucher(refusal({'personal_voucher_balance': 2}), PaySource.personal), isFalse);
  });

  testWidgets('one restaurant: the bar and 식당 변경 are shown and open the picker', (tester) async {
    await _pump(tester, _shell(_one));
    expect(find.byKey(const ValueKey('restaurant-bar')), findsOneWidget);
    expect(find.text('가산 한식뷔페'), findsOneWidget);
    expect(find.text('식당 변경'), findsOneWidget);
    expect(find.byKey(const ValueKey('other-restaurant-vouchers')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('restaurant-bar')));
    await tester.pumpAndSettle();
    expect(find.text('식당 고르기'), findsOneWidget);
    expect(find.text('내 식권이 있는 식당'), findsOneWidget);
    expect(find.byKey(const ValueKey('restaurant-option-m1')), findsOneWidget);
    expect(find.text('3장'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('restaurant-option-m1')));
    await tester.pumpAndSettle();
    expect(find.text('식당 고르기'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('several restaurants: other-voucher line, search, pick and remember', (tester) async {
    await _pump(tester, _shell(_three));
    expect(find.text('다른 식당 식권 1곳 · 5장'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('other-restaurant-vouchers')));
    await tester.pumpAndSettle();
    expect(find.text('다른 식당'), findsOneWidget);
    expect(find.byKey(const ValueKey('restaurant-option-m3')), findsOneWidget);
    await tester.enterText(find.byKey(const ValueKey('restaurant-search')), '구로');
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('restaurant-option-m1')), findsNothing);
    expect(find.byKey(const ValueKey('restaurant-option-m3')), findsOneWidget);
    await tester.enterText(find.byKey(const ValueKey('restaurant-search')), '없는집');
    await tester.pumpAndSettle();
    expect(find.text('찾는 식당이 없어요.'), findsOneWidget);
    await tester.enterText(find.byKey(const ValueKey('restaurant-search')), '국수');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('restaurant-option-m2')));
    await tester.pumpAndSettle();
    expect(find.descendant(of: find.byKey(const ValueKey('restaurant-bar')), matching: find.text('디지털 국수집')),
        findsOneWidget);
    expect(find.text('다른 식당 식권 1곳 · 3장'), findsOneWidget);
    expect((await SharedPreferences.getInstance()).getString(selectedRestaurantKey), 'm2');
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('the remembered restaurant is restored, and a failed load hides the bar', (tester) async {
    SharedPreferences.setMockInitialValues({selectedRestaurantKey: 'm2'});
    await _pump(tester, _shell(_three));
    expect(find.descendant(of: find.byKey(const ValueKey('restaurant-bar')), matching: find.text('디지털 국수집')),
        findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    await _pump(
        tester,
        MaterialApp(
          home: UserDashboardShell(
            data: const {'display_name': '김식권', 'role': 'customer', 'account_type': 'voucher', 'voucher_balance': 3},
            onRefresh: _noop, onScanQr: _noop, onBuyVoucher: _noop, onCoupons: _noop, onEvents: _noop,
            onOpenSettings: _noop, onOpenInviteCode: _noop, onAnnouncements: _noop, onReviews: _noop,
            onTerms: _noop, onPrivacy: _noop, onSignOut: _noop,
            pendingBanner: null,
            restaurantsLoader: () async => throw Exception('offline'),
          ),
        ));
    expect(find.byKey(const ValueKey('restaurant-bar')), findsNothing);
    expect(find.text('내역'), findsWidgets);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('purchase chip and QR balance list read the shared restaurant scope', (tester) async {
    var picks = 0;
    await _pump(
        tester,
        MaterialApp(
          home: Scaffold(
            body: RestaurantScope(
              restaurants: _three,
              selected: _three[1],
              onPick: () => picks++,
              child: const Column(children: [RestaurantPurchaseChip(), RestaurantBalanceList()]),
            ),
          ),
        ));
    expect(find.descendant(of: find.byKey(const ValueKey('restaurant-purchase-chip')), matching: find.text('디지털 국수집')),
        findsOneWidget);
    expect(find.text('이 식당에서만 쓸 수 있어요'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('restaurant-purchase-chip')));
    expect(picks, 1);
    // Only restaurants where vouchers are held are listed under the QR.
    final list = find.byKey(const ValueKey('restaurant-balance-list'));
    expect(find.descendant(of: list, matching: find.text('가산 한식뷔페')), findsOneWidget);
    expect(find.descendant(of: list, matching: find.text('5장')), findsOneWidget);
    expect(find.descendant(of: list, matching: find.text('구로 덮밥')), findsNothing);
    // Outside the dashboard (no scope) both render nothing.
    await tester.pumpWidget(const MaterialApp(
        home: Scaffold(body: Column(children: [RestaurantPurchaseChip(), RestaurantBalanceList()]))));
    expect(find.byKey(const ValueKey('restaurant-purchase-chip')), findsNothing);
    expect(find.byKey(const ValueKey('restaurant-balance-list')), findsNothing);
  });

  testWidgets('ledger employee home shows personal vouchers; the pay switch reports the choice', (tester) async {
    await _pump(
        tester,
        _shell(_one, data: const {
          'display_name': '김직원', 'role': 'employee', 'account_type': 'ledger', 'voucher_balance': null,
          'personal_voucher_balance': 4, 'month_used': 16000, 'recent_transactions': [],
        }));
    // The wallet card opens on the 회사 tab (no voucher count, no buy button);
    // the 개인 tab counts the employee's own vouchers (4) and offers buying.
    await tester.pump();
    expect(find.byKey(const ValueKey('meal-card-tabs')), findsOneWidget);
    expect(find.byKey(const ValueKey('company-meal-unknown')), findsOneWidget);
    expect(find.byKey(const ValueKey('buy-ticket-button')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('meal-tab-personal')));
    await tester.pump();
    expect(find.bySemanticsLabel(RegExp('남은 식권 4.*내 식권 · QR 한 번에 1장 사용')), findsOneWidget);
    expect(find.byKey(const ValueKey('buy-ticket-button')), findsOneWidget);
    await tester.pumpWidget(const SizedBox());

    PaySource? chosen;
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: PaySourceToggle(
                value: PaySource.company, personalBalance: 4, onChanged: (source) => chosen = source))));
    expect(find.text('보유 4장'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('pay-source-company')));
    expect(chosen, isNull);
    await tester.tap(find.byKey(const ValueKey('pay-source-personal')));
    expect(chosen, PaySource.personal);
  });
}
