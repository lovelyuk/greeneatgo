import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../load_error.dart';
import '../restaurants.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';

/// Loads a fresh 60-second member QR code from the server
/// (`GET /transactions/member-qr` → `{code, expires_at, ttl, quantity}`).
/// [quantity]: how many meals one scan of this code pays for.
typedef MemberQrLoader = Future<Map<String, dynamic>> Function(int quantity);

/// Most meals one scan may pay for, whatever is held.
const maxQrQuantity = 10;

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
    this.header,
    this.title = '내 식권 QR',
    this.guide = _voucherGuide,
    this.usedTitle = _voucherUsed,
    this.usedCaption = _remainingVouchers,
    this.showRestaurantBalances = true,
    this.maxQuantity,
    this.unit = '장',
  });

  static String? _remainingVouchers(int remaining) => '남은 식권 $remaining장';
  static String _voucherGuide(int quantity) =>
      '카운터 스캐너에 화면을 대 주세요. 한 번에 식권 $quantity장이 사용돼요.';
  static String _voucherUsed(int quantity) => '식권 $quantity장 사용 완료';

  final MemberQrLoader loadCode;
  final BalanceReader readBalance;
  final VoidCallback? onClose;

  /// Opens the camera fallback with the quantity chosen here.
  final void Function(int quantity)? onScanStoreQr;
  final Duration pollInterval;

  /// Most the holder may choose. Null: the number [readBalance] returned when
  /// the screen opened (vouchers held). Always capped at [maxQrQuantity]; with
  /// 1 the chooser is hidden.
  final int? maxQuantity;

  /// Counter word for the quantity: 장 (vouchers) or 끼 (company-paid meals).
  final String unit;

  /// Shown above the title (ledger employees: the 회사 장부 / 내 식권 choice).
  final Widget? header;

  /// Wording, given the chosen quantity. The defaults describe a voucher QR; a
  /// company-ledger QR passes its own.
  final String title;
  final String Function(int quantity) guide;
  final String Function(int quantity) usedTitle;

  /// Line under [usedTitle], given the value [readBalance] returned after the
  /// use. Null result: no line (a company-ledger meal has no voucher count).
  final String? Function(int remaining) usedCaption;

  /// The per-restaurant voucher list makes no sense for a company-ledger QR.
  final bool showRestaurantBalances;

  @override
  State<MemberQrScreen> createState() => _MemberQrScreenState();
}

class _MemberQrScreenState extends State<MemberQrScreen> {
  String? _code;
  DateTime? _expiresAt;
  String? _error;
  int? _startBalance;
  int? _usedRemaining;
  int _quantity = 1;
  int _usedQuantity = 1;
  int _generation = 0; // drops answers for a quantity that is no longer chosen
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

  int get _max =>
      (widget.maxQuantity ?? _startBalance ?? 1).clamp(1, maxQrQuantity);

  @override
  void didUpdateWidget(MemberQrScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    // The allowance shrank while the screen was open (a meal was just paid).
    if (_quantity > _max && _usedRemaining == null) {
      _quantity = _max;
      _code = null;
      unawaited(_load());
    }
  }

  void _setQuantity(int next) {
    final value = next.clamp(1, _max);
    if (value == _quantity) return;
    // The quantity is inside the code: never leave the old code on screen
    // under the new number.
    setState(() {
      _quantity = value;
      _code = null;
      _error = null;
    });
    unawaited(_load());
  }

  Future<void> _start({bool resetQuantity = false}) async {
    setState(() {
      _usedRemaining = null;
      _error = null;
      _code = null;
      if (resetQuantity) _quantity = 1;
    });
    try {
      _startBalance = await widget.readBalance();
    } catch (_) {
      _startBalance = null;
    }
    if (_quantity > _max) _quantity = _max;
    await _load();
    _poll?.cancel();
    _poll = Timer.periodic(widget.pollInterval, (_) => unawaited(_checkUsed()));
  }

