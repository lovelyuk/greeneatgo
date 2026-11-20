import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/screens/purchase_receipt.dart';
import 'package:greeneatgo_customer/screens/user_dashboard_shell.dart';

Map<String, dynamic> _receipt({Map<String, dynamic>? refund, String method = 'CARD', String slipTitle = '카드 매출전표'}) => {
      'summary': {'order_id': 'GE-V-1', 'product_name': '11장 식권', 'merchant_name': '가산 한식뷔페', 'amount': 80000, 'status': refund == null ? 'done' : 'refunded'},
      'completion': {
        'order_id': 'GE-V-1',
        'amount': 80000,
        'payment': {
          'method': method,
          'method_label': method == 'KAKAOPAY' ? '카카오페이' : '카드',
          'approved_at': '2026-11-19T03:08:00+00:00',
          'transaction_id': 'DAOU123',
          'issuer_name': '신한카드',
          'masked_card_number': '5107-37**-****-8900',
          'authorization_number': '30011223',
        },
        'receipts': {'sales_slip_url': 'https://agent.kiwoompay.co.kr/common/slip?x=1', 'cash_receipt_url': null},
      },
      'receipt': {'lookup': {'date': '2026-11-19', 'amount': 80000, 'number': '30011223', 'number_type': 'approval'}},
      'slip_title': slipTitle,
      'refund': refund,
    };

Future<void> _pump(WidgetTester tester, Widget child) async {
  tester.view.physicalSize = const Size(780, 1688);
  tester.view.devicePixelRatio = 2;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(home: child));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('receipt shows the paid order, opens the slip and offers the lookup values', (tester) async {
    final opened = <String>[];
    await _pump(tester, PurchaseReceiptScreen(load: () async => _receipt(), onOpenReceipt: (_, title, url) => opened.add('$title|$url')));
    expect(find.text('결제 영수증'), findsOneWidget);
    expect(find.text('11장 식권'), findsOneWidget);
    expect(find.text('가산 한식뷔페'), findsOneWidget);
    expect(find.text('80,000원'), findsOneWidget);
    expect(find.text('30011223'), findsOneWidget);
    expect(find.byKey(const ValueKey('payment-done-check')), findsNothing);
    expect(find.byKey(const ValueKey('purchase-receipt-refund')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('payment-sales-slip-button')));
    expect(opened, ['카드 매출전표|https://agent.kiwoompay.co.kr/common/slip?x=1']);
    expect(find.textContaining('결제일 2026-11-19'), findsOneWidget);

    String? copied;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') copied = (call.arguments as Map)['text'] as String;
      return null;
    });
    await tester.ensureVisible(find.byKey(const ValueKey('purchase-receipt-copy')));
    await tester.tap(find.byKey(const ValueKey('purchase-receipt-copy')));
    await tester.pump();
    expect(copied, '30011223');
    expect(find.text('승인번호를 복사했어요'), findsOneWidget);
  });

  testWidgets('KakaoPay slip is offered under the server name and a refund is shown', (tester) async {
    await _pump(
        tester,
        PurchaseReceiptScreen(
            load: () async => _receipt(
                method: 'KAKAOPAY',
                slipTitle: '카카오페이 매출전표',
                refund: {'status': 'completed', 'refund_amount': 80000, 'completed_at': '2026-11-20T00:10:00+00:00'})));
    expect(find.text('카카오페이 매출전표 보기'), findsOneWidget);
    expect(find.text('환불 완료된 결제예요'), findsOneWidget);
    expect(find.textContaining('80,000원 ·'), findsOneWidget);
  });

  testWidgets('load failure offers a retry that loads again', (tester) async {
    var calls = 0;
    await _pump(tester, PurchaseReceiptScreen(load: () async {
      calls++;
      if (calls == 1) throw Exception('영수증을 불러오지 못했어요');
      return _receipt();
    }));
    expect(find.text('영수증을 불러오지 못했어요'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('purchase-receipt-retry')));
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.text('11장 식권'), findsOneWidget);
  });

  testWidgets('내역 tab: 구매 segment lists orders, filters by restaurant, opens the receipt', (tester) async {
    final opened = <String>[];
    Future<void> noop() async {}
    await _pump(
        tester,
        UserDashboardShell(
          data: const {
            'display_name': '김구매', 'role': 'customer', 'account_type': 'voucher', 'voucher_balance': 3,
            'voucher_use_history': [
              {'id': 1, 'amount': 8000, 'kind': 'voucher_use', 'title': '식권 사용', 'merchant_name': '가산 한식뷔페', 'created_at': '2026-11-19T03:08:00+00:00'},
            ],
          },
          onRefresh: noop, onScanQr: noop, onBuyVoucher: noop, onCoupons: noop, onEvents: noop, onOpenSettings: noop,
          onOpenInviteCode: noop, onAnnouncements: noop, onReviews: noop, onTerms: noop, onPrivacy: noop, onSignOut: noop,
          pendingBanner: null,
          purchaseHistoryLoader: () async => [
            {'order_id': 'GE-V-2', 'product_name': '11장 식권', 'merchant_name': '가산 한식뷔페', 'amount': 80000, 'status': 'done', 'method_label': '카드', 'approved_at': '2026-11-19T03:08:00+00:00'},
            {'order_id': 'GE-V-1', 'product_name': '1장 식권', 'merchant_name': '디지털 국수집', 'amount': 7500, 'status': 'refunded', 'method_label': '네이버페이', 'approved_at': '2026-11-18T03:08:00+00:00'},
          ],
          onOpenPurchase: (purchase) async => opened.add('${purchase['order_id']}'),
        ));
    await tester.tap(find.text('내역'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('history-segment-usage')), findsOneWidget);
    // 사용 list carries the restaurant chip row.
    expect(find.byKey(const ValueKey('history-merchant-chips')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('history-segment-purchases')));
    await tester.pumpAndSettle();
    expect(find.text('11장 식권'), findsOneWidget);
    expect(find.text('환불 완료'), findsOneWidget);
    await tester.tap(find.widgetWithText(InkWell, '디지털 국수집').first);
    await tester.pumpAndSettle();
    expect(find.text('11장 식권'), findsNothing);
    expect(find.text('1장 식권'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('purchase-row-GE-V-1')));
    await tester.pumpAndSettle();
    expect(opened, ['GE-V-1']);
    await tester.pumpWidget(const SizedBox());
  });
}
