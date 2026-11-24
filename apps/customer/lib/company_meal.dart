import 'dart:async';

import 'package:flutter/material.dart';

import 'theme/app_colors.dart';
import 'widgets/dashboard_components.dart';

/// One meal window set by the company admin (KST, "HH:MM").
class CompanyMealWindow {
  const CompanyMealWindow(this.name, this.start, this.end);

  final String name;
  final String start;
  final String end;

  static int? _seconds(String value) {
    final parts = value.split(':');
    if (parts.length != 2) return null;
    final hour = int.tryParse(parts[0]);
    final minute = int.tryParse(parts[1]);
    if (hour == null || minute == null || hour < 0 || hour > 23 || minute < 0 || minute > 59) {
      return null;
    }
    return hour * 3600 + minute * 60;
  }

  bool get valid => _seconds(start) != null && _seconds(end) != null;

  /// Same rule as the server: start <= now <= end, and a window may pass midnight.
  bool contains(int secondsOfDay) {
    final from = _seconds(start), to = _seconds(end);
    if (from == null || to == null) return false;
    return from <= to
        ? secondsOfDay >= from && secondsOfDay <= to
        : secondsOfDay >= from || secondsOfDay <= to;
  }
}

/// What the company tab of the home card says.
class CompanyMealView {
  const CompanyMealView({required this.available, required this.title, required this.detail});

  final bool available;
  final String title;
  final String detail;
}

/// `/me.company_meal`: whether a ledger employee can use the company allowance.
///
/// Limits come from the server as a ready message. Meal hours and the weekend rule
/// come as data and are judged again on the device clock (KST), so the card stays
/// right while the app is left open past the end of a meal window.
class CompanyMealStatus {
  const CompanyMealStatus({
    required this.limitMessage,
    required this.windows,
    required this.weekendAllowed,
  });

  final String? limitMessage;
  final List<CompanyMealWindow> windows;
  final bool weekendAllowed;

  static CompanyMealStatus? fromMe(Map<String, dynamic> me) {
    final raw = me['company_meal'];
    if (raw is! Map) return null;
    final block = raw['limit_block'];
    final message = block is Map ? '${block['message'] ?? ''}'.trim() : '';
    final windows = <CompanyMealWindow>[
      if (raw['windows'] is List)
        for (final item in raw['windows'] as List)
          if (item is Map)
            CompanyMealWindow('${item['name'] ?? ''}'.trim(), '${item['start'] ?? ''}', '${item['end'] ?? ''}'),
    ].where((window) => window.valid).toList();
    return CompanyMealStatus(
      limitMessage: message.isEmpty ? null : message,
      windows: windows,
      weekendAllowed: raw['weekend_allowed'] != false,
    );
  }

  String get _hours => windows
      // No-break space inside one window, so a long line wraps between windows.
      .map((w) => [if (w.name.isNotEmpty) w.name, '${w.start}~${w.end}'].join('\u00A0'))
      .join(' · ');

  CompanyMealView at(DateTime now) {
    const blocked = '지금은 회사 식대를 쓸 수 없어요';
    if (limitMessage != null) {
      return CompanyMealView(available: false, title: blocked, detail: limitMessage!);
    }
    final kst = now.toUtc().add(const Duration(hours: 9));
    if (!weekendAllowed && kst.weekday >= DateTime.saturday) {
      return const CompanyMealView(available: false, title: blocked, detail: '주말에는 사용할 수 없어요');
    }
    if (windows.isEmpty) {
      return const CompanyMealView(available: true, title: '회사 식대 사용 가능', detail: '언제든 사용할 수 있어요');
    }
    final seconds = kst.hour * 3600 + kst.minute * 60 + kst.second;
    for (final window in windows) {
      if (window.contains(seconds)) {
        return CompanyMealView(
          available: true,
          title: '회사 식대 사용 가능',
          detail: [
            if (window.name.isNotEmpty) '지금 ${window.name} 시간이에요',
            '${window.start}~${window.end}',
          ].join(' · '),
        );
      }
    }
    return CompanyMealView(available: false, title: blocked, detail: '사용 시간 · $_hours');
  }
}

enum MealCardTab { company, personal }

/// Home card for ledger employees: 회사 / 개인 tabs (회사 first).
///
/// 회사 shows whether the company allowance can be used now and why not, with no
/// voucher count and no buy button. 개인 is the ordinary voucher card.
class LedgerMealCard extends StatefulWidget {
  const LedgerMealCard({
    super.key,
    required this.status,
    required this.personalBalance,
    required this.couponCountLabel,
    required this.pointBalanceLabel,
    required this.monthUsage,
    required this.onTapQr,
    required this.onBuyTicket,
    this.now = DateTime.now,
  });

  final CompanyMealStatus? status;
  final int personalBalance;
  final String couponCountLabel;
  final String pointBalanceLabel;
  final String monthUsage;
  final VoidCallback onTapQr;
  final VoidCallback? onBuyTicket;
  final DateTime Function() now;

  @override
  State<LedgerMealCard> createState() => _LedgerMealCardState();
}