  Future<void> _load() async {
    _refresh?.cancel();
    final asked = _quantity;
    final generation = ++_generation;
    try {
      final data = await widget.loadCode(asked);
      if (generation != _generation) return;
      final code = data['code'];
      final expires = data['expires_at'];
      final ttl = (data['ttl'] as num?)?.toInt() ?? 60;
      if (code is! String || !_memberCode.hasMatch(code) || expires is! num) {
        throw const FormatException('QR을 만들지 못했어요.');
      }
      // A server that does not know quantities answers with a one-meal code:
      // never show that under "3장".
      if (asked > 1 && (data['quantity'] as num?)?.toInt() != asked) {
        _quantity = 1;
        throw const FormatException('여러 장 사용은 아직 준비 중이에요. 1장으로 다시 만들어 주세요.');
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
      if (!mounted || generation != _generation) return;
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
    setState(() {
      _usedRemaining = now;
      _usedQuantity = _quantity;
    });
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
            if (widget.header != null) ...[
              widget.header!,
              const SizedBox(height: 16),
            ],
            const Text('MY QR', style: AppTextStyles.overline),
            const SizedBox(height: 8),
            Text(widget.title, style: AppTextStyles.screenTitle),
            const SizedBox(height: 6),
            Text(widget.guide(_quantity),
                key: const ValueKey('member-qr-guide'),
                style: AppTextStyles.caption),
            const SizedBox(height: 18),
            if (_max > 1 && _usedRemaining == null) ...[
              _QuantityStepper(
                quantity: _quantity,
                max: _max,
                unit: widget.unit,
                onChanged: _setQuantity,
              ),
              const SizedBox(height: 12),
            ],
            _body(),
            // One QR for every restaurant: show what is held where.
            if (widget.showRestaurantBalances) const RestaurantBalanceList(),
            if (widget.onScanStoreQr != null) ...[
              const SizedBox(height: 16),
              // Q3: guidance card (no theme-coloured outlined button).
              Material(
                color: AppColors.card,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(18),
                  side: const BorderSide(color: AppColors.line),
                ),
                child: InkWell(
                  key: const ValueKey('scan-store-qr-button'),
                  borderRadius: BorderRadius.circular(18),
                  onTap: () => widget.onScanStoreQr!(_quantity),
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Row(children: [
                      Container(
                        width: 40,
                        height: 40,
                        decoration: BoxDecoration(
                          color: AppColors.blue.withValues(alpha: 0.16),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: const Icon(Icons.qr_code_scanner_rounded,
                            color: AppColors.blueSoft, size: 22),
                      ),
                      const SizedBox(width: 12),
                      const Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('매장 QR 찍어서 결제',
                                style: TextStyle(
                                    color: AppColors.fg,
                                    fontSize: 15,
                                    fontWeight: FontWeight.w800)),
                            SizedBox(height: 2),
                            Text('카운터에 스캐너가 없을 때 사용해요',
                                style: TextStyle(
                                    color: AppColors.fg2, fontSize: 12.5)),
                          ],
                        ),
                      ),
                      const Icon(Icons.chevron_right_rounded,
                          color: AppColors.fg2),
                    ]),
                  ),
                ),
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
          Text(widget.usedTitle(_usedQuantity),
              style: const TextStyle(
                  color: AppColors.fg,
                  fontSize: 20,
                  fontWeight: FontWeight.w800)),
          if (widget.usedCaption(_usedRemaining!) case final caption?) ...[
            const SizedBox(height: 6),
            Text(caption, style: AppTextStyles.caption),
          ],
          const SizedBox(height: 16),
          FilledButton(
              onPressed: () => unawaited(_start(resetQuantity: true)),
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
        if (_quantity > 1) ...[
          const SizedBox(height: 8),
          Text('이 QR은 $_quantity${widget.unit}용이에요',
              key: const ValueKey('member-qr-quantity-note'),
              style: const TextStyle(
                  color: AppColors.fg,
                  fontSize: 17,
                  fontWeight: FontWeight.w800)),
        ],
        const SizedBox(height: 4),
        const Text('화면을 캡처해서 쓸 수 없어요.', style: AppTextStyles.caption),
      ],
    );
  }
}

/// − 2장 + : how many meals one scan of the QR pays for.
class _QuantityStepper extends StatelessWidget {
  const _QuantityStepper({
    required this.quantity,
    required this.max,
    required this.unit,
    required this.onChanged,
  });
  final int quantity;
  final int max;
  final String unit;
  final ValueChanged<int> onChanged;

  Widget _button(String key, String tooltip, IconData icon, int next) {
    final enabled = next >= 1 && next <= max;
    return IconButton.filledTonal(
      key: ValueKey(key),
      tooltip: tooltip,
      constraints: const BoxConstraints.tightFor(width: 48, height: 48),
      onPressed: enabled ? () => onChanged(next) : null,
      icon: Icon(icon),
    );
  }

  @override
  Widget build(BuildContext context) => Container(
        key: const ValueKey('qr-quantity'),
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(AppRadii.card),
          border: Border.all(color: AppColors.line),
        ),
        child: Row(children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('사용할 수량',
                    style: TextStyle(
                        color: AppColors.fg,
                        fontSize: 15,
                        fontWeight: FontWeight.w800)),
                const SizedBox(height: 2),
                Text('최대 $max$unit',
                    style:
                        const TextStyle(color: AppColors.fg2, fontSize: 12.5)),
              ],
            ),
          ),
          _button('qr-quantity-minus', '줄이기', Icons.remove_rounded, quantity - 1),
          SizedBox(
            width: 64,
            child: Text('$quantity$unit',
                key: const ValueKey('qr-quantity-value'),
                textAlign: TextAlign.center,
                style: const TextStyle(
                    color: AppColors.fg,
                    fontSize: 22,
                    fontWeight: FontWeight.w800)),
          ),
          _button('qr-quantity-plus', '늘리기', Icons.add_rounded, quantity + 1),
        ]),
      );
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
