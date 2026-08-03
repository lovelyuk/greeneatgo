import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'phone_auth.dart';

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
        _info = resend ? '인증번호를 다시 보냈어요.' : '문자로 받은 인증번호 6자리를 입력해 주세요.';
      });
      _startCooldown(result.resendAfter);
    } on PhoneAuthException catch (error) {
      if (!mounted) return;
      setState(() => _error = error.message);
      if (error.retryAfter != null) _startCooldown(error.retryAfter!);
    } catch (_) {
      if (mounted) setState(() => _error = '문자를 보내지 못했어요. 잠시 후 다시 시도해 주세요.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _verifyCode() async {
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
      if (mounted) setState(() => _error = '인증 처리 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요.');
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
    await widget.signInWithCustomToken(customToken);
    await widget.onLoggedIn();
  }

  void _changePhone() {
    _resendTimer?.cancel();
    setState(() {
      _step = PhoneLoginStep.phone;
      _verificationToken = null;
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF8F3E3),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(22, 18, 22, 28),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const SizedBox(height: 56),
            widget.brandHeader ??
                const Text('greeneatGo',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                        color: Color(0xFF18382A),
                        fontSize: 36,
                        fontWeight: FontWeight.w900)),
            const SizedBox(height: 44),
            Container(
              padding: const EdgeInsets.all(22),
              decoration: BoxDecoration(
                color: const Color(0xFFFFFAF0),
                borderRadius: BorderRadius.circular(30),
                border: Border.all(color: const Color(0xFFE5DDC7)),
              ),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                if (_step != PhoneLoginStep.phone) ...[
                  Text('휴대폰 ${_phone.text}',
                      style: const TextStyle(fontWeight: FontWeight.w700)),
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                        onPressed: _busy ? null : _changePhone,
                        child: const Text('번호 변경')),
                  ),
                ],
                if (_step == PhoneLoginStep.phone)
                  TextField(
                    key: const Key('phone-input'),
                    controller: _phone,
                    keyboardType: TextInputType.phone,
                    textInputAction: TextInputAction.done,
                    autofillHints: const [AutofillHints.telephoneNumber],
                    inputFormatters: [LengthLimitingTextInputFormatter(13)],
                    onSubmitted: (_) {
                      if (!_busy && _resendSeconds == 0) _submitCurrentStep();
                    },
                    decoration: const InputDecoration(
                      labelText: '휴대폰 번호',
                      hintText: '010-1234-5678',
                      prefixIcon: Icon(Icons.phone_outlined),
                    ),
                  ),
                if (_step == PhoneLoginStep.code) ...[
                  TextField(
                    key: const Key('otp-input'),
                    controller: _code,
                    keyboardType: TextInputType.number,
                    textInputAction: TextInputAction.done,
                    autofillHints: const [AutofillHints.oneTimeCode],
                    inputFormatters: [
                      FilteringTextInputFormatter.digitsOnly,
                      LengthLimitingTextInputFormatter(6),
                    ],
                    onSubmitted: (_) {
                      if (!_busy) _submitCurrentStep();
                    },
                    decoration: const InputDecoration(
                      labelText: '인증번호 6자리',
                      prefixIcon: Icon(Icons.sms_outlined),
                    ),
                  ),
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                      key: const Key('resend-button'),
                      onPressed: _busy || _resendSeconds > 0
                          ? null
                          : () => unawaited(_sendCode(resend: true)),
                      child: Text(_resendSeconds > 0
                          ? '인증번호 다시 받기 ($_resendSeconds초)'
                          : '인증번호 다시 받기'),
                    ),
                  ),
                ],
                if (_step == PhoneLoginStep.name)
                  TextField(
                    key: const Key('name-input'),
                    controller: _displayName,
                    textInputAction: TextInputAction.done,
                    inputFormatters: [LengthLimitingTextInputFormatter(20)],
                    onSubmitted: (_) {
                      if (!_busy) _submitCurrentStep();
                    },
                    decoration: const InputDecoration(
                      labelText: '이름',
                      prefixIcon: Icon(Icons.badge_outlined),
                    ),
                  ),
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text(_error!,
                        style: const TextStyle(
                            color: Color(0xFF9B1C1C),
                            fontSize: 13,
                            height: 1.45,
                            fontWeight: FontWeight.w600)),
                  ),
                if (_info != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text(_info!,
                        style: const TextStyle(color: Color(0xFF5C7A66))),
                  ),
                const SizedBox(height: 18),
                FilledButton(
                  key: const Key('phone-auth-primary'),
                  onPressed: _busy ||
                          (_step == PhoneLoginStep.phone && _resendSeconds > 0)
                      ? null
                      : _submitCurrentStep,
                  child: Text(_busy
                      ? '처리 중...'
                      : switch (_step) {
                          PhoneLoginStep.phone => _resendSeconds > 0
                              ? '$_resendSeconds초 후 다시 시도'
                              : '인증번호 받기',
                          PhoneLoginStep.code => '인증하고 시작하기',
                          PhoneLoginStep.name => '가입하고 시작하기',
                        }),
                ),
                const SizedBox(height: 12),
                const Text('가입하면 이용약관과 개인정보 처리방침에 동의한 것으로 봅니다.',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 12, color: Color(0xFF5C7A66))),
                Wrap(alignment: WrapAlignment.center, children: [
                  TextButton(
                      onPressed: () => widget.openLegalDocument('terms.html'),
                      child: const Text('이용약관')),
                  TextButton(
                      onPressed: () => widget.openLegalDocument('privacy.html'),
                      child: const Text('개인정보 처리방침')),
                ]),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}
