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
