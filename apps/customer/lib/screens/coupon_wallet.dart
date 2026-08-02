import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme/app_colors.dart';
import '../theme/app_theme.dart';

int _asInt(Object? value) =>
    value is num ? value.round() : double.tryParse('$value')?.round() ?? 0;

double _asDouble(Object? value) =>
    value is num ? value.toDouble() : double.tryParse('$value') ?? 0;

String couponWon(int value) {
  final formatted = value
      .abs()
      .toString()
      .replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => ',');
  return '${value < 0 ? '-' : ''}$formatted원';
}

class CouponItem {
  const CouponItem({
    required this.id,
    required this.name,
    required this.discountType,
    required this.discountValue,
    this.validFrom,
    this.validUntil,
  });

  final String id;
  final String name;
  final String discountType;
  final double discountValue;
  final DateTime? validFrom;
  final DateTime? validUntil;

  bool get isPercent => discountType.toLowerCase() == 'percent';
  String get benefit {
    if (!isPercent) return couponWon(discountValue.floor());
    final value = discountValue == discountValue.truncateToDouble()
        ? discountValue.toInt().toString()
        : discountValue
            .toStringAsFixed(2)
            .replaceFirst(RegExp(r'0+$'), '')
            .replaceFirst(RegExp(r'\.$'), '');
    return '$value%';
  }

  String get validityLabel {
    String date(DateTime value) =>
        '${value.year}.${value.month.toString().padLeft(2, '0')}.${value.day.toString().padLeft(2, '0')}';
    if (validFrom != null && validUntil != null) {
      return '${date(validFrom!.toLocal())} – ${date(validUntil!.toLocal())}';
    }
    if (validUntil != null) return '${date(validUntil!.toLocal())}까지';
    return '사용 기한 제한 없음';
  }

  factory CouponItem.fromJson(Map<String, dynamic> json) => CouponItem(
        id: '${json['id'] ?? json['coupon_id'] ?? ''}',
        name: '${json['name'] ?? json['title'] ?? '할인 쿠폰'}',
        discountType: '${json['discount_type'] ?? 'fixed'}',
        discountValue: _asDouble(json['discount_value']),
        validFrom: DateTime.tryParse('${json['valid_from'] ?? ''}'),
        validUntil: DateTime.tryParse('${json['valid_until'] ?? ''}'),
      );
}

class CouponWallet {
  const CouponWallet({required this.merchantName, required this.items});
  final String merchantName;
  final List<CouponItem> items;

  factory CouponWallet.fromJson(Map<String, dynamic> json) {
    final merchant = json['merchant'];
    final merchantName = merchant is Map
        ? '${merchant['name'] ?? merchant['merchant_name'] ?? ''}'
        : '${merchant ?? ''}';
    final rawItems = json['items'];
    return CouponWallet(
      merchantName: merchantName.trim().isEmpty ? '돈토식당' : merchantName,
      items: rawItems is List
          ? rawItems
              .whereType<Map>()
              .map((item) => CouponItem.fromJson(item.cast<String, dynamic>()))
              .where((item) => item.id.isNotEmpty)
              .toList()
          : const [],
    );
  }
}

class VoucherQuote {
  const VoucherQuote({
    required this.grossAmount,
    required this.couponDiscountAmount,
    required this.pointAmount,
    required this.amount,
  });

  final int grossAmount;
  final int couponDiscountAmount;
  final int pointAmount;
  final int amount;

  factory VoucherQuote.fromJson(Map<String, dynamic> json) => VoucherQuote(
        grossAmount: _asInt(json['gross_amount']),
        couponDiscountAmount: _asInt(json['coupon_discount_amount']),
        pointAmount: _asInt(json['point_amount']),
        amount: _asInt(json['amount'] ?? json['payment_amount']),
      );
}

typedef CouponLoader = Future<CouponWallet> Function();
typedef QuoteLoader = Future<VoucherQuote> Function({
  required String productId,
  String? couponId,
  required int pointAmount,
});

