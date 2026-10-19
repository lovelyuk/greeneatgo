import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

const pendingPaymentSchemaVersion = 1;
const pendingPaymentStaleAfter = Duration(days: 7);

String pendingPaymentStorageKey(String uid) =>
    'pending_payment_v1:${base64Url.encode(utf8.encode(uid)).replaceAll('=', '')}';

enum PendingPaymentValidity { valid, stale, malformed }

class PendingPayment {
  const PendingPayment({
    required this.uid,
    required this.orderId,
    required this.amount,
    required this.createdAt,
  });

  final String uid;
  final String orderId;
  final int amount;
  final DateTime createdAt;

  String get fingerprint =>
      '$uid:$orderId:${createdAt.toUtc().toIso8601String()}';

  Map<String, Object> toMap() => <String, Object>{
        'version': pendingPaymentSchemaVersion,
        'uid': uid,
        'orderId': orderId,
        'amount': amount,
        'createdAt': createdAt.toUtc().toIso8601String(),
      };

  String toJson() => jsonEncode(toMap());

  static PendingPayment? tryParse(String raw, {required String expectedUid}) {
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return null;
      final map = decoded.cast<String, dynamic>();
      final uid = map['uid'];
      final orderId = map['orderId'];
      final amount = map['amount'];
      final createdAt = map['createdAt'];
      if (map['version'] != pendingPaymentSchemaVersion ||
          uid is! String ||
          uid.trim().isEmpty ||
          uid != expectedUid ||
          orderId is! String ||
          orderId.trim().isEmpty ||
          amount is! num ||
          amount != amount.round() ||
          amount <= 0 ||
          createdAt is! String) {
        return null;
      }
      final parsedAt = DateTime.tryParse(createdAt);
      if (parsedAt == null) return null;
      return PendingPayment(
        uid: uid,
        orderId: orderId.trim(),
        amount: amount.round(),
        createdAt: parsedAt.toUtc(),
      );
    } catch (_) {
      return null;
    }
  }
}

class PendingPaymentLoadResult {
  const PendingPaymentLoadResult._({
    required this.validity,
    required this.raw,
    this.payment,
  });

  factory PendingPaymentLoadResult.fromRaw(
    String raw, {
    required String expectedUid,
    required DateTime now,
  }) {
    final payment = PendingPayment.tryParse(raw, expectedUid: expectedUid);
    if (payment == null ||
        payment.createdAt
            .isAfter(now.toUtc().add(const Duration(minutes: 5)))) {
      return PendingPaymentLoadResult._(
        validity: PendingPaymentValidity.malformed,
        raw: raw,
      );
    }
    final age = now.toUtc().difference(payment.createdAt);
    return PendingPaymentLoadResult._(
      validity: age > pendingPaymentStaleAfter
          ? PendingPaymentValidity.stale
          : PendingPaymentValidity.valid,
      raw: raw,
      payment: payment,
    );
  }

  final PendingPaymentValidity validity;
  final PendingPayment? payment;

  /// Retained so malformed potentially-paid records remain visible and are not
  /// silently destroyed by a parser or migration failure.
  final String raw;
}

abstract class PendingPaymentPreferences {
  String? getString(String key);
  Future<bool> setString(String key, String value);
  Future<bool> remove(String key);
}

class SharedPreferencesPendingPaymentPreferences
    implements PendingPaymentPreferences {
  SharedPreferencesPendingPaymentPreferences(this.preferences);

  final SharedPreferences preferences;

  @override
  String? getString(String key) => preferences.getString(key);

  @override
  Future<bool> remove(String key) => preferences.remove(key);

  @override
  Future<bool> setString(String key, String value) =>
      preferences.setString(key, value);
}

class PendingPaymentStore {
  PendingPaymentStore(this.preferences, {DateTime Function()? now})
      : _now = now ?? DateTime.now;

  final PendingPaymentPreferences preferences;
  final DateTime Function() _now;

  static Future<PendingPaymentStore> create() async => PendingPaymentStore(
        SharedPreferencesPendingPaymentPreferences(
          await SharedPreferences.getInstance(),
        ),
      );

