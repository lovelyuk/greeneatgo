import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'phone_auth.dart';
import 'theme/app_colors.dart';

typedef CustomTokenSignIn = Future<void> Function(String customToken);
typedef LegalDocumentOpener = Future<void> Function(String filename);

enum PhoneLoginStep { phone, code, name }

class PhoneLoginScreen extends StatefulWidget {
  const PhoneLoginScreen({
    super.key,
    required this.gateway,
    required this.signInWithCustomToken,
    required this.onLoggedIn,
    required this.openLegalDocument,
    this.brandHeader,
  });

  final PhoneAuthGateway gateway;
  final CustomTokenSignIn signInWithCustomToken;
  final Future<void> Function() onLoggedIn;
  final LegalDocumentOpener openLegalDocument;
  final Widget? brandHeader;

  @override
  State<PhoneLoginScreen> createState() => _PhoneLoginScreenState();
}

class _PhoneLoginScreenState extends State<PhoneLoginScreen> {
  final _phone = TextEditingController();
  final _code = TextEditingController();
  final _displayName = TextEditingController();
  PhoneLoginStep _step = PhoneLoginStep.phone;
  String? _verificationToken;
  String? _pendingCustomToken;
  bool _busy = false;
  int _resendSeconds = 0;
  Timer? _resendTimer;
  String? _error;
  String? _info;

  @override
  void dispose() {
    _resendTimer?.cancel();
    _phone.dispose();
    _code.dispose();
    _displayName.dispose();
    super.dispose();
  }

