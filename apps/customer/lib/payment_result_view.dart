import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'theme/app_colors.dart';

enum SolPaymentState { loading, done, fail }

class SolPaymentResultView extends StatelessWidget {
  const SolPaymentResultView({
    super.key,
    required this.state,
    required this.merchantName,
    required this.amount,
    required this.remaining,
    required this.paidAt,
    required this.usesVoucher,
    required this.errorMessage,
    required this.canPurchase,
    required this.purchaseLabel,
    required this.onClose,
    required this.onConfirm,
    required this.onPurchase,
    required this.onRetry,
  });

  final SolPaymentState state;
  final String merchantName;
  final int? amount;
  final int? remaining;
  final DateTime? paidAt;
  final bool usesVoucher;
  final String errorMessage;
  final bool canPurchase;
  final String purchaseLabel;
  final VoidCallback onClose;
  final VoidCallback onConfirm;
  final VoidCallback onPurchase;
  final VoidCallback onRetry;

  String get _merchant =>
      merchantName.trim().isEmpty ? '이용 식당' : merchantName.trim();

  @override
  Widget build(BuildContext context) {
    final reduceMotion = MediaQuery.disableAnimationsOf(context);
    return Theme(
      data: Theme.of(context).copyWith(
        scaffoldBackgroundColor: AppColors.paymentBg,
        textTheme: Theme.of(context).textTheme.apply(
              fontFamily: 'Pretendard',
              bodyColor: Colors.white,
              displayColor: Colors.white,
            ),
        colorScheme: const ColorScheme.dark(
          primary: AppColors.paymentPrimary,
          secondary: AppColors.paymentPrimaryLight,
          surface: AppColors.paymentSurface,
          error: AppColors.paymentDanger,
        ),
      ),
      child: Scaffold(
        backgroundColor: AppColors.paymentBg,
        appBar: AppBar(
          backgroundColor: AppColors.paymentBg,
          foregroundColor: const Color(0xFFC9D0DE),
          surfaceTintColor: AppColors.paymentBg,
          leading: IconButton(
            tooltip: '닫기',
            onPressed: onClose,
            icon: const Icon(Icons.arrow_back_ios_new_rounded, size: 20),
          ),
          titleSpacing: 0,
          title: const Text('식권 결제',
              style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
        ),
        body: SafeArea(
          top: false,
          child: LayoutBuilder(
            builder: (context, constraints) => SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(22, 12, 22, 24),
              child: ConstrainedBox(
                constraints: BoxConstraints(
                    minHeight: math.max(0, constraints.maxHeight - 36)),
                child: IntrinsicHeight(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (state == SolPaymentState.loading)
                        _LoadingContent(
                          merchantName: _merchant,
                          amount: amount,
                          reduceMotion: reduceMotion,
                          onClose: onClose,
                        )
                      else if (state == SolPaymentState.done)
                        _DoneContent(
                          merchantName: _merchant,
                          amount: amount,
                          remaining: remaining,
                          paidAt: paidAt,
                          usesVoucher: usesVoucher,
                          reduceMotion: reduceMotion,
                          onConfirm: onConfirm,
                        )
                      else
                        _FailContent(
                          message: errorMessage,
                          canPurchase: canPurchase,
                          purchaseLabel: purchaseLabel,
                          onPurchase: onPurchase,
                          onRetry: onRetry,
                          onClose: onClose,
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _LoadingContent extends StatelessWidget {
  const _LoadingContent(
      {required this.merchantName,
      required this.amount,
      required this.reduceMotion,
      required this.onClose});

  final String merchantName;
  final int? amount;
  final bool reduceMotion;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _ProgressRing(reduceMotion: reduceMotion),
          const SizedBox(height: 22),
          const _Heading(title: '결제하고 있어요', subtitle: '화면을 닫지 말고 잠시만 기다려 주세요'),
          const SizedBox(height: 26),
          _PulsingGhostCard(
            merchantName: merchantName,
            amount: amount,
            reduceMotion: reduceMotion,
          ),
          const SizedBox(height: 22),
          _SolButton(label: '결제 취소', onPressed: onClose, ghost: true),
        ],
      );
}

class _DoneContent extends StatelessWidget {
  const _DoneContent({
    required this.merchantName,
    required this.amount,
    required this.remaining,
    required this.paidAt,
    required this.usesVoucher,
    required this.reduceMotion,
    required this.onConfirm,
  });

  final String merchantName;
  final int? amount;
  final int? remaining;
  final DateTime? paidAt;
  final bool usesVoucher;
  final bool reduceMotion;
  final VoidCallback onConfirm;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _AnimatedCheck(reduceMotion: reduceMotion),
          const SizedBox(height: 18),
          _Heading(
            title: '결제 완료',
            subtitle: usesVoucher
                ? '$merchantName에서 식권 1장을 사용했어요'
                : '$merchantName에서 회사 장부로 결제했어요',
          ),
          const SizedBox(height: 26),
          _TicketStub(
            merchantName: merchantName,
            amount: amount,
            remaining: remaining,
            paidAt: paidAt,
            usesVoucher: usesVoucher,
            reduceMotion: reduceMotion,
          ),
          const SizedBox(height: 22),
          _SolButton(label: '확인', onPressed: onConfirm),
          const SizedBox(height: 14),
          const Text(
            '영수증은 이용내역에서 다시 볼 수 있어요',
            textAlign: TextAlign.center,
            style: TextStyle(
                color: Color(0xFF5F6779),
                fontSize: 12,
                fontWeight: FontWeight.w400),
          ),
        ],
      );
}

class _FailContent extends StatelessWidget {
  const _FailContent({
    required this.message,
    required this.canPurchase,
    required this.purchaseLabel,
    required this.onPurchase,
    required this.onRetry,
    required this.onClose,
  });

  final String message;
  final bool canPurchase;
  final String purchaseLabel;
  final VoidCallback onPurchase;
  final VoidCallback onRetry;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const _FailureMark(),
          const SizedBox(height: 18),
          const _Heading(title: '결제하지 못했어요', subtitle: '식권이 차감되지 않았어요'),
          const SizedBox(height: 26),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
            decoration: BoxDecoration(
              color: AppColors.paymentSurface,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: AppColors.paymentLine),
            ),
            child: Text(
              message.trim().isEmpty ? '결제 처리 중 오류가 발생했어요.' : message.trim(),
              style: const TextStyle(
                  color: Color(0xFFB9C1D2),
                  fontSize: 14,
                  height: 1.6,
                  fontWeight: FontWeight.w500),
            ),
          ),
          const SizedBox(height: 22),
          if (canPurchase) ...[
            _SolButton(label: purchaseLabel, onPressed: onPurchase),
            const SizedBox(height: 9),
          ] else ...[
            _SolButton(label: '다시 시도', onPressed: onRetry),
            const SizedBox(height: 9),
          ],
          _SolButton(label: '닫기', onPressed: onClose, ghost: true),
        ],
      );
}

class _Heading extends StatelessWidget {
  const _Heading({required this.title, required this.subtitle});

  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) => Column(
        children: [
          Text(
            title,
            textAlign: TextAlign.center,
            style: const TextStyle(
                fontSize: 26,
                height: 1.2,
                fontWeight: FontWeight.w800,
                letterSpacing: -1.17),
          ),
          const SizedBox(height: 8),
          Text(
            subtitle,
            textAlign: TextAlign.center,
            style: const TextStyle(
                color: AppColors.paymentMuted,
                fontSize: 14,
                fontWeight: FontWeight.w500,
                letterSpacing: -0.28),
          ),
        ],
      );
}

class _ProgressRing extends StatefulWidget {
  const _ProgressRing({required this.reduceMotion});
  final bool reduceMotion;

