import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:greeneatgo_customer/phone_auth.dart';
import 'package:greeneatgo_customer/phone_login_screen.dart';

class FakePhoneAuthGateway implements PhoneAuthGateway {
  PhoneSendResult sendResult =
      const PhoneSendResult(expiresIn: 180, resendAfter: 2);
  PhoneVerifyResult verifyResult = const ExistingPhoneAccount('existing-token');
  String signupResult = 'signup-token';
  PhoneAuthException? sendError;
  final List<String> sentPhones = [];
  final List<(String, String)> verifications = [];
  final List<(String, String)> signups = [];

  @override
  Future<PhoneSendResult> sendCode(String phone) async {
    sentPhones.add(phone);
    final error = sendError;
    if (error != null) throw error;
    return sendResult;
  }

  @override
  Future<PhoneVerifyResult> verifyCode(String phone, String code) async {
    verifications.add((phone, code));
    return verifyResult;
  }

  @override
  Future<String> signup(String verificationToken, String displayName) async {
    signups.add((verificationToken, displayName));
    return signupResult;
  }
}

Widget harness(
  FakePhoneAuthGateway gateway, {
  List<String>? signedTokens,
  CustomTokenSignIn? signInWithCustomToken,
  VoidCallback? onLoggedIn,
  double textScaleFactor = 1,
}) {
  return MaterialApp(
    builder: (context, child) => MediaQuery(
      data: MediaQuery.of(context).copyWith(
        textScaler: TextScaler.linear(textScaleFactor),
      ),
      child: child!,
    ),
    home: PhoneLoginScreen(
      gateway: gateway,
      signInWithCustomToken:
          signInWithCustomToken ?? (token) async => signedTokens?.add(token),
      onLoggedIn: () async => onLoggedIn?.call(),
      openLegalDocument: (_) async {},
    ),
  );
}

