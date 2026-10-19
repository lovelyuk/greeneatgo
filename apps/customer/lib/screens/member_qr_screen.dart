import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../load_error.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';

/// Loads a fresh 60-second member QR code from the server
/// (`GET /transactions/member-qr` → `{code, expires_at, ttl}`).
typedef MemberQrLoader = Future<Map<String, dynamic>> Function();

/// Reads the current voucher balance so the screen can show "used" once the
/// counter scanner redeems the code.
typedef BalanceReader = Future<int?> Function();

final _memberCode = RegExp(r'^\d{81}$');

/// Buyer's QR for the restaurant counter scanner (web `/shop` MemberQr parity).
class MemberQrScreen extends StatefulWidget {
  const MemberQrScreen({
    super.key,
    required this.loadCode,
    required this.readBalance,
    this.onClose,
    this.onScanStoreQr,
    this.pollInterval = const Duration(seconds: 4),
  });

  final MemberQrLoader loadCode;
  final BalanceReader readBalance;
  final VoidCallback? onClose;
  final VoidCallback? onScanStoreQr;
  final Duration pollInterval;

  @override
  State<MemberQrScreen> createState() => _MemberQrScreenState();
}

class _MemberQrScreenState extends State<MemberQrScreen> {
  String? _code;
  DateTime? _expiresAt;
  String? _error;
  int? _startBalance;
  int? _usedRemaining;
  Timer? _refresh;
  Timer? _poll;
  Timer? _tick;
  int _secondsLeft = 0;

  @override
  void initState() {
    super.initState();
    unawaited(_start());
  }

  @override
  void dispose() {
    _refresh?.cancel();
    _poll?.cancel();
    _tick?.cancel();
    super.dispose();
  }

  Future<void> _start() async {
    setState(() {
      _usedRemaining = null;
      _error = null;
      _code = null;
    });
    try {
      _startBalance = await widget.readBalance();
    } catch (_) {
      _startBalance = null;
    }
    await _load();
    _poll?.cancel();
    _poll = Timer.periodic(widget.pollInterval, (_) => unawaited(_checkUsed()));
  }

