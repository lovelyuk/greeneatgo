import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

String normalizePhoneNumber(String value) => value.replaceAll(RegExp(r'[^0-9]'), '');

bool isValidPhoneNumber(String value) =>
    RegExp(r'^010[0-9]{8}$').hasMatch(normalizePhoneNumber(value));

bool isValidOtpCode(String value) => RegExp(r'^[0-9]{6}$').hasMatch(value);

abstract interface class PhoneAuthGateway {
  Future<PhoneSendResult> sendCode(String phone);

  Future<PhoneVerifyResult> verifyCode(String phone, String code);

  Future<String> signup(String verificationToken, String displayName);
}

class PhoneSendResult {
  const PhoneSendResult({required this.expiresIn, required this.resendAfter});

  final int expiresIn;
  final int resendAfter;
}

sealed class PhoneVerifyResult {
  const PhoneVerifyResult();
}

class ExistingPhoneAccount extends PhoneVerifyResult {
  const ExistingPhoneAccount(this.customToken);

  final String customToken;
}

class NewPhoneAccount extends PhoneVerifyResult {
  const NewPhoneAccount(this.verificationToken, {required this.expiresIn});

  final String verificationToken;
  final int expiresIn;
}

class PhoneAuthException implements Exception {
  const PhoneAuthException(this.message, {this.code, this.retryAfter});

  final String message;
  final String? code;
  final int? retryAfter;

  @override
  String toString() => message;
}

class HttpPhoneAuthGateway implements PhoneAuthGateway {
  HttpPhoneAuthGateway({
    required this.baseUrl,
    http.Client? client,
    this.requestTimeout = const Duration(seconds: 60),
  }) : _client = client ?? http.Client();

  final String baseUrl;
  final Duration requestTimeout;
  final http.Client _client;

  void close() => _client.close();

  @override
  Future<PhoneSendResult> sendCode(String phone) async {
    final data = await _post('/auth/phone/send', {
      'phone': normalizePhoneNumber(phone),
      'purpose': 'signup_login',
    });
    return PhoneSendResult(
      expiresIn: _positiveInt(data['expires_in'], fallback: 180),
      resendAfter: _positiveInt(data['resend_after'], fallback: 60),
    );
  }

  @override
  Future<PhoneVerifyResult> verifyCode(String phone, String code) async {
    final data = await _post('/auth/phone/verify', {
      'phone': normalizePhoneNumber(phone),
      'code': code,
      'purpose': 'signup_login',
    });
    if (data['status'] == 'existing') {
      final customToken = data['custom_token'];
      if (customToken is String && customToken.isNotEmpty) {
        return ExistingPhoneAccount(customToken);
      }
    } else if (data['status'] == 'new') {
      final verificationToken = data['verification_token'];
      if (verificationToken is String && verificationToken.isNotEmpty) {
        return NewPhoneAccount(
          verificationToken,
          expiresIn: _positiveInt(data['expires_in'], fallback: 300),
        );
      }
    }
    throw const PhoneAuthException('인증 결과를 확인할 수 없어요. 다시 시도해 주세요.');
  }

  @override
  Future<String> signup(String verificationToken, String displayName) async {
    final data = await _post('/auth/phone/signup', {
      'verification_token': verificationToken,
      'display_name': displayName.trim(),
    });
    final customToken = data['custom_token'];
    if (customToken is String && customToken.isNotEmpty) return customToken;
    throw const PhoneAuthException('회원가입 결과를 확인할 수 없어요. 다시 시도해 주세요.');
  }

  Future<Map<String, dynamic>> _post(
      String path, Map<String, dynamic> body) async {
    http.Response response;
    try {
      response = await _client.post(
        Uri.parse('$baseUrl$path'),
        headers: const {'Content-Type': 'application/json'},
        body: jsonEncode(body),
      ).timeout(requestTimeout);
    } on TimeoutException {
      throw const PhoneAuthException(
        '서버 응답이 늦어지고 있어요.',
        code: 'REQUEST_TIMEOUT',
      );
    } on PhoneAuthException {
      rethrow;
    } catch (_) {
      throw const PhoneAuthException('네트워크 연결을 확인한 뒤 다시 시도해 주세요.');
    }

    Map<String, dynamic>? decoded;
    try {
      final value = jsonDecode(response.body);
      if (value is Map) decoded = value.cast<String, dynamic>();
    } catch (_) {
      // A malformed response is handled as a service error below.
    }

    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = decoded?['detail'];
      final detailMap = detail is Map ? detail.cast<String, dynamic>() : null;
      throw PhoneAuthException(
        (detailMap?['message'] ?? '휴대폰 인증 처리 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요.')
            .toString(),
        code: detailMap?['code']?.toString(),
        retryAfter: _nullablePositiveInt(detailMap?['retry_after']),
      );
    }

    final data = decoded?['data'];
    if (decoded?['ok'] != true || data is! Map) {
      throw const PhoneAuthException('인증 서버 응답을 확인할 수 없어요. 잠시 후 다시 시도해 주세요.');
    }
    return data.cast<String, dynamic>();
  }

  static int _positiveInt(Object? value, {required int fallback}) =>
      _nullablePositiveInt(value) ?? fallback;

  static int? _nullablePositiveInt(Object? value) {
    final parsed = value is int ? value : int.tryParse(value?.toString() ?? '');
    return parsed != null && parsed > 0 ? parsed : null;
  }
}