void main() {
  test('phone and OTP helpers normalize and strictly validate Korean numbers',
      () {
    expect(normalizePhoneNumber(' 010-1234 5678 '), '01012345678');
    expect(isValidPhoneNumber('010-1234-5678'), isTrue);
    expect(isValidPhoneNumber('011-1234-5678'), isFalse);
    expect(isValidPhoneNumber('010-123-4567'), isFalse);
    expect(isValidOtpCode('123456'), isTrue);
    expect(isValidOtpCode('12345a'), isFalse);
  });

  test('HTTP gateway follows envelope, route, and existing-account contract',
      () async {
    late http.Request request;
    final gateway = HttpPhoneAuthGateway(
      baseUrl: 'https://api.example/v1',
      client: MockClient((incoming) async {
        request = incoming;
        return http.Response(
          jsonEncode({
            'ok': true,
            'data': {
              'status': 'existing',
              'custom_token': 'firebase-custom-token'
            },
            'error': null,
          }),
          200,
        );
      }),
    );

    final result = await gateway.verifyCode('010-1234-5678', '123456');
    expect(request.url.toString(), 'https://api.example/v1/auth/phone/verify');
    expect(jsonDecode(request.body), {
      'phone': '01012345678',
      'code': '123456',
      'purpose': 'signup_login',
    });
    expect(result, isA<ExistingPhoneAccount>());
    expect(
        (result as ExistingPhoneAccount).customToken, 'firebase-custom-token');
  });

  test('HTTP gateway uses the exact send route and request body', () async {
    late http.Request request;
    final gateway = HttpPhoneAuthGateway(
      baseUrl: 'https://api.example/v1',
      client: MockClient((incoming) async {
        request = incoming;
        return http.Response(
          jsonEncode({
            'ok': true,
            'data': {'expires_in': 180, 'resend_after': 60},
            'error': null,
          }),
          200,
        );
      }),
    );

    await gateway.sendCode('010-1234-5678');

    expect(request.method, 'POST');
    expect(request.url.toString(), 'https://api.example/v1/auth/phone/send');
    expect(jsonDecode(request.body), {
      'phone': '01012345678',
      'purpose': 'signup_login',
    });
  });

  test('HTTP gateway uses the exact signup route and request body', () async {
    late http.Request request;
    final gateway = HttpPhoneAuthGateway(
      baseUrl: 'https://api.example/v1',
      client: MockClient((incoming) async {
        request = incoming;
        return http.Response(
          jsonEncode({
            'ok': true,
            'data': {'custom_token': 'signup-custom-token'},
            'error': null,
          }),
          200,
        );
      }),
    );

    final token = await gateway.signup('verification-token', ' 홍길동 ');

    expect(request.method, 'POST');
    expect(request.url.toString(), 'https://api.example/v1/auth/phone/signup');
    expect(jsonDecode(request.body), {
      'verification_token': 'verification-token',
      'display_name': '홍길동',
    });
    expect(token, 'signup-custom-token');
  });

  test('HTTP gateway retains backend Korean error and retry cooldown',
      () async {
    final gateway = HttpPhoneAuthGateway(
      baseUrl: 'https://api.example/v1',
      client: MockClient((_) async => http.Response(
            jsonEncode({
              'detail': {
                'code': 'RATE_LIMITED',
                'message': '잠시 후 다시 시도해 주세요',
                'retry_after': 37,
              }
            }),
            429,
            headers: const {'content-type': 'application/json; charset=utf-8'},
          )),
    );

    await expectLater(
      gateway.sendCode('01012345678'),
      throwsA(isA<PhoneAuthException>()
          .having((e) => e.code, 'code', 'RATE_LIMITED')
          .having((e) => e.retryAfter, 'retryAfter', 37)
          .having((e) => e.message, 'message', '잠시 후 다시 시도해 주세요')),
    );
  });

  test('HTTP gateway marks a request timeout as an unknown send outcome',
      () async {
    final gateway = HttpPhoneAuthGateway(
      baseUrl: 'https://api.example/v1',
      requestTimeout: const Duration(milliseconds: 5),
      client: MockClient((_) => Completer<http.Response>().future),
    );

    await expectLater(
      gateway.sendCode('01012345678'),
      throwsA(isA<PhoneAuthException>()
          .having((error) => error.code, 'code', 'REQUEST_TIMEOUT')
          .having(
            (error) => error.message,
            'message',
            '서버 응답이 늦어지고 있어요.',
          )),
    );
  });

  test('HTTP gateway rejects a malformed success response safely', () async {
    final gateway = HttpPhoneAuthGateway(
      baseUrl: 'https://api.example/v1',
      client: MockClient((_) async => http.Response(
            jsonEncode({'ok': true, 'data': 'not-an-object'}),
            200,
          )),
    );

    await expectLater(
      gateway.sendCode('01012345678'),
      throwsA(isA<PhoneAuthException>().having(
        (error) => error.message,
        'message',
        '인증 서버 응답을 확인할 수 없어요. 잠시 후 다시 시도해 주세요.',
      )),
    );
  });

  testWidgets('send then verify existing account signs in with custom token',
      (tester) async {
    final gateway = FakePhoneAuthGateway();
    final signedTokens = <String>[];
    var loggedIn = false;
    await tester.pumpWidget(harness(gateway,
        signedTokens: signedTokens, onLoggedIn: () => loggedIn = true));

    await tester.enterText(
        find.byKey(const Key('phone-input')), '010-1234-5678');
    await tester.pump();
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();

    expect(gateway.sentPhones, ['01012345678']);
    expect(find.byKey(const Key('otp-input')), findsOneWidget);
    expect(find.textContaining('다시 받기 (2초)'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('otp-input')), '123456');
    await tester.pump();
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();

    expect(gateway.verifications, [('01012345678', '123456')]);
    expect(signedTokens, ['existing-token']);
    expect(loggedIn, isTrue);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
      'unknown send outcome still opens OTP entry when the SMS may have arrived',
      (tester) async {
    final gateway = FakePhoneAuthGateway()
      ..sendError = const PhoneAuthException(
        '서버 응답이 늦어지고 있어요.',
        code: 'REQUEST_TIMEOUT',
      );
    await tester.pumpWidget(harness(gateway));

    await tester.enterText(find.byKey(const Key('phone-input')), '01012345678');
    await tester.pump();
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();

    expect(find.byKey(const Key('otp-input')), findsOneWidget);
    expect(find.textContaining('문자가 도착했다면 인증번호 6자리를 입력'), findsOneWidget);
    expect(find.textContaining('네트워크 연결'), findsNothing);
    expect(find.textContaining('다시 받기 (60초)'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
      'custom-token sign-in failure shows a safe error and restores controls',
      (tester) async {
    final gateway = FakePhoneAuthGateway();
    var loggedIn = false;
    await tester.pumpWidget(harness(
      gateway,
      signInWithCustomToken: (_) async {
        throw StateError('sensitive Firebase authentication detail');
      },
      onLoggedIn: () => loggedIn = true,
    ));

    await tester.enterText(find.byKey(const Key('phone-input')), '01012345678');
    await tester.pump();
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('otp-input')), '123456');
    await tester.pump();
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();

    expect(
      find.text('인증 처리 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요.'),
      findsOneWidget,
    );
    expect(find.textContaining('sensitive Firebase'), findsNothing);
    expect(find.text('인증하고 시작하기'), findsOneWidget);
    expect(
      tester
          .widget<FilledButton>(find.byKey(const Key('phone-auth-primary')))
          .onPressed,
      isNotNull,
    );
    expect(loggedIn, isFalse);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('new account verification requests name then signs up',
      (tester) async {
    final gateway = FakePhoneAuthGateway()
      ..verifyResult = const NewPhoneAccount(
          'raw-verification-token-which-is-long',
          expiresIn: 300);
    final signedTokens = <String>[];
    var loggedIn = false;
    await tester.pumpWidget(harness(gateway,
        signedTokens: signedTokens, onLoggedIn: () => loggedIn = true));

    await tester.enterText(find.byKey(const Key('phone-input')), '01099998888');
    await tester.pump();
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('otp-input')), '654321');
    await tester.pump();
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();

    expect(find.byKey(const Key('name-input')), findsOneWidget);
    expect(find.byKey(const Key('phone-input')), findsNothing);
    expect(find.byKey(const Key('otp-input')), findsNothing);
    expect(find.byType(EditableText), findsOneWidget);
    expect(
      tester.widget<Text>(find.byKey(const Key('signup-phone-value'))).data,
      '01099998888',
    );
    expect(find.text('인증완료'), findsOneWidget);
    expect(find.text('가입하고 시작하기'), findsOneWidget);
    expect(find.textContaining('처음 이용'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('name-input')), ' 홍길동 ');
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();

    expect(gateway.signups, [('raw-verification-token-which-is-long', '홍길동')]);
    expect(gateway.sentPhones, ['01099998888']);
    expect(gateway.verifications, [('01099998888', '654321')]);
    expect(signedTokens, ['signup-token']);
    expect(loggedIn, isTrue);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
      'new-account screen uses exact navy/lime tokens at 360x640 and 1.3 text scale',
      (tester) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final gateway = FakePhoneAuthGateway()
      ..verifyResult =
          const NewPhoneAccount('verification-token', expiresIn: 300);
    await tester.pumpWidget(harness(gateway, textScaleFactor: 1.3));

    await tester.enterText(find.byKey(const Key('phone-input')), '01099998888');
    await tester.pump();
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('otp-input')), '654321');
    await tester.pump();
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();

    final scaffold =
        tester.widget<Scaffold>(find.byKey(const Key('signup-screen')));
    final primary = tester
        .widget<FilledButton>(find.byKey(const Key('phone-auth-primary')));
    final surface = tester
        .widget<Container>(find.byKey(const Key('signup-decor-surface')))
        .decoration! as BoxDecoration;
    final surfaceAlt = tester
        .widget<Container>(find.byKey(const Key('signup-decor-surface-alt')))
        .decoration! as BoxDecoration;
    final divider =
        tester.widget<Divider>(find.byKey(const Key('signup-phone-divider')));
    final name = tester.widget<TextField>(find.byKey(const Key('name-input')));
    final enabledBorder =
        name.decoration!.enabledBorder! as UnderlineInputBorder;

    expect(scaffold.backgroundColor, const Color(0xFF0E1C2B));
    expect(surface.color, const Color(0xFF16293C));
    expect(surfaceAlt.color, const Color(0xFF14283A));
    expect(divider.color, const Color(0xFF2A3B4F));
    expect(enabledBorder.borderSide.color, const Color(0xFF2A3B4F));
    expect(
        primary.style!.backgroundColor!.resolve({}), const Color(0xFF9DBF63));
    expect(
        primary.style!.foregroundColor!.resolve({}), const Color(0xFF0E1C2B));
    expect(find.byType(EditableText), findsOneWidget);
    expect(tester.takeException(), isNull);

    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('invalid phone, OTP, and empty name show validation errors',
      (tester) async {
    final gateway = FakePhoneAuthGateway()
      ..verifyResult =
          const NewPhoneAccount('verification-token', expiresIn: 300);
    await tester.pumpWidget(harness(gateway));

    await tester.enterText(
        find.byKey(const Key('phone-input')), '010-123-4567');
    await tester.pump();
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();
    expect(find.text('올바른 010 휴대폰 번호를 입력해 주세요.'), findsOneWidget);
    expect(gateway.sentPhones, isEmpty);

    await tester.enterText(
        find.byKey(const Key('phone-input')), '010-1234-5678');
    await tester.pump();
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('otp-input')), '12345');
    await tester.pump();
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();
    expect(find.text('인증번호 6자리를 입력해 주세요.'), findsOneWidget);
    expect(gateway.verifications, isEmpty);

    await tester.enterText(find.byKey(const Key('otp-input')), '123456');
    await tester.pump();
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();
    expect(find.byKey(const Key('name-input')), findsOneWidget);
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();
    expect(find.text('이름은 1자 이상 20자 이하로 입력해 주세요.'), findsOneWidget);
    expect(gateway.signups, isEmpty);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('rate-limit error displays backend message and retry countdown',
      (tester) async {
    final gateway = FakePhoneAuthGateway()
      ..sendError = const PhoneAuthException('잠시 후 다시 시도해 주세요',
          code: 'RATE_LIMITED', retryAfter: 3);
    await tester.pumpWidget(harness(gateway));
    await tester.enterText(find.byKey(const Key('phone-input')), '01012345678');
    await tester.pump();
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();

    expect(find.text('잠시 후 다시 시도해 주세요'), findsOneWidget);
    expect(find.text('3초 후 다시 시도'), findsOneWidget);
    expect(
        tester
            .widget<FilledButton>(find.byKey(const Key('phone-auth-primary')))
            .onPressed,
        isNull);
    await tester.pump(const Duration(seconds: 3));
    gateway.sendError = null;
    await tester.tap(find.byKey(const Key('phone-auth-primary')));
    await tester.pump();
    expect(find.textContaining('다시 받기 (2초)'), findsOneWidget);
    expect(
        tester
            .widget<TextButton>(find.byKey(const Key('resend-button')))
            .onPressed,
        isNull);

    await tester.pump(const Duration(seconds: 2));
    expect(find.text('인증번호 다시 받기'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });
}