class CouponTicketCard extends StatelessWidget {
  const CouponTicketCard({
    super.key,
    required this.coupon,
    required this.merchantName,
    this.selected = false,
    this.onTap,
  });

  final CouponItem coupon;
  final String merchantName;
  final bool selected;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => Semantics(
        button: onTap != null,
        selected: selected,
        label: '${coupon.name}, ${coupon.benefit} 할인, ${coupon.validityLabel}',
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(22),
          child: ClipPath(
            clipper: const _CouponTicketClipper(),
            child: Container(
              key: ValueKey('coupon-${coupon.id}'),
              height: 154,
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: coupon.isPercent
                      ? const [Color(0xFF6948EF), Color(0xFF315DDB)]
                      : const [Color(0xFF315DDB), Color(0xFF243B9D)],
                ),
                border: Border.all(
                    color: selected ? Colors.white : Colors.white24,
                    width: selected ? 2 : 1),
              ),
              child: Row(children: [
                SizedBox(
                  width: 60,
                  child: RotatedBox(
                    quarterTurns: 3,
                    child: Center(
                      child: Text('COUPON',
                          style: AppTextStyles.overline.copyWith(
                              color: Colors.white70, letterSpacing: 2.8)),
                    ),
                  ),
                ),
                Container(width: 1, color: Colors.white24),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(18, 16, 16, 14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          Expanded(
                            child: Text(merchantName,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                    color: Colors.white70,
                                    fontSize: 11,
                                    fontWeight: FontWeight.w700)),
                          ),
                          if (selected)
                            const Icon(Icons.check_circle_rounded,
                                color: Colors.white, size: 20),
                        ]),
                        const SizedBox(height: 5),
                        Text(coupon.benefit,
                            style: const TextStyle(
                                color: Colors.white,
                                fontSize: 30,
                                height: 1,
                                fontWeight: FontWeight.w800,
                                letterSpacing: -1)),
                        const SizedBox(height: 5),
                        Text(coupon.name,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                                color: Colors.white,
                                fontSize: 14,
                                fontWeight: FontWeight.w800)),
                        const Spacer(),
                        Text('유효기간  ${coupon.validityLabel}',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                                color: Colors.white70,
                                fontSize: 10.5,
                                fontWeight: FontWeight.w600)),
                      ],
                    ),
                  ),
                ),
              ]),
            ),
          ),
        ),
      );
}

class _CouponTicketClipper extends CustomClipper<Path> {
  const _CouponTicketClipper();

  @override
  Path getClip(Size size) {
    const radius = 22.0;
    const notch = 9.0;
    const split = 60.0;
    return Path()
      ..moveTo(radius, 0)
      ..lineTo(size.width - radius, 0)
      ..quadraticBezierTo(size.width, 0, size.width, radius)
      ..lineTo(size.width, size.height - radius)
      ..quadraticBezierTo(
          size.width, size.height, size.width - radius, size.height)
      ..lineTo(split + notch, size.height)
      ..arcToPoint(Offset(split - notch, size.height),
          radius: const Radius.circular(notch), clockwise: false)
      ..lineTo(radius, size.height)
      ..quadraticBezierTo(0, size.height, 0, size.height - radius)
      ..lineTo(0, radius)
      ..quadraticBezierTo(0, 0, radius, 0)
      ..lineTo(split - notch, 0)
      ..arcToPoint(const Offset(split + notch, 0),
          radius: const Radius.circular(notch), clockwise: false)
      ..close();
  }

  @override
  bool shouldReclip(covariant CustomClipper<Path> oldClipper) => false;
}

ThemeData _darkTheme(BuildContext context) => Theme.of(context).copyWith(
      scaffoldBackgroundColor: AppColors.bg,
      colorScheme: const ColorScheme.dark(
          primary: AppColors.blue,
          secondary: AppColors.blueSoft,
          surface: AppColors.card,
          error: AppColors.danger),
      textTheme: Theme.of(context).textTheme.apply(
          fontFamily: 'Pretendard',
          bodyColor: AppColors.fg,
          displayColor: AppColors.fg),
      appBarTheme: const AppBarTheme(
          backgroundColor: AppColors.bg,
          foregroundColor: AppColors.fg,
          surfaceTintColor: Colors.transparent),
    );

