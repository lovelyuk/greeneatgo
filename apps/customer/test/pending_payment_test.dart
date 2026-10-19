import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/main.dart';
import 'package:greeneatgo_customer/pending_payment.dart';

class MemoryPreferences implements PendingPaymentPreferences {
  final Map<String, String> values = <String, String>{};

  @override
  String? getString(String key) => values[key];

  @override
  Future<bool> remove(String key) async {
    values.remove(key);
    return true;
  }

  @override
  Future<bool> setString(String key, String value) async {
    values[key] = value;
    return true;
  }
}

PendingPayment payment({
  String uid = 'user-a',
  String orderId = 'ORDER-1',
  DateTime? createdAt,
}) =>
    PendingPayment(
      uid: uid,
      orderId: orderId,
      amount: 72000,
      createdAt: createdAt ?? DateTime.utc(2026, 7, 28, 10),
    );

Map<String, dynamic> confirmation() => <String, dynamic>{
      'amount': 72000,
      'payment': <String, dynamic>{
        'method': 'CARD',
        'method_label': '신용카드',
        'transaction_id': 'TRX-1',
      },
    };

void main() {
  test('pending payment round-trips with strict uid scoping', () async {
    final preferences = MemoryPreferences();
    final store = PendingPaymentStore(
      preferences,
      now: () => DateTime.utc(2026, 7, 28, 11),
    );
    final original = payment();

    await store.save(original);

    expect(store.load('user-b'), isNull);
    final loaded = store.load('user-a');
    expect(loaded?.validity, PendingPaymentValidity.valid);
    expect(loaded?.payment?.orderId, 'ORDER-1');
    expect(loaded?.payment?.amount, 72000);
  });

  test('stale and malformed potentially-paid records are retained', () async {
    final preferences = MemoryPreferences();
    final store = PendingPaymentStore(
      preferences,
      now: () => DateTime.utc(2026, 7, 28),
    );
    await store.save(payment(createdAt: DateTime.utc(2026, 7, 1)));

    expect(store.load('user-a')?.validity, PendingPaymentValidity.stale);

    final key = pendingPaymentStorageKey('user-a');
    preferences.values[key] = '{broken payment json';
    final malformed = store.load('user-a');
    expect(malformed?.validity, PendingPaymentValidity.malformed);
    expect(malformed?.raw, '{broken payment json');
    expect(preferences.values[key], isNotNull,
        reason: 'parsing must never silently delete a potentially-paid order');
  });

  test('clear is compare-before-remove and cannot delete a newer order',
      () async {
    final preferences = MemoryPreferences();
    final store = PendingPaymentStore(preferences);
    final oldPayment = payment();
    final newerPayment = payment(
      orderId: 'ORDER-2',
      createdAt: DateTime.utc(2026, 7, 28, 11),
    );
    await store.save(newerPayment);

    expect(await store.clear(oldPayment), isFalse);
    expect(store.load('user-a')?.payment?.orderId, 'ORDER-2');
    expect(await store.clear(newerPayment), isTrue);
    expect(store.load('user-a'), isNull);
  });

  testWidgets('pending payment banner is non-blocking until explicitly tapped',
      (tester) async {
    final preferences = MemoryPreferences();
    final store = PendingPaymentStore(
      preferences,
      now: () => DateTime.utc(2026, 7, 28, 11),
    );
    await store.save(payment());
    var tapped = false;

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: PendingPaymentRecoveryBanner(
          load: store.load('user-a')!,
          onTap: () => tapped = true,
        ),
      ),
    ));

    expect(find.text('결제 상태 확인'), findsNothing);
    expect(tapped, isFalse);
    await tester.tap(find.text('결제 승인을 확인하고 있어요'));
    await tester.pump();
    expect(tapped, isTrue);
  });

  testWidgets('recovery retries pending confirmation and clears on success',
      (tester) async {
    final preferences = MemoryPreferences();
    final store = PendingPaymentStore(
      preferences,
      now: () => DateTime.utc(2026, 7, 28, 11),
    );
    await store.save(payment());
    final load = store.load('user-a')!;
    var calls = 0;

    await tester.pumpWidget(MaterialApp(
      home: PendingPaymentRecoveryScreen(
        load: load,
        store: store,
        retryDelay: const Duration(seconds: 1),
        confirmPayment: ({required orderId, required amount}) async {
          calls++;
          if (calls == 1) {
            throw const ApiException(
              statusCode: 409,
              reason: 'PAYMENT_PENDING',
              message: 'pending',
            );
          }
          return confirmation();
        },
      ),
    ));
    await tester.pump();
    expect(calls, 1);
    expect(find.textContaining('30초 후'), findsOneWidget);

    await tester.pump(const Duration(seconds: 1));
    await tester.pump();
    expect(calls, 2);
    expect(find.text('결제 완료'), findsOneWidget);
    expect(store.load('user-a'), isNull);
  });

  testWidgets('recovery automatic confirmation stops at the retry limit',
      (tester) async {
    final preferences = MemoryPreferences();
    final store = PendingPaymentStore(
      preferences,
      now: () => DateTime.utc(2026, 7, 28, 11),
    );
    await store.save(payment());
    var calls = 0;

    await tester.pumpWidget(MaterialApp(
      home: PendingPaymentRecoveryScreen(
        load: store.load('user-a')!,
        store: store,
        retryDelay: const Duration(seconds: 1),
        confirmPayment: ({required orderId, required amount}) async {
          calls++;
          throw const ApiException(
            statusCode: 409,
            reason: 'PAYMENT_PENDING',
            message: 'pending',
          );
        },
      ),
    ));
    await tester.pump();
    for (var i = 1; i < paymentConfirmationMaxAttempts; i++) {
      await tester.pump(const Duration(seconds: 1));
      await tester.pump();
    }

    expect(calls, paymentConfirmationMaxAttempts);
    expect(find.textContaining('자동 확인을 마쳤어요'), findsOneWidget);
    await tester.pump(const Duration(seconds: 2));
    expect(calls, paymentConfirmationMaxAttempts);
    expect(store.load('user-a'), isNotNull);
  });

  testWidgets('recovery cancels delayed retry after stale lifecycle disposal',
      (tester) async {
    final preferences = MemoryPreferences();
    final store = PendingPaymentStore(
      preferences,
      now: () => DateTime.utc(2026, 7, 28, 11),
    );
    await store.save(payment());
    var calls = 0;

    await tester.pumpWidget(MaterialApp(
      home: PendingPaymentRecoveryScreen(
        load: store.load('user-a')!,
        store: store,
        retryDelay: const Duration(seconds: 1),
        confirmPayment: ({required orderId, required amount}) async {
          calls++;
          throw const ApiException(
            statusCode: 409,
            reason: 'PAYMENT_PENDING',
            message: 'pending',
          );
        },
      ),
    ));
    await tester.pump();
    expect(calls, 1);

    await tester.pumpWidget(const MaterialApp(home: SizedBox()));
    await tester.pump(const Duration(seconds: 2));
    expect(calls, 1);
    expect(store.load('user-a'), isNotNull,
        reason: 'dispose must not clear pending payment state');
  });

  testWidgets(
      'resume confirms immediately without overlapping an in-flight call',
      (tester) async {
    final preferences = MemoryPreferences();
    final store = PendingPaymentStore(
      preferences,
      now: () => DateTime.utc(2026, 7, 28, 11),
    );
    await store.save(payment());
    final pendingCall = Completer<Map<String, dynamic>>();
    var calls = 0;

    await tester.pumpWidget(MaterialApp(
      home: PendingPaymentRecoveryScreen(
        load: store.load('user-a')!,
        store: store,
        confirmPayment: ({required orderId, required amount}) {
          calls++;
          return pendingCall.future;
        },
      ),
    ));
    await tester.pump();
    expect(calls, 1);

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(calls, 1);

    pendingCall.complete(confirmation());
    await tester.pump();
    await tester.pump();
    expect(find.text('결제 완료'), findsOneWidget);
  });

  testWidgets('결제창에서 취소했어요: unpaid order is stopped on the server and the record removed',
      (tester) async {
    final store = PendingPaymentStore(MemoryPreferences(),
        now: () => DateTime.utc(2026, 7, 28, 11));
    final pending = payment();
    await store.save(pending);
    var stops = 0;
    final ready = <String, dynamic>{
      'order_id': 'ORDER-1', 'amount': 72000, 'status': 'ready',
      'recovery_action': 'reconcile', 'checkout_url': null,
    };
    await tester.pumpWidget(MaterialApp(
      home: Builder(builder: (context) => Scaffold(body: Center(
        child: TextButton(
          onPressed: () => Navigator.of(context).push(MaterialPageRoute<bool>(
            builder: (_) => PendingPaymentRecoveryScreen(
              load: store.load('user-a')!,
              store: store,
              confirmPayment: ({required orderId, required amount}) async =>
                  throw const ApiException(
                      statusCode: 409, reason: 'PAYMENT_PENDING', message: 'pending'),
              readRecovery: (_, __) async => ready,
              abandon: (_, __) async {
                stops++;
                return {
                  ...ready,
                  'status': 'canceled',
                  'recovery_action': 'locally_abandoned',
                  'completion': null,
                  'local_abandonment': {'outcome': 'abandoned'},
                };
              },
            ),
          )),
          child: const Text('open'),
        ),
      ))),
    ));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('pending-cancel')));
    await tester.pump();
    await tester.pump(const Duration(seconds: 3));
    await tester.pumpAndSettle();
    expect(stops, 1);
    expect(store.load('user-a'), isNull);
    expect(find.byType(PendingPaymentRecoveryScreen), findsNothing);
  });

  testWidgets('결제창에서 취소했어요: a paid order is confirmed, never stopped',
      (tester) async {
    final store = PendingPaymentStore(MemoryPreferences(),
        now: () => DateTime.utc(2026, 7, 28, 11));
    await store.save(payment());
    var stops = 0, confirms = 0;
    await tester.pumpWidget(MaterialApp(
      home: PendingPaymentRecoveryScreen(
        load: store.load('user-a')!,
        store: store,
        confirmPayment: ({required orderId, required amount}) async {
          confirms++;
          if (confirms == 1) {
            throw const ApiException(
                statusCode: 409, reason: 'PAYMENT_PENDING', message: 'pending');
          }
          return confirmation();
        },
        readRecovery: (_, __) async => {
          'order_id': 'ORDER-1', 'amount': 72000, 'status': 'done',
          'recovery_action': 'complete', 'checkout_url': null,
        },
        abandon: (_, __) async {
          stops++;
          return const {};
        },
      ),
    ));
    await tester.pump();
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('pending-cancel')));
    await tester.pump();
    await tester.pumpAndSettle();
    expect(stops, 0);
    expect(find.text('결제 완료'), findsOneWidget);
    expect(store.load('user-a'), isNull);
  });
}
