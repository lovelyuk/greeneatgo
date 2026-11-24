import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/screens/member_qr_screen.dart';
import 'package:qr_flutter/qr_flutter.dart';

final _code = '81${'0' * 37}12345678${'1' * 34}';

Future<void> _pump(WidgetTester tester, Widget child) async {
  await tester.binding.setSurfaceSize(const Size(360, 740));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(MaterialApp(home: child));
}

void main() {
  testWidgets('shows a scannable member QR with countdown, then "used" when balance drops',
      (tester) async {
    var balance = 5;
    var loads = 0;
    await _pump(
      tester,
      MemberQrScreen(
        loadCode: (_) async {
          loads++;
          return {
            'code': _code,
            'expires_at': DateTime.now().millisecondsSinceEpoch ~/ 1000 + 60,
            'ttl': 60,
          };
        },
        readBalance: () async => balance,
        pollInterval: const Duration(seconds: 1),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 600));

    final qr = tester.widget<QrImageView>(find.byKey(const ValueKey('member-qr-image')));
    expect(find.byType(QrImageView), findsOneWidget);
    expect(loads, 1);
    expect(find.textContaining('초 후 새 QR로 바뀌어요'), findsOneWidget);
    expect(qr.size, 240);

    balance = 4; // counter redeemed one voucher
    for (var i = 0; i < 6; i++) {
      await tester.pump(const Duration(milliseconds: 500));
    }
    expect(find.byKey(const ValueKey('member-qr-used')), findsOneWidget);
    expect(find.text('식권 1장 사용 완료'), findsOneWidget);
    expect(find.text('남은 식권 4장'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('rejects a malformed server code instead of drawing it', (tester) async {
    await _pump(
      tester,
      MemberQrScreen(
        loadCode: (_) async => {'code': 'QR-DONTO', 'expires_at': 1, 'ttl': 60},
        readBalance: () async => 3,
      ),
    );
    await tester.pump();
    await tester.pump();
    expect(find.byType(QrImageView), findsNothing);
    expect(find.text('QR을 만들지 못했어요.'), findsOneWidget);
    expect(find.text('다시 만들기'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('store-QR fallback button is offered', (tester) async {
    var tapped = false;
    await _pump(
      tester,
      MemberQrScreen(
        loadCode: (_) async => {
          'code': _code,
          'expires_at': DateTime.now().millisecondsSinceEpoch ~/ 1000 + 60,
          'ttl': 60,
        },
        readBalance: () async => 1,
        onScanStoreQr: (_) => tapped = true,
      ),
    );
    await tester.pump();
    await tester.pump();
    await tester.ensureVisible(find.byKey(const ValueKey('scan-store-qr-button')));
    expect(find.text('매장 QR 찍어서 결제'), findsOneWidget);
    expect(find.text('카운터에 스캐너가 없을 때 사용해요'), findsOneWidget);
    expect(find.byType(OutlinedButton), findsNothing,
        reason: 'Q3 card, not the olive theme outlined button');
    await tester.tap(find.byKey(const ValueKey('scan-store-qr-button')));
    expect(tapped, isTrue);
    // One voucher held: nothing to choose.
    expect(find.byKey(const ValueKey('qr-quantity')), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  Map<String, dynamic> answer(int quantity) => {
        'code': '${quantity > 1 ? '83' : '81'}${_code.substring(2)}',
        'quantity': quantity,
        'expires_at': DateTime.now().millisecondsSinceEpoch ~/ 1000 + 60,
        'ttl': 60,
      };

  testWidgets('pick how many vouchers one scan uses: new code per quantity, capped by what is held',
      (tester) async {
    var balance = 3;
    final asked = <int>[];
    int? scanned;
    await _pump(
      tester,
      MemberQrScreen(
        loadCode: (quantity) async {
          asked.add(quantity);
          return answer(quantity);
        },
        readBalance: () async => balance,
        pollInterval: const Duration(seconds: 1),
        onScanStoreQr: (quantity) => scanned = quantity,
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.byKey(const ValueKey('qr-quantity')), findsOneWidget);
    expect(find.text('1장'), findsOneWidget);
    expect(find.text('최대 3장'), findsOneWidget);
    expect(find.byKey(const ValueKey('member-qr-quantity-note')), findsNothing);
    expect(tester.widget<IconButton>(find.byKey(const ValueKey('qr-quantity-minus'))).onPressed, isNull);

    await tester.tap(find.byKey(const ValueKey('qr-quantity-plus')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.byKey(const ValueKey('qr-quantity-plus')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(asked, [1, 2, 3]);
    expect(find.text('3장'), findsOneWidget);
    expect(find.text('이 QR은 3장용이에요'), findsOneWidget);
    expect(find.text('카운터 스캐너에 화면을 대 주세요. 한 번에 식권 3장이 사용돼요.'), findsOneWidget);
    expect(tester.widget<QrImageView>(find.byKey(const ValueKey('member-qr-image'))).key, isNotNull);
    // Holds 3: cannot go to 4.
    expect(tester.widget<IconButton>(find.byKey(const ValueKey('qr-quantity-plus'))).onPressed, isNull);

    // The camera fallback takes the chosen quantity along.
    await tester.ensureVisible(find.byKey(const ValueKey('scan-store-qr-button')));
    await tester.tap(find.byKey(const ValueKey('scan-store-qr-button')));
    expect(scanned, 3);

    balance = 0; // the counter used all three
    for (var i = 0; i < 6; i++) {
      await tester.pump(const Duration(milliseconds: 500));
    }
    expect(find.text('식권 3장 사용 완료'), findsOneWidget);
    expect(find.text('남은 식권 0장'), findsOneWidget);
    expect(find.byKey(const ValueKey('qr-quantity')), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('a one-meal answer is never shown under a larger number', (tester) async {
    await _pump(
      tester,
      MemberQrScreen(
        // A server that ignores the quantity.
        loadCode: (_) async => answer(1),
        readBalance: () async => 5,
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.byKey(const ValueKey('qr-quantity-plus')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.byType(QrImageView), findsNothing);
    expect(find.text('여러 장 사용은 아직 준비 중이에요. 1장으로 다시 만들어 주세요.'), findsOneWidget);
    expect(find.text('1장'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('a slow answer for an earlier quantity is dropped', (tester) async {
    final pending = <int, Completer<Map<String, dynamic>>>{};
    await _pump(
      tester,
      MemberQrScreen(
        loadCode: (quantity) => (pending[quantity] = Completer()).future,
        readBalance: () async => 5,
      ),
    );
    await tester.pump();
    pending[1]!.complete(answer(1));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tap(find.byKey(const ValueKey('qr-quantity-plus')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('qr-quantity-plus')));
    await tester.pump();
    // 3 answers first, then the stale answer for 2 arrives.
    pending[3]!.complete(answer(3));
    await tester.pump();
    pending[2]!.complete(answer(2));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    final qr = tester.widget<QrImageView>(find.byKey(const ValueKey('member-qr-image')));
    expect(find.text('이 QR은 3장용이에요'), findsOneWidget);
    expect(find.text('3장'), findsOneWidget);
    expect(qr, isNotNull);
    await tester.pumpWidget(const SizedBox());
  });
}