  Future<void> _load() async {
    _refresh?.cancel();
    try {
      final data = await widget.loadCode();
      final code = data['code'];
      final expires = data['expires_at'];
      final ttl = (data['ttl'] as num?)?.toInt() ?? 60;
      if (code is! String || !_memberCode.hasMatch(code) || expires is! num) {
        throw const FormatException('QR을 만들지 못했어요.');
      }
      if (!mounted) return;
      setState(() {
        _code = code;
        _expiresAt =
            DateTime.fromMillisecondsSinceEpoch(expires.toInt() * 1000);
        _error = null;
      });
      _startTick();
      _refresh = Timer(Duration(seconds: (ttl - 10).clamp(5, 3600)),
          () => unawaited(_load()));
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error is FormatException
          ? error.message
          : friendlyLoadError(error));
    }
  }

  void _startTick() {
    _tick?.cancel();
    void update() {
      final expires = _expiresAt;
      if (!mounted || expires == null) return;
      final left = expires.difference(DateTime.now()).inMilliseconds;
      setState(() => _secondsLeft = left <= 0 ? 0 : (left / 1000).ceil());
    }

    update();
    _tick = Timer.periodic(const Duration(milliseconds: 500), (_) => update());
  }

  Future<void> _checkUsed() async {
    if (_usedRemaining != null || _startBalance == null) return;
    int? now;
    try {
      now = await widget.readBalance();
    } catch (_) {
      return;
    }
    if (!mounted || now == null || now >= _startBalance!) return;
    _refresh?.cancel();
    _poll?.cancel();
    _tick?.cancel();
    setState(() => _usedRemaining = now);
    unawaited(HapticFeedback.mediumImpact());
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: AppColors.bg,
        appBar: AppBar(
          backgroundColor: AppColors.bg,
          foregroundColor: AppColors.fg,
          surfaceTintColor: AppColors.bg,
          leading: widget.onClose == null
              ? null
              : IconButton(
                  tooltip: '홈으로',
                  onPressed: widget.onClose,
                  icon: const Icon(Icons.arrow_back_rounded),
                ),
          title: const Text('QR 사용하기'),
        ),
        body: ListView(
          padding: const EdgeInsets.fromLTRB(18, 8, 18, 112),
          children: [
            const Text('MY QR', style: AppTextStyles.overline),
            const SizedBox(height: 8),
            const Text('내 식권 QR', style: AppTextStyles.screenTitle),
            const SizedBox(height: 6),
            const Text('카운터 스캐너에 화면을 대 주세요. 한 번에 식권 1장이 사용돼요.',
                style: AppTextStyles.caption),
            const SizedBox(height: 18),
            _body(),
            if (widget.onScanStoreQr != null) ...[
              const SizedBox(height: 16),
              OutlinedButton.icon(
                key: const ValueKey('scan-store-qr-button'),
                onPressed: widget.onScanStoreQr,
                icon: const Icon(Icons.qr_code_scanner_rounded),
                label: const Text('스캐너가 없나요? 매장 QR 찍어서 결제'),
              ),
            ],
          ],
        ),
      );

  Widget _body() {
    if (_usedRemaining != null) {
      return _Card(
        key: const ValueKey('member-qr-used'),
        children: [
          Container(
            width: 64,
            height: 64,
            decoration: const BoxDecoration(
                color: AppColors.blue, shape: BoxShape.circle),
            child: const Icon(Icons.check_rounded,
                color: AppColors.fg, size: 38),
          ),
          const SizedBox(height: 14),
          const Text('식권 1장 사용 완료',
              style: TextStyle(
                  color: AppColors.fg,
                  fontSize: 20,
                  fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          Text('남은 식권 $_usedRemaining장', style: AppTextStyles.caption),
          const SizedBox(height: 16),
          FilledButton(
              onPressed: () => unawaited(_start()),
              child: const Text('QR 다시 보기')),
        ],
      );
    }
    if (_error != null) {
      return _Card(children: [
        Text(_error!, style: const TextStyle(color: AppColors.danger)),
        const SizedBox(height: 12),
        FilledButton(
            onPressed: () => unawaited(_start()),
            child: const Text('다시 만들기')),
      ]);
    }
    final code = _code;
    if (code == null) {
      return const _Card(children: [
        SizedBox(height: 40),
        CircularProgressIndicator(),
        SizedBox(height: 40),
      ]);
    }
    return _Card(
      key: const ValueKey('member-qr-ready'),
      children: [
        Semantics(
          label: '식권 사용 QR 코드',
          image: true,
          child: Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(18),
            ),
            child: QrImageView(
              key: const ValueKey('member-qr-image'),
              data: code,
              version: QrVersions.auto,
              errorCorrectionLevel: QrErrorCorrectLevel.M,
              size: 240,
              backgroundColor: Colors.white,
              padding: const EdgeInsets.all(6),
            ),
          ),
        ),
        const SizedBox(height: 14),
        Text(
          _secondsLeft > 0 ? '$_secondsLeft초 후 새 QR로 바뀌어요' : '새 QR로 바꾸는 중…',
          key: const ValueKey('member-qr-timer'),
          style: const TextStyle(color: AppColors.blueSoft, fontSize: 13),
        ),
        const SizedBox(height: 4),
        const Text('화면을 캡처해서 쓸 수 없어요.', style: AppTextStyles.caption),
      ],
    );
  }
}

class _Card extends StatelessWidget {
  const _Card({super.key, required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.fromLTRB(18, 22, 18, 22),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(AppRadii.card),
          border: Border.all(color: AppColors.line),
        ),
        child: Column(children: children),
      );
}