  @override
  State<_ProgressRing> createState() => _ProgressRingState();
}

class _ProgressRingState extends State<_ProgressRing>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller =
        AnimationController(vsync: this, duration: const Duration(seconds: 1));
    if (!widget.reduceMotion) _controller.repeat();
  }

  @override
  void didUpdateWidget(covariant _ProgressRing oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.reduceMotion) {
      _controller.stop();
      _controller.value = 0;
    } else if (!_controller.isAnimating) {
      _controller.repeat();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Center(
        child: RotationTransition(
          turns: _controller,
          child: const CustomPaint(
            size: Size.square(74),
            painter: _RingPainter(),
          ),
        ),
      );
}

class _RingPainter extends CustomPainter {
  const _RingPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 5
      ..strokeCap = StrokeCap.round
      ..shader = const SweepGradient(
        colors: [
          Color(0x005B8CFF),
          Color(0x335B8CFF),
          AppColors.paymentPrimary,
          Color(0x000046FF)
        ],
        stops: [0, .4, .94, 1],
      ).createShader(rect);
    canvas.drawArc(rect.deflate(3), -math.pi / 2, math.pi * 2, false, paint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class _PulsingGhostCard extends StatefulWidget {
  const _PulsingGhostCard(
      {required this.merchantName,
      required this.amount,
      required this.reduceMotion});
  final String merchantName;
  final int? amount;
  final bool reduceMotion;

  @override
  State<_PulsingGhostCard> createState() => _PulsingGhostCardState();
}

class _PulsingGhostCardState extends State<_PulsingGhostCard>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _opacity;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 1600));
    _opacity = Tween<double>(begin: .55, end: 1)
        .animate(CurvedAnimation(parent: _controller, curve: Curves.easeInOut));
    if (!widget.reduceMotion) _controller.repeat(reverse: true);
  }

  @override
  void didUpdateWidget(covariant _PulsingGhostCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.reduceMotion) {
      _controller.stop();
      _controller.value = 1;
    } else if (!_controller.isAnimating) {
      _controller.repeat(reverse: true);
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FadeTransition(
        opacity: _opacity,
        child: CustomPaint(
          painter:
              const _DashedBorderPainter(radius: 16, color: Color(0x29FFFFFF)),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 22),
            child: Column(
              children: [
                _Eyebrow(text: widget.merchantName, light: true),
                const SizedBox(height: 12),
                _Amount(value: widget.amount, light: true),
                const SizedBox(height: 10),
                const Text('결제 정보를 확인하고 있어요',
                    style:
                        TextStyle(color: AppColors.paymentMuted, fontSize: 14)),
              ],
            ),
          ),
        ),
      );
}

