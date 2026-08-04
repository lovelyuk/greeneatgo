import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:greeneatgo_customer/main.dart';
import 'package:greeneatgo_customer/phone_auth.dart';
import 'package:greeneatgo_customer/phone_login_screen.dart';
import 'package:greeneatgo_customer/theme/app_colors.dart';

class _FakeGateway implements PhoneAuthGateway {
  @override
  Future<PhoneSendResult> sendCode(String phone) async =>
      const PhoneSendResult(expiresIn: 180, resendAfter: 60);

  @override
  Future<PhoneVerifyResult> verifyCode(String phone, String code) async =>
      const ExistingPhoneAccount('token');

  @override
  Future<String> signup(String verificationToken, String displayName) async =>
      'token';
}

Widget _phoneHarness({double textScale = 1}) => MaterialApp(
      theme: ThemeData(fontFamily: 'Pretendard'),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(
          textScaler: TextScaler.linear(textScale),
        ),
        child: child!,
      ),
      home: PhoneLoginScreen(
        gateway: _FakeGateway(),
        signInWithCustomToken: (_) async {},
        onLoggedIn: () async {},
        openLegalDocument: (_) async {},
      ),
    );

void _setSurface(WidgetTester tester, Size size) {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

void main() {
  setUpAll(() async {
    final pretendard = FontLoader('Pretendard')
      ..addFont(rootBundle.load('assets/fonts/Pretendard-Regular.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-SemiBold.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-Bold.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-ExtraBold.otf'));
    final materialIcons = FontLoader('MaterialIcons')
      ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await Future.wait([pretendard.load(), materialIcons.load()]);
  });

  for (final size in const [Size(360, 640), Size(430, 932)]) {
    testWidgets(
        'splash has exact dark geometry at ${size.width.toInt()}x${size.height.toInt()}',
        (tester) async {
      _setSurface(tester, size);
      await tester.pumpWidget(
        MaterialApp(
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context).copyWith(
              textScaler: const TextScaler.linear(1.3),
            ),
            child: child!,
          ),
          home: const BrandLoadingScreen(),
        ),
      );

      expect(
        tester
            .widget<Scaffold>(find.byKey(const Key('brand-loading-screen')))
            .backgroundColor,
        AppColors.navyBase,
      );
      expect(tester.getSize(find.byKey(const Key('splash-logo'))).width, 112);
      expect(tester.getSize(find.byKey(const Key('splash-spinner'))),
          const Size.square(26));
      final spinner = tester.widget<CircularProgressIndicator>(
          find.byKey(const Key('splash-spinner')));
      expect(spinner.color, AppColors.limeGreen);
      expect(spinner.backgroundColor, AppColors.spinnerTrack);
      final top =
          tester.widget<Positioned>(find.byKey(const Key('splash-circle-top')));
      final bottom = tester
          .widget<Positioned>(find.byKey(const Key('splash-circle-bottom')));
      expect((top.top, top.right), (-52, -52));
      expect((bottom.bottom, bottom.left), (-60, -60));
      expect(tester.takeException(), isNull);
    });

    testWidgets(
        'phone and OTP dark UI is responsive at ${size.width.toInt()}x${size.height.toInt()}',
        (tester) async {
      _setSurface(tester, size);
      await tester.pumpWidget(_phoneHarness(textScale: 1.3));

      final scaffold =
          tester.widget<Scaffold>(find.byKey(const Key('phone-login-screen')));
      expect(scaffold.backgroundColor, AppColors.navyBase);
      expect(tester.getSize(find.byKey(const Key('login-logo'))).width, 78);
      expect(find.text('휴대폰 번호로\n간편하게 시작하세요'), findsOneWidget);
      final button = tester
          .widget<FilledButton>(find.byKey(const Key('phone-auth-primary')));
      expect(button.onPressed, isNull);
      expect(button.style!.backgroundColor!.resolve({WidgetState.disabled}),
          AppColors.navyBorder);
      expect(button.style!.foregroundColor!.resolve({WidgetState.disabled}),
          AppColors.textPlaceholder);

      await tester.enterText(
          find.byKey(const Key('phone-input')), '010-1234-5678');
      await tester.pump();
      expect(
          tester
              .widget<FilledButton>(find.byKey(const Key('phone-auth-primary')))
              .onPressed,
          isNotNull);
      expect(
          tester
              .widget<FilledButton>(find.byKey(const Key('phone-auth-primary')))
              .style!
              .backgroundColor!
              .resolve({}),
          AppColors.limeGreen);

      await tester.tap(find.byKey(const Key('phone-auth-primary')));
      await tester.pump();
      expect(find.byKey(const Key('otp-input')), findsOneWidget);
      expect(find.byKey(const Key('change-phone-button')), findsOneWidget);
      expect(find.byKey(const Key('resend-button')), findsOneWidget);
      expect(find.textContaining('인증번호 다시 받기 (60초)'), findsOneWidget);
      expect(
          tester
              .widget<FilledButton>(find.byKey(const Key('phone-auth-primary')))
              .onPressed,
          isNull);
      await tester.enterText(find.byKey(const Key('otp-input')), '123456');
      await tester.pump();
      expect(
          tester
              .widget<FilledButton>(find.byKey(const Key('phone-auth-primary')))
              .onPressed,
          isNotNull);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }

  testWidgets('production phone widget golden at 430x932', (tester) async {
    _setSurface(tester, const Size(430, 932));
    await tester.pumpWidget(_phoneHarness());
    await expectLater(
      find.byKey(const Key('phone-login-screen')),
      matchesGoldenFile('goldens/dark_phone_login_430x932.png'),
    );
  });
}
