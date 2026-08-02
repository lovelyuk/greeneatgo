import 'dart:ui';

import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_theme.dart';

enum TicketState { active, expiring, empty }

enum AmountStyle { neg, plus, muted, plain }

enum MealSlot { lunch, dinner, grant, refund }

class MealTicketCard extends StatelessWidget {
  const MealTicketCard({
    super.key,
    required this.remainingLabel,
    required this.caption,
    required this.todayUsage,
    required this.onTapQr,
    this.state = TicketState.active,
    this.actionLabel = 'QR 사용하기',
  });

  final String remainingLabel;
  final String caption;
  final String todayUsage;
  final VoidCallback onTapQr;
  final TicketState state;
  final String actionLabel;

  @override
  Widget build(BuildContext context) {
    final empty = state == TicketState.empty;
    final paper = empty ? AppColors.paperMuted : AppColors.paper;
    return Semantics(
      button: true,
      label: '남은 식권 $remainingLabel, $caption',
      child: ClipPath(
        clipper: const _TicketClipper(),
        child: Container(
          height: 218,
          decoration: BoxDecoration(
            color: paper,
            border: state == TicketState.expiring
                ? Border.all(color: AppColors.gold, width: 2)
                : null,
            borderRadius: BorderRadius.circular(AppRadii.card),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(22, 20, 22, 13),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('남은 식권', style: AppTextStyles.overline),
                      const Spacer(),
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Expanded(
                            child: FittedBox(
                              fit: BoxFit.scaleDown,
                              alignment: Alignment.centerLeft,
                              child: Text(
                                remainingLabel,
                                style: AppTextStyles.ticketNumber.copyWith(
                                  color: empty ? AppColors.fg2 : AppColors.ink,
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 6),
                      Text(
                        caption,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTextStyles.caption.copyWith(
                          color: empty ? AppColors.fg2 : AppColors.ink,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              SizedBox(
                height: 2,
                child: CustomPaint(painter: _DashedLinePainter()),
              ),
              SizedBox(
                height: 72,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(22, 6, 14, 6),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('오늘 사용',
                                style: AppTextStyles.caption
                                    .copyWith(color: AppColors.ink)),
                            const SizedBox(height: 2),
                            Text(todayUsage,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: AppTextStyles.body
                                    .copyWith(color: AppColors.ink)),
                          ],
                        ),
                      ),
                      const SizedBox(width: 10),
                      SizedBox(
                        height: 48,
                        child: FilledButton.icon(
                          onPressed: onTapQr,
                          style: FilledButton.styleFrom(
                            backgroundColor:
                                empty ? AppColors.fg2 : AppColors.ink,
                            foregroundColor: AppColors.paper,
                            padding: const EdgeInsets.symmetric(horizontal: 14),
                            shape: RoundedRectangleBorder(
                              borderRadius:
                                  BorderRadius.circular(AppRadii.button),
                            ),
                          ),
                          icon: const Icon(Icons.qr_code_rounded,
                              size: 18, color: AppColors.gold),
                          label: Text(actionLabel,
                              style: const TextStyle(
                                  fontSize: 12, fontWeight: FontWeight.w800)),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _TicketClipper extends CustomClipper<Path> {
  const _TicketClipper();

  @override
  Path getClip(Size size) {
    const radius = AppRadii.card;
    const notch = 11.0;
    const y = 145.0;
    final path = Path()
      ..moveTo(radius, 0)
      ..lineTo(size.width - radius, 0)
      ..quadraticBezierTo(size.width, 0, size.width, radius)
      ..lineTo(size.width, y - notch)
      ..arcToPoint(Offset(size.width, y + notch),
          radius: const Radius.circular(notch), clockwise: false)
      ..lineTo(size.width, size.height - radius)
      ..quadraticBezierTo(
          size.width, size.height, size.width - radius, size.height)
      ..lineTo(radius, size.height)
      ..quadraticBezierTo(0, size.height, 0, size.height - radius)
      ..lineTo(0, y + notch)
      ..arcToPoint(const Offset(0, y - notch),
          radius: const Radius.circular(notch), clockwise: false)
      ..lineTo(0, radius)
      ..quadraticBezierTo(0, 0, radius, 0)
      ..close();
    return path;
  }

  @override
  bool shouldReclip(covariant CustomClipper<Path> oldClipper) => false;
}

class _DashedLinePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AppColors.ticketLine
      ..strokeWidth = 2;
    const dash = 6.0;
    const gap = 5.0;
    for (double x = 0; x < size.width; x += dash + gap) {
      canvas.drawLine(
          Offset(x, 1), Offset((x + dash).clamp(0, size.width), 1), paint);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class StackedCardGroup extends StatelessWidget {
  const StackedCardGroup({super.key, required this.children});
  final List<StackedCard> children;

  @override
  Widget build(BuildContext context) => Column(
        children: [
          for (var i = 0; i < children.length; i++)
            Transform.translate(
              offset: const Offset(0, -14),
              child: Padding(
                padding:
                    EdgeInsets.only(bottom: i == children.length - 1 ? 0 : 0),
                child: children[i],
              ),
            ),
        ],
      );
}

class StackedCard extends StatelessWidget {
  const StackedCard({
    super.key,
    this.leadingIcon,
    required this.title,
    this.subtitle,
    this.trailing,
    this.footer,
  });

  final Widget? leadingIcon;
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final Widget? footer;

  @override
  Widget build(BuildContext context) => Container(
        constraints: BoxConstraints(minHeight: footer == null ? 90 : 118),
        padding: const EdgeInsets.fromLTRB(18, 26, 18, 16),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(AppRadii.card),
          border: Border.all(color: AppColors.line),
        ),
        child: Column(
          children: [
            Row(
              children: [
                if (leadingIcon != null) ...[
                  leadingIcon!,
                  const SizedBox(width: 12),
                ],
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title, style: AppTextStyles.cardTitle),
                      if (subtitle != null) ...[
                        const SizedBox(height: 4),
                        Text(subtitle!,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppTextStyles.caption),
                      ],
                    ],
                  ),
                ),
                if (trailing != null) ...[
                  const SizedBox(width: 10),
                  trailing!,
                ],
              ],
            ),
            if (footer != null) ...[
              const SizedBox(height: 15),
              footer!,
            ],
          ],
        ),
      );
}

class AppProgressBar extends StatelessWidget {
  const AppProgressBar({
    super.key,
    required this.value,
    required this.leftCaption,
    required this.rightCaption,
  });
  final double value;
  final String leftCaption;
  final String rightCaption;

  @override
  Widget build(BuildContext context) => Column(
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(3),
            child: LinearProgressIndicator(
              value: value.clamp(0, 1),
              minHeight: 6,
              backgroundColor: AppColors.progressTrack,
              valueColor: const AlwaysStoppedAnimation(AppColors.blue),
            ),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(child: Text(leftCaption, style: AppTextStyles.caption)),
              Text(rightCaption, style: AppTextStyles.caption),
            ],
          ),
        ],
      );
}

class TxListItem extends StatelessWidget {
  const TxListItem({
    super.key,
    required this.slot,
    required this.title,
    required this.subtitle,
    required this.amount,
    required this.style,
    this.showDivider = true,
  });
  final MealSlot slot;
  final String title;
  final String subtitle;
  final String amount;
  final AmountStyle style;
  final bool showDivider;

  Color get _amountColor => switch (style) {
        AmountStyle.neg => AppColors.danger,
        AmountStyle.plus => AppColors.blueSoft,
        AmountStyle.muted => AppColors.fg2,
        AmountStyle.plain => AppColors.fg,
      };

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(vertical: 13),
        decoration: BoxDecoration(
          border: showDivider
              ? const Border(top: BorderSide(color: AppColors.lineSoft))
              : null,
        ),
        child: Row(
          children: [
            _SlotBadge(slot: slot),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTextStyles.body),
                  const SizedBox(height: 4),
                  Text(subtitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTextStyles.caption),
                ],
              ),
            ),
            const SizedBox(width: 10),
            Text(amount,
                style: TextStyle(
                    color: _amountColor,
                    fontSize: 14,
                    fontWeight: FontWeight.w800)),
          ],
        ),
      );
}