class _DashedBorderPainter extends CustomPainter {
  const _DashedBorderPainter({required this.radius, required this.color});
  final double radius;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final path = Path()
      ..addRRect(
          RRect.fromRectAndRadius(Offset.zero & size, Radius.circular(radius)));
    final metric = path.computeMetrics().first;
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    for (double distance = 0; distance < metric.length; distance += 10) {
      canvas.drawPath(
          metric.extractPath(distance, math.min(distance + 5, metric.length)),
          paint);
    }
  }

  @override
  bool shouldRepaint(covariant _DashedBorderPainter oldDelegate) => false;
}

class _AnimatedCheck extends StatelessWidget {
  const _AnimatedCheck({required this.reduceMotion});
  final bool reduceMotion;

  @override
  Widget build(BuildContext context) => Center(
        child: Container(
          width: 80,
          height: 80,
          alignment: Alignment.center,
          decoration: const BoxDecoration(
              shape: BoxShape.circle, color: Color(0x290046FF)),
          child: Container(
            width: 64,
            height: 64,
            decoration: const BoxDecoration(
              shape: BoxShape.circle,
              color: AppColors.paymentPrimary,
              boxShadow: [
                BoxShadow(
                    color: Color(0x660046FF),
                    blurRadius: 30,
                    offset: Offset(0, 12))
              ],
            ),
            child: TweenAnimationBuilder<double>(
              tween: Tween(begin: reduceMotion ? 1 : 0, end: 1),
              duration: reduceMotion
                  ? Duration.zero
                  : const Duration(milliseconds: 450),
              curve: Curves.easeInOut,
              builder: (_, value, __) =>
                  CustomPaint(painter: _CheckPainter(value)),
            ),
          ),
        ),
      );
}

class _CheckPainter extends CustomPainter {
  const _CheckPainter(this.progress);
  final double progress;