  void _startCooldown(int seconds) {
    _resendTimer?.cancel();
    _resendSeconds = seconds;
    if (seconds <= 0) return;
    _resendTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) return;
      if (_resendSeconds <= 1) {
        timer.cancel();
        setState(() => _resendSeconds = 0);
      } else {
        setState(() => _resendSeconds--);
      }
    });
  }

  Future<void> _sendCode({bool resend = false}) async {
    final phone = normalizePhoneNumber(_phone.text);
    if (!isValidPhoneNumber(phone)) {
      setState(() => _error = '올바른 010 휴대폰 번호를 입력해 주세요.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _info = null;
    });
    try {
      final result = await widget.gateway.sendCode(phone);
      if (!mounted) return;
      _phone.text = phone;
      _code.clear();
      setState(() {
        _step = PhoneLoginStep.code;
        _pendingCustomToken = null;
        _info = resend ? '인증번호를 다시 보냈어요.' : '문자로 받은 인증번호 6자리를 입력해 주세요.';
      });
      _startCooldown(result.resendAfter);
    } on PhoneAuthException catch (error) {
      if (!mounted) return;
      if (error.code == 'REQUEST_TIMEOUT') {
        _phone.text = phone;
        _code.clear();
        setState(() {
          _step = PhoneLoginStep.code;
          _pendingCustomToken = null;
          _error = null;
          _info = '문자가 도착했다면 인증번호 6자리를 입력해 주세요. 오지 않았다면 잠시 후 다시 받아주세요.';
        });
        _startCooldown(60);
        return;
      }
      setState(() => _error = error.message);
      if (error.retryAfter != null) _startCooldown(error.retryAfter!);
    } catch (_) {
      if (mounted) setState(() => _error = '문자를 보내지 못했어요. 잠시 후 다시 시도해 주세요.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _verifyCode() async {
    final pendingCustomToken = _pendingCustomToken;
    if (pendingCustomToken != null) {
      await _retryLogin(pendingCustomToken);
      return;
    }
    final code = _code.text.trim();
    if (!isValidOtpCode(code)) {
      setState(() => _error = '인증번호 6자리를 입력해 주세요.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _info = null;
    });
    try {
      final result = await widget.gateway.verifyCode(_phone.text, code);
      if (!mounted) return;
      switch (result) {
        case ExistingPhoneAccount(:final customToken):
          await _finishLogin(customToken);
          return;
        case NewPhoneAccount(:final verificationToken):
          setState(() {
            _verificationToken = verificationToken;
            _step = PhoneLoginStep.name;
            _info = '처음 이용하시는군요. 사용할 이름을 입력해 주세요.';
          });
          return;
      }
    } on PhoneAuthException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } catch (_) {
      if (mounted) {
        setState(() => _error = '인증 처리 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요.');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _signup() async {
    final name = _displayName.text.trim();
    if (name.isEmpty || name.length > 20) {
      setState(() => _error = '이름은 1자 이상 20자 이하로 입력해 주세요.');
      return;
    }
    final verificationToken = _verificationToken;
    if (verificationToken == null) {
      _changePhone();
      setState(() => _error = '인증 정보가 만료됐어요. 인증번호를 다시 받아주세요.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _info = null;
    });
    try {
      final customToken = await widget.gateway.signup(verificationToken, name);
      await _finishLogin(customToken);
    } on PhoneAuthException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } catch (_) {
      if (mounted) setState(() => _error = '회원가입 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _finishLogin(String customToken) async {
    _pendingCustomToken = customToken;
    await widget.signInWithCustomToken(customToken);
    _pendingCustomToken = null;
    await widget.onLoggedIn();
  }

  Future<void> _retryLogin(String customToken) async {
    setState(() {
      _busy = true;
      _error = null;
      _info = null;
    });
    try {
      await _finishLogin(customToken);
    } on PhoneAuthException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } catch (_) {
      if (mounted) {
        setState(() => _error = '인증은 완료됐어요. 로그인 연결을 다시 시도해 주세요.');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _changePhone() {
    _resendTimer?.cancel();
    setState(() {
      _step = PhoneLoginStep.phone;
      _verificationToken = null;
      _pendingCustomToken = null;
      _code.clear();
      _displayName.clear();
      _resendSeconds = 0;
      _error = null;
      _info = null;
    });
  }

  void _submitCurrentStep() {
    unawaited(switch (_step) {
      PhoneLoginStep.phone => _sendCode(),
      PhoneLoginStep.code => _verifyCode(),
      PhoneLoginStep.name => _signup(),
    });
  }

  Widget _buildSignupScreen() {
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: Scaffold(
        key: const Key('signup-screen'),
        backgroundColor: AppColors.navyBase,
        body: SafeArea(
          child: Stack(
            children: [
              Positioned(
                right: -72,
                top: -88,
                child: Container(
                  key: const Key('signup-decor-surface'),
                  width: 190,
                  height: 190,
                  decoration: const BoxDecoration(
                    color: AppColors.navySurface,
                    shape: BoxShape.circle,
                  ),
                ),
              ),
              Positioned(
                left: -94,
                bottom: 42,
                child: Container(
                  key: const Key('signup-decor-surface-alt'),
                  width: 170,
                  height: 170,
                  decoration: const BoxDecoration(
                    color: AppColors.navySurfaceAlt,
                    shape: BoxShape.circle,
                  ),
                ),
              ),
              SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(24, 20, 24, 22),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Align(
                      alignment: Alignment.centerLeft,
                      child: Image.asset(
                        'assets/brand/greeneat_logo_light.png',
                        key: const Key('signup-logo'),
                        width: 78,
                        fit: BoxFit.contain,
                      ),
                    ),
                    const SizedBox(height: 30),
                    const Text(
                      '반가워요!\n이름을 알려주세요',
                      style: TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 29,
                        height: 1.25,
                        fontWeight: FontWeight.w800,
                        letterSpacing: -0.8,
                      ),
                    ),
                    const SizedBox(height: 10),
                    const Text(
                      '처음 이용하시는군요. 가입에 사용할 이름만 입력하면 돼요.',
                      style: TextStyle(
                        color: AppColors.textSecondary,
                        fontSize: 14,
                        height: 1.45,
                      ),
                    ),
                    const SizedBox(height: 34),
                    const Text(
                      '휴대폰 번호',
                      style: TextStyle(
                        color: AppColors.textSecondary,
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 9),
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            _phone.text,
                            key: const Key('signup-phone-value'),
                            style: const TextStyle(
                              color: AppColors.textPrimary,
                              fontSize: 19,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 0.2,
                            ),
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 5,
                          ),
                          decoration: BoxDecoration(
                            color: AppColors.limeGreen.withValues(alpha: 0.14),
                            borderRadius: BorderRadius.circular(20),
                          ),
                          child: const Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(Icons.check_circle,
                                  color: AppColors.limeGreen, size: 15),
                              SizedBox(width: 4),
                              Text(
                                '인증완료',
                                style: TextStyle(
                                  color: AppColors.limeGreen,
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const Divider(
                      key: Key('signup-phone-divider'),
                      height: 20,
                      thickness: 1,
                      color: AppColors.navyBorder,
                    ),
                    const SizedBox(height: 20),
                    TextField(
                      key: const Key('name-input'),
                      controller: _displayName,
                      autofocus: true,
                      textInputAction: TextInputAction.done,
                      style: const TextStyle(
                        color: AppColors.textPrimary,
                        fontSize: 19,
                        fontWeight: FontWeight.w600,
                      ),
                      cursorColor: AppColors.limeGreen,
                      inputFormatters: [LengthLimitingTextInputFormatter(20)],
                      onSubmitted: (_) {
                        if (!_busy) _submitCurrentStep();
                      },
                      decoration: const InputDecoration(
                        labelText: '이름',
                        labelStyle: TextStyle(color: AppColors.textSecondary),
                        floatingLabelStyle:
                            TextStyle(color: AppColors.limeGreen),
                        hintText: '이름을 입력해 주세요',
                        hintStyle: TextStyle(color: Color(0xFF697888)),
                        contentPadding: EdgeInsets.symmetric(vertical: 12),
                        enabledBorder: UnderlineInputBorder(
                          borderSide: BorderSide(color: AppColors.navyBorder),
                        ),
                        focusedBorder: UnderlineInputBorder(
                          borderSide:
                              BorderSide(color: AppColors.limeGreen, width: 2),
                        ),
                      ),
                    ),
                    if (_error != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 10),
                        child: Text(
                          _error!,
                          style: const TextStyle(
                            color: Color(0xFFFF8D8D),
                            fontSize: 13,
                            height: 1.4,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                    const SizedBox(height: 30),
                    SizedBox(
                      height: 56,
                      child: FilledButton(
                        key: const Key('phone-auth-primary'),
                        onPressed: _busy ? null : _submitCurrentStep,
                        style: FilledButton.styleFrom(
                          backgroundColor: AppColors.limeGreen,
                          foregroundColor: AppColors.textOnLime,
                          disabledBackgroundColor:
                              AppColors.limeGreen.withValues(alpha: 0.5),
                          disabledForegroundColor:
                              AppColors.textOnLime.withValues(alpha: 0.6),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(16),
                          ),
                          textStyle: const TextStyle(
                            fontFamily: 'Pretendard',
                            fontSize: 16,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        child: Text(_busy ? '처리 중...' : '가입하고 시작하기'),
                      ),
                    ),
                    const SizedBox(height: 16),
                    const Text(
                      '가입하면 이용약관과 개인정보 처리방침에 동의한 것으로 봅니다.',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 11,
                        height: 1.4,
                        color: AppColors.textSecondary,
                      ),
                    ),
                    Wrap(
                      alignment: WrapAlignment.center,
                      spacing: 8,
                      children: [
                        TextButton(
                          onPressed: () =>
                              widget.openLegalDocument('terms.html'),
                          style: TextButton.styleFrom(
                            foregroundColor: AppColors.textPrimary,
                            textStyle: const TextStyle(
                              fontSize: 12,
                              decoration: TextDecoration.underline,
                              decorationColor: AppColors.navyBorderStrong,
                            ),
                          ),
                          child: const Text('이용약관'),
                        ),
                        TextButton(
                          onPressed: () =>
                              widget.openLegalDocument('privacy.html'),
                          style: TextButton.styleFrom(
                            foregroundColor: AppColors.textPrimary,
                            textStyle: const TextStyle(
                              fontSize: 12,
                              decoration: TextDecoration.underline,
                              decorationColor: AppColors.navyBorderStrong,
                            ),
                          ),
                          child: const Text('개인정보 처리방침'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_step == PhoneLoginStep.name) return _buildSignupScreen();

    final isPhoneStep = _step == PhoneLoginStep.phone;
    final hasInput = isPhoneStep
        ? _phone.text.trim().isNotEmpty
        : _code.text.trim().isNotEmpty;
    final canSubmit =
        !_busy && hasInput && (!isPhoneStep || _resendSeconds == 0);

    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: Scaffold(
        key: const Key('phone-login-screen'),
        backgroundColor: AppColors.navyBase,
        body: SafeArea(
          child: LayoutBuilder(
            builder: (context, constraints) {
              final baseScale =
                  (constraints.maxHeight / 720 * 1.5).clamp(1.0, 1.5);
              final systemTextScale = math.max(
                1.0,
                MediaQuery.textScalerOf(context).scale(16) / 16,
              );
              final scale =
                  (baseScale / math.sqrt(systemTextScale)).clamp(1.0, 1.5);
              return Padding(
                padding: const EdgeInsets.symmetric(horizontal: 26),
                child: SingleChildScrollView(
                  child: ConstrainedBox(
                    constraints:
                        BoxConstraints(minHeight: constraints.maxHeight),
                    child: IntrinsicHeight(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          const Spacer(flex: 4),
                          Column(
                            key: const Key('login-content-block'),
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Align(
                                alignment: Alignment.centerLeft,
                                child: Image.asset(
                                  'assets/brand/greeneat_logo_light.png',
                                  key: const Key('login-logo'),
                                  width: 78 * scale,
                                  height: 78 * scale * 383 / 430,
                                  fit: BoxFit.contain,
                                ),
                              ),
                              SizedBox(height: 28 * scale),
                              Text(
                                isPhoneStep
                                    ? '휴대폰 번호로\n간편하게 시작하세요'
                                    : '인증번호를\n입력해 주세요',
                                key: const Key('login-headline'),
                                style: TextStyle(
                                  color: AppColors.textPrimary,
                                  fontSize: 21 * scale,
                                  fontWeight: FontWeight.w500,
                                  letterSpacing: -0.4,
                                  height: 1.4,
                                ),
                              ),
                              SizedBox(height: 6 * scale),
                              Text(
                                isPhoneStep
                                    ? '번호만 있으면 바로 식권을 쓸 수 있어요'
                                    : '${_phone.text}로 인증번호를 보냈어요',
                                key: const Key('login-auxiliary-text'),
                                style: TextStyle(
                                  color: AppColors.textSecondary,
                                  fontSize: 13 * scale,
                                  height: 1.6,
                                ),
                              ),
                              SizedBox(height: 30 * scale),
                              if (!isPhoneStep) ...[
                                Row(
                                  children: [
                                    Expanded(
                                      child: Text(
                                        '휴대폰 ${_phone.text}',
                                        style: TextStyle(
                                          color: AppColors.textSecondary,
                                          fontSize: 12 * scale,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                    ),
                                    TextButton(
                                      key: const Key('change-phone-button'),
                                      onPressed: _busy ? null : _changePhone,
                                      style: TextButton.styleFrom(
                                        foregroundColor: AppColors.textLink,
                                        disabledForegroundColor:
                                            AppColors.textPlaceholder,
                                        padding: EdgeInsets.symmetric(
                                            horizontal: 4 * scale),
                                        minimumSize: Size(0, 32 * scale),
                                        tapTargetSize:
                                            MaterialTapTargetSize.shrinkWrap,
                                      ),
                                      child: const Text('번호 변경'),
                                    ),
                                  ],
                                ),
                                SizedBox(height: 8 * scale),
                              ],
                              Text(
                                isPhoneStep ? '휴대폰 번호' : '인증번호 6자리',
                                key: const Key('login-field-label'),
                                style: TextStyle(
                                  color: AppColors.textMuted,
                                  fontSize: 12 * scale,
                                ),
                              ),
                              SizedBox(height: 8 * scale),
                              TextField(
                                key: Key(
                                    isPhoneStep ? 'phone-input' : 'otp-input'),
                                controller: isPhoneStep ? _phone : _code,
                                keyboardType: isPhoneStep
                                    ? TextInputType.phone
                                    : TextInputType.number,
                                textInputAction: TextInputAction.done,
                                autofillHints: isPhoneStep
                                    ? const [AutofillHints.telephoneNumber]
                                    : const [AutofillHints.oneTimeCode],
                                inputFormatters: isPhoneStep
                                    ? [LengthLimitingTextInputFormatter(13)]
                                    : [
                                        FilteringTextInputFormatter.digitsOnly,
                                        LengthLimitingTextInputFormatter(6),
                                      ],
                                onChanged: (_) => setState(() {}),
                                onSubmitted: (_) {
                                  if (canSubmit) _submitCurrentStep();
                                },
                                cursorColor: AppColors.limeGreen,
                                style: TextStyle(
                                  color: AppColors.textPrimary,
                                  fontSize: 19 * scale,
                                ),
                                decoration: InputDecoration(
                                  filled: false,
                                  isDense: true,
                                  hintText:
                                      isPhoneStep ? '010 0000 0000' : '000000',
                                  hintStyle: TextStyle(
                                    color: AppColors.textPlaceholder,
                                    fontSize: 19 * scale,
                                  ),
                                  prefixIcon: Icon(
                                    isPhoneStep
                                        ? Icons.phone_outlined
                                        : Icons.sms_outlined,
                                    color: AppColors.textPlaceholder,
                                    size: 17 * scale,
                                  ),
                                  prefixIconConstraints: BoxConstraints(
                                    minWidth: 29 * scale,
                                    minHeight: 44 * scale,
                                  ),
                                  contentPadding: EdgeInsets.symmetric(
                                      vertical: 12 * scale),
                                  enabledBorder: const UnderlineInputBorder(
                                    borderSide:
                                        BorderSide(color: AppColors.navyBorder),
                                  ),
                                  focusedBorder: const UnderlineInputBorder(
                                    borderSide: BorderSide(
                                      color: AppColors.limeGreen,
                                      width: 2,
                                    ),
                                  ),
                                ),
                              ),
                              if (_error != null)
                                Padding(
                                  padding: EdgeInsets.only(top: 10 * scale),
                                  child: Text(
                                    _error!,
                                    key: const Key('phone-auth-error'),
                                    style: TextStyle(
                                      color: const Color(0xFFFF8D8D),
                                      fontSize: 13 * scale,
                                      height: 1.4,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ),
                              if (_info != null)
                                Padding(
                                  padding: EdgeInsets.only(top: 10 * scale),
                                  child: Text(
                                    _info!,
                                    key: const Key('phone-auth-info'),
                                    style: TextStyle(
                                      color: AppColors.textSecondary,
                                      fontSize: 13 * scale,
                                      height: 1.4,
                                    ),
                                  ),
                                ),
                              SizedBox(height: 26 * scale),
                              SizedBox(
                                height: 52 * scale,
                                child: FilledButton(
                                  key: const Key('phone-auth-primary'),
                                  onPressed:
                                      canSubmit ? _submitCurrentStep : null,
                                  style: FilledButton.styleFrom(
                                    padding: EdgeInsets.symmetric(
                                        horizontal: 22 * scale),
                                    backgroundColor: AppColors.limeGreen,
                                    foregroundColor: AppColors.textOnLime,
                                    disabledBackgroundColor:
                                        AppColors.navyBorder,
                                    disabledForegroundColor:
                                        AppColors.textPlaceholder,
                                    shape: RoundedRectangleBorder(
                                      borderRadius:
                                          BorderRadius.circular(12 * scale),
                                    ),
                                    textStyle: TextStyle(
                                      fontFamily: 'Pretendard',
                                      fontSize: 16 * scale,
                                      fontWeight: FontWeight.w500,
                                    ),
                                  ),
                                  child: Text(
                                    _busy
                                        ? '처리 중...'
                                        : isPhoneStep
                                            ? (_resendSeconds > 0
                                                ? '$_resendSeconds초 후 다시 시도'
                                                : '인증번호 받기')
                                            : _pendingCustomToken != null
                                                ? '로그인 다시 시도'
                                                : '인증하고 시작하기',
                                  ),
                                ),
                              ),
                              if (!isPhoneStep) ...[
                                SizedBox(height: 8 * scale),
                                Align(
                                  alignment: Alignment.centerRight,
                                  child: TextButton(
                                    key: const Key('resend-button'),
                                    onPressed: _busy || _resendSeconds > 0
                                        ? null
                                        : () =>
                                            unawaited(_sendCode(resend: true)),
                                    style: TextButton.styleFrom(
                                      foregroundColor: AppColors.textLink,
                                      disabledForegroundColor:
                                          AppColors.textPlaceholder,
                                      padding: const EdgeInsets.symmetric(
                                          horizontal: 4),
                                    ),
                                    child: Text(
                                      _resendSeconds > 0
                                          ? '인증번호 다시 받기 ($_resendSeconds초)'
                                          : '인증번호 다시 받기',
                                    ),
                                  ),
                                ),
                              ],
                            ],
                          ),
                          const Spacer(flex: 5),
                          Column(
                            key: const Key('login-legal-area'),
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const Text(
                                '가입하면 이용약관과 개인정보 처리방침에\n동의한 것으로 봅니다.',
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  fontSize: 11,
                                  height: 1.6,
                                  color: AppColors.textMuted,
                                ),
                              ),
                              const SizedBox(height: 10),
                              Row(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  _LegalLink(
                                    label: '이용약관',
                                    onTap: () =>
                                        widget.openLegalDocument('terms.html'),
                                  ),
                                  const SizedBox(width: 16),
                                  _LegalLink(
                                    label: '개인정보 처리방침',
                                    onTap: () => widget
                                        .openLegalDocument('privacy.html'),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 26),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              );
            },
          ),
        ),
      ),
    );
  }
}

class _LegalLink extends StatelessWidget {
  const _LegalLink({required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onTap,
        child: Text(
          label,
          style: const TextStyle(
            color: AppColors.textLink,
            fontSize: 12,
            decoration: TextDecoration.underline,
            decorationThickness: 0.5,
            decorationColor: AppColors.navyBorderStrong,
          ),
        ),
      );
}