class _SlotBadge extends StatelessWidget {
  const _SlotBadge({required this.slot});
  final MealSlot slot;

  @override
  Widget build(BuildContext context) {
    final (label, fg, bg) = switch (slot) {
      MealSlot.lunch => (
          '중',
          AppColors.gold,
          AppColors.gold.withValues(alpha: .15)
        ),
      MealSlot.dinner => ('석', AppColors.dinnerText, AppColors.cardHi),
      MealSlot.grant => (
          '＋',
          AppColors.blueSoft,
          AppColors.blue.withValues(alpha: .13)
        ),
      MealSlot.refund => ('↩', AppColors.fg2, AppColors.cardHi),
    };
    return Container(
      width: 36,
      height: 36,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(label,
          style:
              TextStyle(color: fg, fontSize: 14, fontWeight: FontWeight.w800)),
    );
  }
}

class SectionHeader extends StatelessWidget {
  const SectionHeader({super.key, required this.title, this.onViewAll});
  final String title;
  final VoidCallback? onViewAll;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 22),
        child: Row(
          children: [
            Expanded(
              child: Text(title,
                  style: const TextStyle(
                      color: AppColors.fg,
                      fontSize: 14,
                      fontWeight: FontWeight.w800)),
            ),
            if (onViewAll != null)
              TextButton(
                onPressed: onViewAll,
                style: TextButton.styleFrom(
                  foregroundColor: AppColors.fg2,
                  minimumSize: const Size(48, 48),
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                ),
                child: const Text('전체보기 ›',
                    style:
                        TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
              ),
          ],
        ),
      );
}