  @override
  void paint(Canvas canvas, Size size) {
    final path = Path()
      ..moveTo(size.width * .27, size.height * .52)
      ..lineTo(size.width * .43, size.height * .68)
      ..lineTo(size.width * .75, size.height * .34);
    final metric = path.computeMetrics().first;
    canvas.drawPath(
      metric.extractPath(0, metric.length * progress),
      Paint()
        ..color = Colors.white
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3.2
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round,
    );
  }

  @override
  bool shouldRepaint(covariant _CheckPainter oldDelegate) =>
      oldDelegate.progress != progress;
}

class _FailureMark extends StatelessWidget {
  const _FailureMark();

  @override
  Widget build(BuildContext context) => Center(
        child: Container(
          width: 64,
          height: 64,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: AppColors.paymentDanger.withValues(alpha: .14),
            border: Border.all(
                color: AppColors.paymentDanger.withValues(alpha: .4)),
          ),
          child: const Icon(Icons.close_rounded,
              color: AppColors.paymentDanger, size: 30),
        ),
      );
}

class _TicketStub extends StatelessWidget {
  const _TicketStub({
    required this.merchantName,
    required this.amount,
    required this.remaining,
    required this.paidAt,
    required this.usesVoucher,
    required this.reduceMotion,
  });

  final String merchantName;
  final int? amount;
  final int? remaining;
  final DateTime? paidAt;
  final bool usesVoucher;
  final bool reduceMotion;

  String get _mealWindow => paidAt != null && paidAt!.hour >= 15 ? '석식' : '중식';

  @override
  Widget build(BuildContext context) {
    final ticket = Container(
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          begin: Alignment.topRight,
          end: Alignment.bottomLeft,
          colors: [AppColors.paymentCream, AppColors.paymentCreamDark],
        ),
        borderRadius: BorderRadius.circular(16),
        boxShadow: const [
          BoxShadow(
              color: Color(0x80000000), blurRadius: 40, offset: Offset(0, 18))
        ],
      ),
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(22, 24, 22, 20),
            child: Column(
              children: [
                _Eyebrow(text: '$merchantName · $_mealWindow'),
                const SizedBox(height: 12),
                _Amount(value: amount),
                const SizedBox(height: 10),
                Text(
                  usesVoucher ? '식권 1장 사용' : '회사 장부 결제',
                  style: const TextStyle(
                      color: Color(0xFF5A6070),
                      fontSize: 14,
                      fontWeight: FontWeight.w500,
                      letterSpacing: -0.28),
                ),
              ],
            ),
          ),
          const _Perforation(),
          Padding(
            padding: const EdgeInsets.fromLTRB(22, 16, 22, 20),
            child: Row(
              children: [
                Expanded(
                  child: _StubValue(
                    label: usesVoucher ? '남은 식권' : '결제 구분',
                    value: usesVoucher
                        ? (remaining == null ? '-' : '$remaining장')
                        : '회사 장부',
                    highlighted: true,
                  ),
                ),
                Expanded(
                  child: _StubValue(
                      label: '결제일시', value: _shortDate(paidAt), alignEnd: true),
                ),
              ],
            ),
          ),
        ],
      ),
    );
    if (reduceMotion) return ticket;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: const Duration(milliseconds: 500),
      curve: const Cubic(.2, .9, .25, 1),
      builder: (_, value, child) => Opacity(
        opacity: value,
        child: Transform.translate(
          offset: Offset(0, 16 * (1 - value)),
          child: Transform.scale(scale: .97 + .03 * value, child: child),
        ),
      ),
      child: ticket,
    );
  }
}

class _Perforation extends StatelessWidget {
  const _Perforation();

  @override
  Widget build(BuildContext context) => const SizedBox(
        height: 18,
        child: Stack(
          clipBehavior: Clip.none,
          alignment: Alignment.center,
          children: [
            Positioned(
                left: 16,
                right: 16,
                child: CustomPaint(
                    size: Size(double.infinity, 1),
                    painter: _PerforationPainter())),
            Positioned(
                left: -9,
                child: DecoratedBox(
                    decoration: BoxDecoration(
                        color: AppColors.paymentBg, shape: BoxShape.circle),
                    child: SizedBox.square(dimension: 18))),
            Positioned(
                right: -9,
                child: DecoratedBox(
                    decoration: BoxDecoration(
                        color: AppColors.paymentBg, shape: BoxShape.circle),
                    child: SizedBox.square(dimension: 18))),
          ],
        ),
      );
}

