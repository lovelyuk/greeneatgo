import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _defaultAuthError = '인증 처리 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요.';

String friendlyFirebaseAuthCode(String code) {
  return switch (code) {
    'invalid-email' => '올바른 이메일 주소를 입력해 주세요.',
    'invalid-credential' ||
    'wrong-password' ||
    'user-not-found' =>
      '이메일 또는 비밀번호가 올바르지 않아요.',
    'email-already-in-use' => '이미 가입된 이메일이에요. 로그인해 주세요.',
    'weak-password' => '더 안전한 비밀번호를 사용해 주세요. 비밀번호는 6자 이상이어야 해요.',
    'user-disabled' => '사용이 중지된 계정이에요. 고객센터에 문의해 주세요.',
    'too-many-requests' => '요청이 너무 많아요. 잠시 후 다시 시도해 주세요.',
    'network-request-failed' => '네트워크 연결을 확인한 뒤 다시 시도해 주세요.',
    'requires-recent-login' => '보안을 위해 현재 비밀번호로 다시 인증해 주세요.',
    'operation-not-allowed' => '현재 사용할 수 없는 로그인 방식이에요. 고객센터에 문의해 주세요.',
    _ => _defaultAuthError,
  };
}

String friendlyFirebaseAuthError(Object error) {
  if (error is FirebaseAuthException) {
    return friendlyFirebaseAuthCode(error.code);
  }
  return _defaultAuthError;
}

bool isValidEmail(String value) =>
    RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$').hasMatch(value.trim());

String normalizeSignupEmail(String email) => email.trim().toLowerCase();

String pendingSignupProfileKey(String email) =>
    'pending_signup_profile:${normalizeSignupEmail(email)}';

String signupDisplayName({
  String? sessionDisplayName,
  String? meDisplayName,
  String? pendingDisplayName,
}) {
  for (final candidate in [
    sessionDisplayName,
    meDisplayName,
    pendingDisplayName,
  ]) {
    final value = candidate?.trim() ?? '';
    if (value.isNotEmpty) return value;
  }
  return '';
}

String normalizeSignupPhone(String phone) =>
    phone.trim().replaceAll(RegExp(r'[\s-]'), '');

bool isValidSignupPhone(String phone) =>
    RegExp(r'^010\d{8}$').hasMatch(normalizeSignupPhone(phone));

class PendingSignupProfile {
  const PendingSignupProfile(
      {required this.uid, required this.displayName, required this.phone});

  final String uid;
  final String displayName;
  final String phone;

  String toJson() => jsonEncode({
        'uid': uid.trim(),
        'display_name': displayName.trim(),
        'phone': normalizeSignupPhone(phone),
      });

  static PendingSignupProfile? fromJson(String value) {
    try {
      final decoded = jsonDecode(value);
      if (decoded is! Map<String, dynamic>) return null;
      final uid = decoded['uid'];
      final displayName = decoded['display_name'];
      final phone = decoded['phone'];
      if (uid is! String ||
          displayName is! String ||
          (phone != null && phone is! String)) {
        return null;
      }
      final normalizedUid = uid.trim();
      final normalizedName = displayName.trim();
      if (normalizedUid.isEmpty || normalizedName.isEmpty) return null;
      return PendingSignupProfile(
          uid: normalizedUid,
          displayName: normalizedName,
          phone: normalizeSignupPhone(phone as String? ?? ''));
    } catch (_) {
      return null;
    }
  }
}

Future<void> savePendingSignupProfile({
  required String uid,
  required String email,
  required String displayName,
  required String phone,
}) async {
  final preferences = await SharedPreferences.getInstance();
  final saved = await preferences.setString(
    pendingSignupProfileKey(email),
    PendingSignupProfile(uid: uid, displayName: displayName, phone: phone)
        .toJson(),
  );
  if (!saved) throw StateError('Pending sign-up profile could not be saved.');
}

Future<PendingSignupProfile?> loadPendingSignupProfile(
    {required String uid, required String email}) async {
  final preferences = await SharedPreferences.getInstance();
  final key = pendingSignupProfileKey(email);
  final value = preferences.getString(key);
  if (value == null) return null;
  final profile = PendingSignupProfile.fromJson(value);
  if (profile?.uid == uid) return profile;
  await preferences.remove(key);
  return null;
}

Future<void> clearPendingSignupProfile(String email) async {
  final preferences = await SharedPreferences.getInstance();
  final key = pendingSignupProfileKey(email);
  final removed = await preferences.remove(key);
  if (!removed && preferences.containsKey(key)) {
    throw StateError('Pending sign-up profile could not be cleared.');
  }
}
