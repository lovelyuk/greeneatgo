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
        loadCode: () async {
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
        loadCode: () async => {'code': 'QR-DONTO', 'expires_at': 1, 'ttl': 60},
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
        loadCode: () async => {
          'code': _code,
          'expires_at': DateTime.now().millisecondsSinceEpoch ~/ 1000 + 60,
          'ttl': 60,
        },
        readBalance: () async => 3,
        onScanStoreQr: () => tapped = true,
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
    await tester.pumpWidget(const SizedBox());
  });
}