class CouponWalletScreen extends StatefulWidget {
  const CouponWalletScreen({super.key, required this.loadCoupons});
  final CouponLoader loadCoupons;

  @override
  State<CouponWalletScreen> createState() => _CouponWalletScreenState();
}

class _CouponWalletScreenState extends State<CouponWalletScreen> {
  late Future<CouponWallet> _wallet = widget.loadCoupons();

  void _reload() => setState(() => _wallet = widget.loadCoupons());

  @override
  Widget build(BuildContext context) => Theme(
        data: _darkTheme(context),
        child: Scaffold(
          appBar: AppBar(title: const Text('쿠폰함')),
          body: SafeArea(
            child: FutureBuilder<CouponWallet>(
              future: _wallet,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snapshot.hasError) {
                  return _LoadError(error: snapshot.error, onRetry: _reload);
                }
                final wallet = snapshot.data!;
                return RefreshIndicator(
                  onRefresh: () async {
                    _reload();
                    await _wallet;
                  },
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(18, 8, 18, 32),
                    children: [
                      Text('${wallet.items.length}장의 쿠폰',
                          style: AppTextStyles.screenTitle),
                      const SizedBox(height: 6),
                      Text('${wallet.merchantName}에서 사용할 수 있어요.',
                          style: AppTextStyles.caption),
                      const SizedBox(height: 22),
                      if (wallet.items.isEmpty)
                        const _EmptyCoupons()
                      else
                        for (final coupon in wallet.items) ...[
                          CouponTicketCard(
                              coupon: coupon,
                              merchantName: wallet.merchantName),
                          const SizedBox(height: 14),
                        ],
                    ],
                  ),
                );
              },
            ),
          ),
        ),
      );
}

class CheckoutSelection {
  const CheckoutSelection({required this.couponId, required this.pointAmount});
  final String? couponId;
  final int pointAmount;
}

class CheckoutOptionsScreen extends StatefulWidget {
  const CheckoutOptionsScreen({
    super.key,
    required this.productId,
    required this.productName,
    required this.pointBalance,
    required this.loadCoupons,
    required this.loadQuote,
  });

  final String productId;
  final String productName;
  final int pointBalance;
  final CouponLoader loadCoupons;
  final QuoteLoader loadQuote;

  @override
  State<CheckoutOptionsScreen> createState() => _CheckoutOptionsScreenState();
}

class _CheckoutOptionsScreenState extends State<CheckoutOptionsScreen> {
  final _points = TextEditingController(text: '0');
  CouponWallet? _wallet;
  CouponItem? _coupon;
  VoucherQuote? _quote;
  String? _error;
  String? _couponWarning;
  bool _loadingWallet = true;
  bool _quoting = false;
  int _generation = 0;

