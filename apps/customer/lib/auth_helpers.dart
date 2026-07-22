import 'package:firebase_auth/firebase_auth.dart';

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