class _PerforationPainter extends CustomPainter {
  const _PerforationPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = const Color(0xFFC3BCA9)
      ..strokeWidth = 1;
    for (double x = 0; x < size.width; x += 12) {
      canvas.drawLine(
          Offset(x, 0), Offset(math.min(x + 6, size.width), 0), paint);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class _Eyebrow extends StatelessWidget {
  const _Eyebrow({required this.text, this.light = false});
  final String text;
  final bool light;

  @override
  Widget build(BuildContext context) => Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const SizedBox(
              width: 5,
              height: 5,
              child: DecoratedBox(
                  decoration: BoxDecoration(
                      color: AppColors.paymentPrimary,
                      shape: BoxShape.circle))),
          const SizedBox(width: 7),
          Flexible(
            child: Text(
              text,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: light ? AppColors.paymentMuted : const Color(0xFF6C7385),
                fontSize: 11,
                fontWeight: FontWeight.w700,
                letterSpacing: .88,
              ),
            ),
          ),
        ],
      );
}

class _Amount extends StatelessWidget {
  const _Amount({required this.value, this.light = false});
  final int? value;
  final bool light;

  @override
  Widget build(BuildContext context) {
    final color = light ? Colors.white : AppColors.paymentCreamInk;
    if (value == null) {
      return Text('금액 확인 중',
          style: TextStyle(
              color: color, fontSize: 22, fontWeight: FontWeight.w700));
    }
    final formatted = value!.toString().replaceAllMapped(
        RegExp(r'(\d)(?=(\d{3})+(?!\d))'), (match) => '${match[1]},');
    return FittedBox(
      fit: BoxFit.scaleDown,
      child: Text.rich(
        TextSpan(
          children: [
            TextSpan(text: formatted),
            const TextSpan(
                text: '원',
                style: TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.w700,
                    letterSpacing: -.66)),
          ],
        ),
        maxLines: 1,
        style: TextStyle(
            color: color,
            fontSize: 44,
            height: 1,
            fontWeight: FontWeight.w800,
            letterSpacing: -2.42),
      ),
    );
  }
}

class _StubValue extends StatelessWidget {
  const _StubValue(
      {required this.label,
      required this.value,
      this.highlighted = false,
      this.alignEnd = false});
  final String label;
  final String value;
  final bool highlighted;
  final bool alignEnd;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment:
            alignEnd ? CrossAxisAlignment.end : CrossAxisAlignment.start,
        children: [
          Text(label,
              style: const TextStyle(
                  color: Color(0xFF8B90A0),
                  fontSize: 11,
                  fontWeight: FontWeight.w600)),
          const SizedBox(height: 5),
          Text(
            value,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
                color: highlighted
                    ? AppColors.paymentPrimary
                    : AppColors.paymentCreamInk,
                fontSize: 15,
                fontWeight: FontWeight.w700,
                letterSpacing: -.45),
          ),
        ],
      );
}

class _SolButton extends StatelessWidget {
  const _SolButton(
      {required this.label, required this.onPressed, this.ghost = false});
  final String label;
  final VoidCallback onPressed;
  final bool ghost;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 54,
        child: ghost
            ? OutlinedButton(
                onPressed: onPressed,
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.paymentMuted,
                  side: const BorderSide(color: AppColors.paymentLine),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14)),
                  textStyle: const TextStyle(
                      fontSize: 16, fontWeight: FontWeight.w700),
                ),
                child: Text(label),
              )
            : FilledButton(
                onPressed: onPressed,
                style: FilledButton.styleFrom(
                  backgroundColor: AppColors.paymentPrimary,
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14)),
                  textStyle: const TextStyle(
                      fontSize: 16, fontWeight: FontWeight.w700),
                ),
                child: Text(label),
              ),
      );
}

String _shortDate(DateTime? date) {
  if (date == null) return '-';
  String two(int value) => value.toString().padLeft(2, '0');
  return '${date.month}/${date.day} ${two(date.hour)}:${two(date.minute)}';
}