  int get _pointIntent => int.tryParse(_points.text.replaceAll(',', '')) ?? 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _generation++;
    _points.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loadingWallet = true;
      _error = null;
      _couponWarning = null;
    });
    try {
      _wallet = await widget.loadCoupons();
    } catch (error) {
      if (!mounted) return;
      _wallet = const CouponWallet(merchantName: '식당', items: []);
      _couponWarning = '쿠폰을 불러오지 못했어요. 쿠폰 없이 결제할 수 있어요.';
    }
    if (!mounted) return;
    setState(() => _loadingWallet = false);
    await _requestQuote();
  }

  Future<void> _requestQuote() async {
    final generation = ++_generation;
    final points = _pointIntent.clamp(0, widget.pointBalance).toInt();
    if (points != _pointIntent) {
      _points.text = '$points';
      _points.selection = TextSelection.collapsed(offset: _points.text.length);
    }
    setState(() {
      _quoting = true;
      _quote = null;
      _error = null;
    });
    try {
      final quote = await widget.loadQuote(
          productId: widget.productId,
          couponId: _coupon?.id,
          pointAmount: points);
      if (mounted && generation == _generation) setState(() => _quote = quote);
    } catch (error) {
      if (mounted && generation == _generation) {
        setState(() => _error = error.toString());
      }
    } finally {
      if (mounted && generation == _generation) {
        setState(() => _quoting = false);
      }
    }
  }

  void _onPointChanged(String _) {
    final generation = ++_generation;
    Future<void>.delayed(const Duration(milliseconds: 350), () {
      if (mounted && generation == _generation) _requestQuote();
    });
    setState(() {
      _quote = null;
      _quoting = true;
    });
  }

  @override
  Widget build(BuildContext context) => Theme(
        data: _darkTheme(context),
        child: Scaffold(
          appBar: AppBar(title: const Text('할인 선택')),
          body: SafeArea(
            child: _loadingWallet
                ? const Center(child: CircularProgressIndicator())
                : ListView(
                    padding: const EdgeInsets.fromLTRB(18, 4, 18, 112),
                    children: [
                      Text(widget.productName,
                          style: AppTextStyles.screenTitle),
                      const SizedBox(height: 5),
                      const Text('결제 전에 쿠폰과 포인트를 선택해 주세요.',
                          style: AppTextStyles.caption),
                      const SizedBox(height: 24),
                      const Text('쿠폰', style: AppTextStyles.cardTitle),
                      const SizedBox(height: 10),
                      _NoCouponTile(
                        selected: _coupon == null,
                        onTap: () {
                          setState(() => _coupon = null);
                          _requestQuote();
                        },
                      ),
                      if (_couponWarning != null) ...[
                        const SizedBox(height: 8),
                        Row(children: [
                          Expanded(
                            child: Text(
                              _couponWarning!,
                              key: const Key('coupon-warning'),
                              style: AppTextStyles.caption,
                            ),
                          ),
                          TextButton(
                            onPressed: _load,
                            child: const Text('다시 시도'),
                          ),
                        ]),
                      ],
                      if (_wallet != null)
                        for (final coupon in _wallet!.items) ...[
                          const SizedBox(height: 12),
                          CouponTicketCard(
                            coupon: coupon,
                            merchantName: _wallet!.merchantName,
                            selected: _coupon?.id == coupon.id,
                            onTap: () {
                              setState(() => _coupon = coupon);
                              _requestQuote();
                            },
                          ),
                        ],
                      const SizedBox(height: 24),
                      Row(children: [
                        const Expanded(
                            child: Text('포인트', style: AppTextStyles.cardTitle)),
                        Text('보유 ${couponWon(widget.pointBalance)}',
                            style: AppTextStyles.caption),
                      ]),
                      const SizedBox(height: 10),
                      TextField(
                        key: const Key('point-entry'),
                        controller: _points,
                        onChanged: _onPointChanged,
                        keyboardType: TextInputType.number,
                        inputFormatters: [
                          FilteringTextInputFormatter.digitsOnly
                        ],
                        decoration: InputDecoration(
                          suffixText: 'P',
                          filled: true,
                          fillColor: AppColors.card,
                          hintText: '0',
                          border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(16),
                              borderSide:
                                  const BorderSide(color: AppColors.line)),
                          suffixIcon: TextButton(
                            key: const Key('max-points'),
                            onPressed: () {
                              _points.text = '${widget.pointBalance}';
                              _points.selection = TextSelection.collapsed(
                                  offset: _points.text.length);
                              _requestQuote();
                            },
                            child: const Text('최대'),
                          ),
                        ),
                      ),
                      const SizedBox(height: 22),
                      _QuoteCard(quote: _quote, loading: _quoting),
                      if (_error != null) ...[
                        const SizedBox(height: 12),
                        Text(_error!,
                            key: const Key('quote-error'),
                            style: const TextStyle(color: AppColors.danger)),
                      ],
                    ],
                  ),
          ),
          bottomNavigationBar: _loadingWallet
              ? null
              : SafeArea(
                  minimum: const EdgeInsets.fromLTRB(18, 8, 18, 14),
                  child: SizedBox(
                    height: 54,
                    child: FilledButton(
                      key: const Key('continue-to-payment'),
                      onPressed: _quote == null || _quoting
                          ? null
                          : () => Navigator.of(context).pop(CheckoutSelection(
                              couponId: _coupon?.id,
                              pointAmount: _pointIntent)),
                      child: Text(_quote == null
                          ? '금액 확인 중...'
                          : _quote!.amount == 0
                              ? '포인트로 구매하기'
                              : '${couponWon(_quote!.amount)} 결제하기'),
                    ),
                  ),
                ),
        ),
      );
}