class _LedgerMealCardState extends State<LedgerMealCard> {
  MealCardTab _tab = MealCardTab.company;
  Timer? _clock;

  @override
  void initState() {
    super.initState();
    // Re-judge the meal hours while the screen stays open.
    _clock = Timer.periodic(const Duration(seconds: 20), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _clock?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tabs = _MealTabs(tab: _tab, onChanged: (tab) => setState(() => _tab = tab));
    if (_tab == MealCardTab.personal) {
      return MealTicketCard(
        top: tabs,
        remainingCountLabel: '${widget.personalBalance}',
        couponCountLabel: widget.couponCountLabel,
        pointBalanceLabel: widget.pointBalanceLabel,
        caption: '내 식권 · QR 한 번에 1장 사용',
        monthUsage: widget.monthUsage,
        onTapQr: widget.onTapQr,
        onBuyTicket: widget.onBuyTicket,
        state: widget.personalBalance == 0 ? TicketState.empty : TicketState.active,
      );
    }
    final view = widget.status?.at(widget.now());
    final personalHint = view != null && !view.available && widget.personalBalance > 0
        ? '내 식권 ${widget.personalBalance}장으로는 결제할 수 있어요'
        : null;
    final title = view?.title ?? '회사 장부로 결제해요';
    final detail = view?.detail ?? '매장 계약 단가가 적용돼요';
    return MealTicketCard(
      top: tabs,
      headerLabel: '회사 식대',
      balance: _CompanyMealPanel(
        available: view?.available,
        title: title,
        detail: detail,
        hint: personalHint,
      ),
      balanceSemantics: '회사 식대 $title, $detail${personalHint == null ? '' : ', $personalHint'}',
      remainingCountLabel: '-',
      couponCountLabel: widget.couponCountLabel,
      pointBalanceLabel: widget.pointBalanceLabel,
      caption: '회사 장부 결제 · 매장 계약 단가 적용',
      monthUsage: widget.monthUsage,
      onTapQr: widget.onTapQr,
      onBuyTicket: null,
      state: TicketState.active,
    );
  }
}

class _MealTabs extends StatelessWidget {
  const _MealTabs({required this.tab, required this.onChanged});

  final MealCardTab tab;
  final ValueChanged<MealCardTab> onChanged;

  @override
  Widget build(BuildContext context) => Container(
        key: const ValueKey('meal-card-tabs'),
        margin: const EdgeInsets.only(bottom: 14),
        padding: const EdgeInsets.all(4),
        decoration: BoxDecoration(
          color: AppColors.flipTile,
          border: Border.all(color: AppColors.flipBorder),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(children: [
          for (final (value, label) in const [(MealCardTab.company, '회사'), (MealCardTab.personal, '개인')])
            Expanded(
              child: Semantics(
                button: true,
                selected: tab == value,
                label: '$label 식권',
                child: GestureDetector(
                  key: ValueKey('meal-tab-${value.name}'),
                  behavior: HitTestBehavior.opaque,
                  onTap: () => onChanged(value),
                  child: Container(
                    height: 40,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: tab == value ? AppColors.blue : Colors.transparent,
                      borderRadius: BorderRadius.circular(9),
                    ),
                    child: ExcludeSemantics(
                      child: Text(
                        label,
                        style: TextStyle(
                          fontFamily: 'Pretendard',
                          color: tab == value ? AppColors.fg : AppColors.flipDim,
                          fontSize: 14,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
        ]),
      );
}

class _CompanyMealPanel extends StatelessWidget {
  const _CompanyMealPanel({required this.available, required this.title, required this.detail, this.hint});

  /// null = the server sent no status: say how payment works without claiming either way.
  final bool? available;
  final String title;
  final String detail;
  final String? hint;

  @override
  Widget build(BuildContext context) {
    final color = available == null
        ? AppColors.flipStrong
        : available!
            ? AppColors.flipDigit
            : AppColors.gold;
    final icon = available == null
        ? Icons.apartment_rounded
        : available!
            ? Icons.check_circle_rounded
            : Icons.schedule_rounded;
    return Container(
      key: ValueKey('company-meal-${available == null ? 'unknown' : available! ? 'available' : 'blocked'}'),
      constraints: const BoxConstraints(minHeight: 84),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: AppColors.flipTile,
        border: Border.all(color: available == false ? AppColors.gold.withValues(alpha: .55) : AppColors.flipBorder),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(children: [
        Icon(icon, color: color, size: 30),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title,
                  style: TextStyle(
                      fontFamily: 'Pretendard', color: color, fontSize: 17, fontWeight: FontWeight.w800, height: 1.25)),
              const SizedBox(height: 4),
              Text(detail,
                  style: const TextStyle(
                      fontFamily: 'Pretendard', color: AppColors.flipStrong, fontSize: 13, height: 1.35)),
              if (hint != null) ...[
                const SizedBox(height: 4),
                Text(hint!,
                    style: const TextStyle(
                        fontFamily: 'Pretendard', color: AppColors.flipDim, fontSize: 12.5, height: 1.35)),
              ],
            ],
          ),
        ),
      ]),
    );
  }
}
