import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/pending_payment.dart';

class _MemPrefs implements PendingPaymentPreferences {
  final Map<String, String> values = {};
  @override
  String? getString(String key) => values[key];
  @override
  Future<bool> setString(String key, String value) async {
    values[key] = value;
    return true;
  }

  @override
  Future<bool> remove(String key) async => values.remove(key) != null;
}

final _payment = PendingPayment(
  uid: 'user-1',
  orderId: 'GE-V-ORDER1',
  amount: 100,
  createdAt: DateTime.utc(2026, 10, 19, 3),
);

Map<String, dynamic> _ready() => {
      'order_id': 'GE-V-ORDER1',
      'amount': 100,
      'status': 'ready',
      'recovery_action': 'reconcile',
      'checkout_url': null,
      'resumable': false,
    };

Map<String, dynamic> _stopped() => {
      'order_id': 'GE-V-ORDER1',
      'amount': 100,
      'status': 'canceled',
      'recovery_action': 'locally_abandoned',
      'checkout_url': null,
      'completion': null,
      'local_abandonment': {'outcome': 'abandoned'},
    };

Future<PendingPaymentStore> _store() async {
  final store = PendingPaymentStore(_MemPrefs());
  await store.save(_payment);
  return store;
}

void main() {
  test('closed checkout: ready order is stopped on the server, then the record is removed',
      () async {
    final store = await _store();
    var reads = 0, stops = 0;
    final outcome = await settleClosedCheckout(
      payment: _payment,
      store: store,
      readRecovery: (_, __) async {
        reads++;
        return _ready();
      },
      abandon: (orderId, amount) async {
        stops++;
        expect(orderId, 'GE-V-ORDER1');
        expect(amount, 100);
        return _stopped();
      },
      sleep: (_) async {},
    );
    expect(outcome, PendingSettleOutcome.cleared);
    expect(reads, 2, reason: 'waits once for a just-finished approval');
    expect(stops, 1);
    expect(store.load('user-1'), isNull);
  });

  test('paid order keeps the record (Home must confirm and issue vouchers)',
      () async {
    final store = await _store();
    var stops = 0;
    final outcome = await settleClosedCheckout(
      payment: _payment,
      store: store,
      readRecovery: (_, __) async => {..._ready(), 'status': 'done', 'recovery_action': 'complete'},
      abandon: (_, __) async {
        stops++;
        return _stopped();
      },
      sleep: (_) async {},
    );
    expect(outcome, PendingSettleOutcome.paid);
    expect(stops, 0);
    expect(store.load('user-1'), isNotNull);
  });

  test('approval landing during the settle wait is never stopped', () async {
    final store = await _store();
    var reads = 0, stops = 0;
    final outcome = await settleClosedCheckout(
      payment: _payment,
      store: store,
      readRecovery: (_, __) async => ++reads == 1
          ? _ready()
          : {..._ready(), 'status': 'done', 'recovery_action': 'complete'},
      abandon: (_, __) async {
        stops++;
        return _stopped();
      },
      sleep: (_) async {},
    );
    expect(outcome, PendingSettleOutcome.paid);
    expect(stops, 0);
    expect(store.load('user-1'), isNotNull);
  });

  test('server stop with a late-approval contradiction keeps the record', () async {
    final store = await _store();
    final outcome = await settleClosedCheckout(
      payment: _payment,
      store: store,
      readRecovery: (_, __) async => _ready(),
      abandon: (_, __) async => {..._stopped(), 'recovery_action': 'reconcile'},
      sleep: (_) async {},
    );
    expect(outcome, PendingSettleOutcome.unknown);
    expect(store.load('user-1'), isNotNull);
  });

  test('network error keeps the record', () async {
    final store = await _store();
    final outcome = await settleClosedCheckout(
      payment: _payment,
      store: store,
      readRecovery: (_, __) async => throw Exception('offline'),
      abandon: (_, __) async => _stopped(),
      sleep: (_) async {},
    );
    expect(outcome, PendingSettleOutcome.unknown);
    expect(store.load('user-1'), isNotNull);
  });

  test('already stopped earlier (web or previous run) clears without a new stop',
      () async {
    final store = await _store();
    var stops = 0;
    final outcome = await settleClosedCheckout(
      payment: _payment,
      store: store,
      readRecovery: (_, __) async => _stopped(),
      abandon: (_, __) async {
        stops++;
        return _stopped();
      },
      sleep: (_) async {},
    );
    expect(outcome, PendingSettleOutcome.cleared);
    expect(stops, 0);
    expect(store.load('user-1'), isNull);
  });

  test('read-only mode (fresh record on Home) never stops a ready order',
      () async {
    final store = await _store();
    var stops = 0;
    final outcome = await settleClosedCheckout(
      payment: _payment,
      store: store,
      readRecovery: (_, __) async => _ready(),
      abandon: (_, __) async {
        stops++;
        return _stopped();
      },
      allowAbandon: false,
      sleep: (_) async {},
    );
    expect(outcome, PendingSettleOutcome.unknown);
    expect(stops, 0);
    expect(store.load('user-1'), isNotNull);
  });
}