class AppTabBar extends StatelessWidget {
  const AppTabBar({
    super.key,
    required this.index,
    required this.onChanged,
  });
  final int index;
  final ValueChanged<int> onChanged;

  static const tabs = [
    (Icons.home_rounded, '홈'),
    (Icons.receipt_long_rounded, '이용내역'),
    (Icons.account_balance_wallet_rounded, '장부'),
    (Icons.person_rounded, '내정보'),
  ];

  @override
  Widget build(BuildContext context) => ClipRRect(
        borderRadius: BorderRadius.circular(26),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 14, sigmaY: 14),
          child: Container(
            height: 64,
            decoration: BoxDecoration(
              color: AppColors.card.withValues(alpha: .95),
              borderRadius: BorderRadius.circular(26),
              border: Border.all(color: AppColors.line),
            ),
            child: Row(
              children: [
                for (var i = 0; i < tabs.length; i++)
                  Expanded(
                    child: Semantics(
                      selected: index == i,
                      label: '${tabs[i].$2} 탭',
                      button: true,
                      child: InkWell(
                        onTap: () => onChanged(i),
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(tabs[i].$1,
                                size: 21,
                                color: index == i
                                    ? AppColors.blueSoft
                                    : AppColors.fg2.withValues(alpha: .5)),
                            const SizedBox(height: 4),
                            Text(tabs[i].$2,
                                style: TextStyle(
                                    color: index == i
                                        ? AppColors.blueSoft
                                        : AppColors.fg2.withValues(alpha: .5),
                                    fontSize: 10,
                                    fontWeight: FontWeight.w700)),
                          ],
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      );
}

class DarkCard extends StatelessWidget {
  const DarkCard(
      {super.key,
      required this.child,
      this.padding = const EdgeInsets.all(18)});
  final Widget child;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) => Container(
        padding: padding,
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(AppRadii.card),
          border: Border.all(color: AppColors.line),
        ),
        child: child,
      );
}