  Future<void> save(PendingPayment payment) async {
    if (payment.uid.trim().isEmpty ||
        payment.orderId.trim().isEmpty ||
        payment.amount <= 0) {
      throw ArgumentError('Invalid pending payment');
    }
    final saved = await preferences.setString(
      pendingPaymentStorageKey(payment.uid),
      payment.toJson(),
    );
    if (!saved) throw StateError('Pending payment could not be saved');
  }

  PendingPaymentLoadResult? load(String uid) {
    if (uid.trim().isEmpty) return null;
    final raw = preferences.getString(pendingPaymentStorageKey(uid));
    if (raw == null) return null;
    return PendingPaymentLoadResult.fromRaw(
      raw,
      expectedUid: uid,
      now: _now(),
    );
  }

  /// Compare-before-remove prevents an old confirmation response from deleting
  /// a newer order for the same user.
  Future<bool> clear(PendingPayment payment) async {
    final key = pendingPaymentStorageKey(payment.uid);
    final current = preferences.getString(key);
    final parsed = current == null
        ? null
        : PendingPayment.tryParse(current, expectedUid: payment.uid);
    if (parsed?.fingerprint != payment.fingerprint) return false;
    return preferences.remove(key);
  }
}


/// Reads `GET /payments/recovery?order_id&amount` (server order state).
typedef PendingRecoveryReader = Future<Map<String, dynamic>> Function(
    String orderId, int amount);

/// Calls `POST /payments/orders/{id}/abandon` with
/// `explicit_checkout_cancel_intent: true` (owner stopped the checkout).
typedef PendingOrderAbandoner = Future<Map<String, dynamic>> Function(
    String orderId, int amount);

enum PendingSettleOutcome {
  /// Server holds an owner stop receipt / verified closure → record removed.
  cleared,

  /// Server says the order was paid → keep the record so Home confirms it.
  paid,

  /// Could not prove either way → keep the record (banner stays).
  unknown,
}

/// After the buyer closes the Kiwoom checkout without paying, retire the local
/// "결제 승인을 확인하고 있어요" record the same way web /shop does:
/// read the server order, give a just-finished approval a moment to land,
/// then record an explicit owner stop. The record is removed only when the
/// server returns a stop receipt (`locally_abandoned`) or a verified closure
/// (`closed`); a paid order, a late-approval contradiction or any error keeps
/// it so a real charge can never be hidden.
Future<PendingSettleOutcome> settleClosedCheckout({
  required PendingPayment payment,
  required PendingPaymentStore store,
  required PendingRecoveryReader readRecovery,
  required PendingOrderAbandoner abandon,
  bool allowAbandon = true,
  Duration settleDelay = const Duration(seconds: 2),
  Future<void> Function(Duration)? sleep,
}) async {
  final wait = sleep ?? (d) => Future<void>.delayed(d);
  bool retired(Map<String, dynamic> r) {
    final action = r['recovery_action'];
    return r['checkout_url'] == null &&
        r['completion'] == null &&
        r['status'] != 'done' &&
        (action == 'locally_abandoned' ||
            (action == 'closed' && r['closure'] is Map));
  }

  try {
    var result = await readRecovery(payment.orderId, payment.amount);
    if (result['status'] == 'ready' && result['local_abandonment'] == null) {
      await wait(settleDelay);
      result = await readRecovery(payment.orderId, payment.amount);
    }
    if (result['status'] == 'done') return PendingSettleOutcome.paid;
    if (!retired(result)) {
      final stoppable = result['local_abandonment'] == null &&
          {'ready', 'failed', 'canceled'}.contains(result['status']) &&
          result['recovery_action'] == 'reconcile';
      if (!allowAbandon || !stoppable) return PendingSettleOutcome.unknown;
      result = await abandon(payment.orderId, payment.amount);
      if (result['status'] == 'done') return PendingSettleOutcome.paid;
      if (!retired(result)) return PendingSettleOutcome.unknown;
    }
    await store.clear(payment);
    return PendingSettleOutcome.cleared;
  } catch (_) {
    return PendingSettleOutcome.unknown;
  }
}