class _NoCouponTile extends StatelessWidget {
  const _NoCouponTile({required this.selected, required this.onTap});
  final bool selected;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Material(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(16),
        child: ListTile(
          key: const Key('no-coupon'),
          onTap: onTap,
          shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
              side: BorderSide(
                  color: selected ? AppColors.blueSoft : AppColors.line)),
          leading: Icon(
              selected ? Icons.check_circle_rounded : Icons.circle_outlined,
              color: selected ? AppColors.blueSoft : AppColors.fg2),
          title: const Text('쿠폰 사용 안 함', style: AppTextStyles.body),
        ),
      );
}

class _QuoteCard extends StatelessWidget {
  const _QuoteCard({required this.quote, required this.loading});
  final VoucherQuote? quote;
  final bool loading;
  @override
  Widget build(BuildContext context) => Container(
        key: const Key('server-quote'),
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
            color: AppColors.card,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: AppColors.line)),
        child: loading || quote == null
            ? const SizedBox(
                height: 88, child: Center(child: CircularProgressIndicator()))
            : Column(children: [
                _AmountRow('상품 금액', couponWon(quote!.grossAmount)),
                const SizedBox(height: 10),
                _AmountRow(
                    '쿠폰 할인', '-${couponWon(quote!.couponDiscountAmount)}',
                    accent: true),
                const SizedBox(height: 10),
                _AmountRow('포인트 사용', '-${couponWon(quote!.pointAmount)}',
                    accent: true),
                const Divider(height: 28, color: AppColors.line),
                _AmountRow('최종 결제', couponWon(quote!.amount), total: true),
              ]),
      );
}

class _AmountRow extends StatelessWidget {
  const _AmountRow(this.label, this.value,
      {this.accent = false, this.total = false});
  final String label;
  final String value;
  final bool accent;
  final bool total;
  @override
  Widget build(BuildContext context) => Row(children: [
        Expanded(
            child: Text(label,
                style:
                    total ? AppTextStyles.cardTitle : AppTextStyles.caption)),
        Text(value,
            style: TextStyle(
                color: accent ? AppColors.blueSoft : AppColors.fg,
                fontSize: total ? 20 : 13,
                fontWeight: FontWeight.w800)),
      ]);
}

class _LoadError extends StatelessWidget {
  const _LoadError({required this.error, required this.onRetry});
  final Object? error;
  final VoidCallback onRetry;
  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(error.toString(),
                textAlign: TextAlign.center,
                style: const TextStyle(color: AppColors.danger)),
            const SizedBox(height: 14),
            OutlinedButton(onPressed: onRetry, child: const Text('다시 불러오기')),
          ]),
        ),
      );
}

class _EmptyCoupons extends StatelessWidget {
  const _EmptyCoupons();
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(vertical: 44, horizontal: 20),
        decoration: BoxDecoration(
            color: AppColors.card,
            borderRadius: BorderRadius.circular(22),
            border: Border.all(color: AppColors.line)),
        child: const Column(children: [
          Icon(Icons.confirmation_number_outlined,
              color: AppColors.fg2, size: 36),
          SizedBox(height: 12),
          Text('사용 가능한 쿠폰이 없어요', style: AppTextStyles.cardTitle),
          SizedBox(height: 5),
          Text('새 쿠폰이 생기면 이곳에 표시됩니다.', style: AppTextStyles.caption),
        ]),
      );
}
