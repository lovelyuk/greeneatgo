import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/payment_result_view.dart';

void main() {
  Future<void> pumpState(
    WidgetTester tester,
    SolPaymentState state, {
    bool reduceMotion = false,
  }) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      MaterialApp(
        home: MediaQuery(
          data: MediaQueryData(
            size: const Size(360, 640),
            textScaler: const TextScaler.linear(1.3),
            disableAnimations: reduceMotion,
          ),
          child: SolPaymentResultView(
            state: state,
            merchantName: '돈토식당',
            amount: 8000,
            remaining: 9,
            paidAt: DateTime(2026, 8, 5, 9, 30),
            usesVoucher: true,
            errorMessage: '보유 식권이 없어요. 식권을 구매한 뒤 다시 시도해 주세요.',
            canPurchase: true,
            purchaseLabel: '식권 충전하기',
            onClose: () {},
            onConfirm: () {},
            onPurchase: () {},
            onRetry: () {},
          ),
        ),
      ),
    );
    await tester.pump();
  }

  testWidgets('SOL payment loading state fits a 360x640 accessibility viewport',
      (tester) async {
    await pumpState(tester, SolPaymentState.loading, reduceMotion: true);

    expect(find.text('결제하고 있어요'), findsOneWidget);
    expect(find.text('결제 취소'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('SOL payment done state binds ticket values', (tester) async {
    await pumpState(tester, SolPaymentState.done, reduceMotion: true);

    expect(find.text('결제 완료'), findsOneWidget);
    expect(find.text('돈토식당 · 중식'), findsOneWidget);
    expect(find.text('8,000원'), findsOneWidget);
    expect(find.text('9장'), findsOneWidget);
    expect(find.text('8/5 09:30'), findsOneWidget);
    expect(find.text('확인'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('SOL payment failure state exposes server reason and recovery',
      (tester) async {
    await pumpState(tester, SolPaymentState.fail, reduceMotion: true);

    expect(find.text('결제하지 못했어요'), findsOneWidget);
    expect(find.textContaining('보유 식권이 없어요'), findsOneWidget);
    expect(find.text('식권 충전하기'), findsOneWidget);
    expect(find.text('닫기'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
