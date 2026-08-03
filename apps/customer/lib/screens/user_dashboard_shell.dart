import 'dart:async';

import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../widgets/dashboard_components.dart';

typedef AsyncAction = Future<void> Function();
typedef DashboardPageBuilder = Widget Function(VoidCallback close);

class UserDashboardShell extends StatefulWidget {
  const UserDashboardShell({
    super.key,
    required this.data,
    required this.onRefresh,
    required this.onScanQr,
    required this.onBuyVoucher,
    required this.onCoupons,
    required this.onEvents,
    required this.onOpenSettings,
    required this.onAnnouncements,
    required this.onReviews,
    required this.onTerms,
    required this.onPrivacy,
    required this.onSignOut,
    required this.pendingBanner,
    this.todayMenuCard,
    this.partnerBanner,
    this.purchasePageBuilder,
    this.qrPageBuilder,
  });

  final Map<String, dynamic> data;
  final AsyncAction onRefresh;
  final AsyncAction onScanQr;
  final AsyncAction onBuyVoucher;
  final AsyncAction onCoupons;
  final AsyncAction onEvents;
  final AsyncAction onOpenSettings;
  final AsyncAction onAnnouncements;
  final AsyncAction onReviews;
  final AsyncAction onTerms;
  final AsyncAction onPrivacy;
  final AsyncAction onSignOut;
  final Widget? pendingBanner;
  final Widget? todayMenuCard;
  final Widget? partnerBanner;
  final DashboardPageBuilder? purchasePageBuilder;
  final DashboardPageBuilder? qrPageBuilder;

  @override
  State<UserDashboardShell> createState() => _UserDashboardShellState();
}

class _UserDashboardShellState extends State<UserDashboardShell> {
  int _index = 0;
  bool _actionInFlight = false;

  Future<void> _runAction(AsyncAction action) async {
    if (_actionInFlight) return;
    setState(() => _actionInFlight = true);
    try {
      await action();
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('화면을 열지 못했어요. 잠시 후 다시 시도해 주세요.')),
        );
      }
    } finally {
      if (mounted) setState(() => _actionInFlight = false);
    }
  }

  Future<void> _openActionPage(
    int index,
    DashboardPageBuilder? pageBuilder,
    AsyncAction fallback,
  ) async {
    if (pageBuilder == null) {
      await _runAction(fallback);
      return;
    }
    if (mounted) setState(() => _index = index);
  }

  void _closeActionPage() {
    if (!mounted) return;
    setState(() => _index = 0);
    unawaited(_runAction(widget.onRefresh));
  }

  List<Map<String, dynamic>> get _transactions {
    final history = widget.data['voucher_use_history'];
    if (history is List && history.isNotEmpty) {
      return history
          .whereType<Map>()
          .map((e) => e.cast<String, dynamic>())
          .toList();
    }
    final recent = widget.data['recent_transactions'];
    if (recent is List) {
      return recent
          .whereType<Map>()
          .map((e) => e.cast<String, dynamic>())
          .toList();
    }
    return const [];
  }

  @override
  Widget build(BuildContext context) {
    final screens = [
      _HomeTab(
        data: widget.data,
        transactions: _transactions,
        pendingBanner: widget.pendingBanner,
        onScanQr: () => _openActionPage(
          2,
          widget.qrPageBuilder,
          widget.onScanQr,
        ),
        onBuyVoucher: () => _openActionPage(
          1,
          widget.purchasePageBuilder,
          widget.onBuyVoucher,
        ),
        onHistory: () => setState(() => _index = 3),
        onProfile: () => setState(() => _index = 4),
        onCoupons: widget.onCoupons,
        onEvents: widget.onEvents,
        onAnnouncements: widget.onAnnouncements,
        onReviews: widget.onReviews,
        onRefresh: widget.onRefresh,
        todayMenuCard: widget.todayMenuCard,
        partnerBanner: widget.partnerBanner,
      ),
      if (_index == 1 && widget.purchasePageBuilder != null)
        Padding(
          padding: const EdgeInsets.only(bottom: 78),
          child: widget.purchasePageBuilder!(_closeActionPage),
        )
      else
        const SizedBox.shrink(),
      if (_index == 2 && widget.qrPageBuilder != null)
        Padding(
          padding: const EdgeInsets.only(bottom: 78),
          child: widget.qrPageBuilder!(_closeActionPage),
        )
      else
        const SizedBox.shrink(),
      _HistoryTab(transactions: _transactions),
      _ProfileTab(
        data: widget.data,
        onOpenSettings: widget.onOpenSettings,
        onBuyVoucher: () => _openActionPage(
          1,
          widget.purchasePageBuilder,
          widget.onBuyVoucher,
        ),
        onCoupons: widget.onCoupons,
        onAnnouncements: widget.onAnnouncements,
        onReviews: widget.onReviews,
        onTerms: widget.onTerms,
        onPrivacy: widget.onPrivacy,
        onSignOut: widget.onSignOut,
      ),
    ];
    return Theme(
      data: Theme.of(context).copyWith(
        scaffoldBackgroundColor: AppColors.bg,
        textTheme: Theme.of(context).textTheme.apply(
              fontFamily: 'Pretendard',
              bodyColor: AppColors.fg,
              displayColor: AppColors.fg,
            ),
        colorScheme: const ColorScheme.dark(
          primary: AppColors.blue,
          secondary: AppColors.blueSoft,
          surface: AppColors.card,
          error: AppColors.danger,
        ),
      ),
      child: PopScope(
        canPop: _index == 0,
        onPopInvokedWithResult: (didPop, _) {
          if (!didPop && _index != 0) _closeActionPage();
        },
        child: Scaffold(
          backgroundColor: AppColors.bg,
          extendBody: true,
          body: SafeArea(
            bottom: false,
            child: IndexedStack(index: _index, children: screens),
          ),
          bottomNavigationBar: SafeArea(
            minimum: const EdgeInsets.fromLTRB(14, 0, 14, 14),
            child: AppTabBar(
              index: _index,
              onChanged: (value) async {
                if (value == 1) {
                  await _openActionPage(
                    1,
                    widget.purchasePageBuilder,
                    widget.onBuyVoucher,
                  );
                } else if (value == 2) {
                  await _openActionPage(
                    2,
                    widget.qrPageBuilder,
                    widget.onScanQr,
                  );
                } else {
                  setState(() => _index = value);
                }
              },
            ),
          ),
        ),
      ),
    );
  }
}

class _HomeTab extends StatelessWidget {
  const _HomeTab({
    required this.data,
    required this.transactions,
    required this.pendingBanner,
    required this.onScanQr,
    required this.onBuyVoucher,
    required this.onHistory,
    required this.onProfile,
    required this.onRefresh,
    required this.todayMenuCard,
    required this.partnerBanner,
    required this.onCoupons,
    required this.onEvents,
    required this.onAnnouncements,
    required this.onReviews,
  });

  final Map<String, dynamic> data;
  final List<Map<String, dynamic>> transactions;
  final Widget? pendingBanner;
  final Widget? todayMenuCard;
  final Widget? partnerBanner;
  final AsyncAction onScanQr;
  final AsyncAction onBuyVoucher;
  final VoidCallback onHistory;
  final VoidCallback onProfile;
  final AsyncAction onRefresh;
  final AsyncAction onCoupons;
  final AsyncAction onEvents;
  final AsyncAction onAnnouncements;
  final AsyncAction onReviews;

  @override
  Widget build(BuildContext context) {
    final displayName = _text(data['display_name'], fallback: '사용자');
    final company =
        data['company'] is Map ? _text((data['company'] as Map)['name']) : '';
    final isVoucher = data['account_type'] == 'voucher';
    final voucherBalance = _integer(data['voucher_balance']);
    final monthUsed = _integer(data['month_used']);
    final monthVoucherUses = transactions
        .where((tx) =>
            _isCurrentMonth(tx['created_at']) &&
            (tx['kind'] == 'voucher_use' || tx.containsKey('voucher_id')))
        .toList();
    final fallbackMonthVoucherAmount = monthVoucherUses.fold<int>(
        0, (sum, tx) => sum + _integer(tx['amount']).abs());
    final monthVoucherCount = data.containsKey('voucher_month_used_count')
        ? _integer(data['voucher_month_used_count'])
        : monthVoucherUses.length;
    final monthVoucherAmount = data.containsKey('voucher_month_used_amount')
        ? _integer(data['voucher_month_used_amount'])
        : fallbackMonthVoucherAmount;
    final ticketLabel = isVoucher ? '$voucherBalance' : '-';
    final ticketCaption =
        isVoucher ? '보유 식권 · QR 한 번에 1장 사용' : '회사 장부 결제 · 매장 계약 단가 적용';
    final monthUsage = isVoucher
        ? monthVoucherCount == 0
            ? '사용 내역 없음'
            : '$monthVoucherCount장 · ${_won(monthVoucherAmount)}'
        : monthUsed > 0
            ? _won(monthUsed)
            : '사용 내역 없음';

    return RefreshIndicator(
      color: AppColors.blue,
      backgroundColor: AppColors.card,
      onRefresh: onRefresh,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 96),
        children: [
          _AppHeader(
            displayName: displayName,
            subtitle: [company, '돈토식당'].where((e) => e.isNotEmpty).join(' · '),
            onProfile: onProfile,
          ),
          if (pendingBanner != null) ...[
            const SizedBox(height: 12),
            pendingBanner!,
          ],
          const SizedBox(height: 16),
          MealTicketCard(
            remainingCountLabel: ticketLabel,
            caption: ticketCaption,
            monthUsage: monthUsage,
            onTapQr: onScanQr,
            onBuyTicket: isVoucher ? onBuyVoucher : null,
            state: isVoucher && voucherBalance == 0
                ? TicketState.empty
                : TicketState.active,
          ),
          const SizedBox(height: 16),
          _HomeShortcuts(
            onCoupons: onCoupons,
            onEvents: onEvents,
            onAnnouncements: onAnnouncements,
            onReviews: onReviews,
          ),
          if (todayMenuCard != null) ...[
            const SizedBox(height: 16),
            todayMenuCard!,
          ],
          SectionHeader(title: '최근 이용', onViewAll: onHistory),
          if (transactions.isEmpty)
            const _EmptyState(
              message: '아직 이용 내역이 없어요.\n식당에서 QR로 첫 식사를 결제해 보세요.',
            )
          else
            ...transactions.take(3).toList().asMap().entries.map((entry) {
              final tx = entry.value;
              return TxListItem(
                showDivider: entry.key != 0,
                slot: _slot(tx),
                title: _title(tx),
                subtitle: _transactionSubtitle(tx),
                amount: '-${_amountLabel(tx)}',
                style: AmountStyle.neg,
              );
            }),
          if (partnerBanner != null) partnerBanner!,
        ],
      ),
    );
  }
}

class _HomeShortcuts extends StatelessWidget {
  const _HomeShortcuts({
    required this.onCoupons,
    required this.onEvents,
    required this.onAnnouncements,
    required this.onReviews,
  });

  final AsyncAction onCoupons;
  final AsyncAction onEvents;
  final AsyncAction onAnnouncements;
  final AsyncAction onReviews;

  @override
  Widget build(BuildContext context) {
    final items = <(IconData, String, AsyncAction)>[
      (Icons.confirmation_number_rounded, '쿠폰함', onCoupons),
      (Icons.celebration_rounded, '이벤트', onEvents),
      (Icons.campaign_rounded, '공지사항', onAnnouncements),
      (Icons.rate_review_rounded, '리뷰', onReviews),
    ];
    return DarkCard(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 12),
      child: Row(
        children: [
          for (final item in items)
            Expanded(
              child: InkWell(
                onTap: item.$3,
                borderRadius: BorderRadius.circular(16),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 38,
                        height: 38,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: AppColors.cardHi,
                          borderRadius: BorderRadius.circular(13),
                        ),
                        child:
                            Icon(item.$1, color: AppColors.blueSoft, size: 21),
                      ),
                      const SizedBox(height: 7),
                      FittedBox(
                        fit: BoxFit.scaleDown,
                        child: Text(item.$2,
                            maxLines: 1, style: AppTextStyles.caption),
                      ),
                    ],
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _AppHeader extends StatelessWidget {
  const _AppHeader({
    required this.displayName,
    required this.subtitle,
    required this.onProfile,
  });
  final String displayName;
  final String subtitle;
  final VoidCallback onProfile;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 60,
        child: Row(
          children: [
            InkWell(
              onTap: onProfile,
              borderRadius: BorderRadius.circular(18),
              child: Container(
                width: 44,
                height: 44,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: AppColors.blue,
                  borderRadius: BorderRadius.circular(16),
                ),
                child: Text(
                  displayName.characters.first,
                  style: const TextStyle(
                      color: AppColors.fg,
                      fontSize: 17,
                      fontWeight: FontWeight.w800),
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('$displayName님', style: AppTextStyles.cardTitle),
                  const SizedBox(height: 3),
                  Text(subtitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTextStyles.caption),
                ],
              ),
            ),
            IconButton(
              tooltip: '내정보',
              onPressed: onProfile,
              icon: const Icon(Icons.menu_rounded, color: AppColors.fg),
            ),
          ],
        ),
      );
}

class _HistoryTab extends StatelessWidget {
  const _HistoryTab({required this.transactions});
  final List<Map<String, dynamic>> transactions;

  @override
  Widget build(BuildContext context) {
    final total = transactions.fold<int>(
        0, (sum, tx) => sum + _integer(tx['amount']).abs());
    final grouped = <String, List<Map<String, dynamic>>>{};
    for (final tx in transactions) {
      grouped.putIfAbsent(_dayLabel(tx['created_at']), () => []).add(tx);
    }
    return ListView(
      padding: const EdgeInsets.fromLTRB(18, 22, 18, 112),
      children: [
        const Text('이용내역', style: AppTextStyles.screenTitle),
        const SizedBox(height: 22),
        _MonthSelector(month: DateTime.now()),
        const SizedBox(height: 12),
        DarkCard(
          child: Row(
            children: [
              _SummaryCell(label: '사용', value: '${transactions.length}건'),
              const _VerticalLine(),
              _SummaryCell(label: '금액', value: _won(total)),
              const _VerticalLine(),
              _SummaryCell(label: '내 부담', value: _won(total)),
            ],
          ),
        ),
        if (transactions.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 16),
            child:
                _EmptyState(message: '아직 이용 내역이 없어요.\n식당에서 QR로 첫 식사를 결제해 보세요.'),
          )
        else
          for (final group in grouped.entries) ...[
            Padding(
              padding: const EdgeInsets.only(top: 22, bottom: 2),
              child: Text(group.key,
                  style: AppTextStyles.caption.copyWith(color: AppColors.fg)),
            ),
            for (var i = 0; i < group.value.length; i++)
              TxListItem(
                showDivider: i != 0,
                slot: _slot(group.value[i]),
                title: _title(group.value[i]),
                subtitle: _transactionSubtitle(group.value[i]),
                amount: '-${_amountLabel(group.value[i])}',
                style: AmountStyle.neg,
              ),
          ],
      ],
    );
  }
}

// Kept only as a legacy data presentation reference; the dashboard no longer
// exposes a ledger tab or route.
// ignore: unused_element
class _LedgerTab extends StatelessWidget {
  const _LedgerTab({required this.data});
  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final monthUsed = _integer(data['month_used']);
    final isEmployee = data['account_type'] == 'ledger';
    return ListView(
      padding: const EdgeInsets.fromLTRB(18, 22, 18, 112),
      children: [
        const Text('장부', style: AppTextStyles.screenTitle),
        const SizedBox(height: 22),
        Container(
          height: 208,
          padding: const EdgeInsets.all(22),
          decoration: BoxDecoration(
            gradient: const LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [AppColors.blue, AppColors.blueSoft],
            ),
            borderRadius: BorderRadius.circular(22),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('${DateTime.now().month}월 미정산 금액',
                  style: AppTextStyles.caption.copyWith(color: AppColors.fg)),
              const Spacer(),
              Text(isEmployee ? _won(monthUsed) : '-',
                  style: AppTextStyles.heroNumber),
              const SizedBox(height: 10),
              Text(
                isEmployee
                    ? '실제 이용 누적 · 회사 정산 주기에 따라 확정'
                    : '장부 계정에만 제공되는 정보예요.',
                style: AppTextStyles.caption.copyWith(color: AppColors.fg),
              ),
            ],
          ),
        ),
        const SizedBox(height: 22),
        const DarkCard(child: _SettlementTimeline()),
        const SectionHeader(title: '지난 정산'),
        const _EmptyState(message: '확정된 지난 정산 정보가 아직 제공되지 않아요.'),
      ],
    );
  }
}

class _SettlementTimeline extends StatelessWidget {
  const _SettlementTimeline();

  @override
  Widget build(BuildContext context) {
    const items = [
      ('이용 누적 중', '이번 달 실제 이용 금액이 쌓이고 있어요.'),
      ('정산 확정', '회사 정산이 확정되면 표시됩니다.'),
      ('결제 완료', '결제 완료 정보가 제공되면 표시됩니다.'),
    ];
    return Column(
      children: [
        for (var i = 0; i < items.length; i++)
          IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 22,
                  child: Column(
                    children: [
                      Container(
                        width: 14,
                        height: 14,
                        decoration: BoxDecoration(
                          color: i == 0 ? AppColors.blue : AppColors.timeline,
                          shape: BoxShape.circle,
                        ),
                      ),
                      if (i < items.length - 1)
                        Expanded(
                          child: Container(width: 2, color: AppColors.timeline),
                        ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Padding(
                    padding:
                        EdgeInsets.only(bottom: i == items.length - 1 ? 0 : 22),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(items[i].$1, style: AppTextStyles.cardTitle),
                        const SizedBox(height: 4),
                        Text(items[i].$2, style: AppTextStyles.caption),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _ProfileTab extends StatelessWidget {
  const _ProfileTab({
    required this.data,
    required this.onOpenSettings,
    required this.onBuyVoucher,
    required this.onCoupons,
    required this.onAnnouncements,
    required this.onReviews,
    required this.onTerms,
    required this.onPrivacy,
    required this.onSignOut,
  });
  final Map<String, dynamic> data;
  final AsyncAction onOpenSettings;
  final AsyncAction onBuyVoucher;
  final AsyncAction onCoupons;
  final AsyncAction onAnnouncements;
  final AsyncAction onReviews;
  final AsyncAction onTerms;
  final AsyncAction onPrivacy;
  final AsyncAction onSignOut;

  @override
  Widget build(BuildContext context) {
    final name = _text(data['display_name'], fallback: '사용자');
    final company =
        data['company'] is Map ? _text((data['company'] as Map)['name']) : '';
    return ListView(
      padding: const EdgeInsets.fromLTRB(18, 22, 18, 112),
      children: [
        const Text('내정보', style: AppTextStyles.screenTitle),
        const SizedBox(height: 24),
        Row(
          children: [
            Container(
              width: 56,
              height: 56,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: AppColors.blue,
                borderRadius: BorderRadius.circular(20),
              ),
              child: Text(name.characters.first,
                  style: const TextStyle(
                      color: AppColors.fg,
                      fontSize: 20,
                      fontWeight: FontWeight.w800)),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(name,
                      style: const TextStyle(
                          color: AppColors.fg,
                          fontSize: 19,
                          fontWeight: FontWeight.w800)),
                  const SizedBox(height: 4),
                  Text(company.isEmpty ? _roleLabel(data['role']) : company,
                      style: AppTextStyles.caption),
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: 24),
        _SettingGroup(rows: [
          _SettingRow('휴대폰 번호', _text(data['phone'], fallback: '-')),
          const _SettingRow('인증수단', '이메일'),
          _SettingRow(
              '결제수단', data['account_type'] == 'ledger' ? '회사 장부' : '식권'),
        ]),
        const SizedBox(height: 12),
        _SettingGroup(rows: [
          _SettingRow('결제 알림', '켜짐', onTap: onOpenSettings),
          _SettingRow('계정 설정', '이름·비밀번호', onTap: onOpenSettings),
        ]),
        const SizedBox(height: 12),
        _SettingGroup(rows: [
          _SettingRow('쿠폰함', '', onTap: onCoupons),
          _SettingRow('식권 상품', '', onTap: onBuyVoucher),
          _SettingRow('공지사항', '', onTap: onAnnouncements),
          _SettingRow('구매 인증 리뷰', '', onTap: onReviews),
        ]),
        const SizedBox(height: 12),
        _SettingGroup(rows: [
          _SettingRow('개인정보 처리방침', '', onTap: onPrivacy),
          _SettingRow('이용약관', '', onTap: onTerms),
          const _SettingRow('앱 버전', '0.1.7'),
          _SettingRow('로그아웃', '', onTap: onSignOut, danger: true),
        ]),
      ],
    );
  }
}

class _SettingGroup extends StatelessWidget {
  const _SettingGroup({required this.rows});
  final List<_SettingRow> rows;

  @override
  Widget build(BuildContext context) => DarkCard(
        padding: const EdgeInsets.symmetric(horizontal: 18),
        child: Column(
          children: [
            for (var i = 0; i < rows.length; i++) ...[
              rows[i],
              if (i < rows.length - 1)
                const Divider(height: 1, color: AppColors.lineSoft),
            ],
          ],
        ),
      );
}

class _SettingRow extends StatelessWidget {
  const _SettingRow(this.label, this.value, {this.onTap, this.danger = false});
  final String label;
  final String value;
  final AsyncAction? onTap;
  final bool danger;

  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onTap,
        child: SizedBox(
          height: 58,
          child: Row(
            children: [
              Expanded(
                child: Text(label,
                    style: AppTextStyles.body.copyWith(
                        color: danger ? AppColors.danger : AppColors.fg)),
              ),
              if (value.isNotEmpty) Text(value, style: AppTextStyles.caption),
              if (onTap != null) ...[
                const SizedBox(width: 5),
                const Icon(Icons.chevron_right_rounded,
                    color: AppColors.fg2, size: 20),
              ],
            ],
          ),
        ),
      );
}

class _MonthSelector extends StatelessWidget {
  const _MonthSelector({required this.month});
  final DateTime month;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 48,
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.chevron_left_rounded, color: AppColors.fg2),
            const SizedBox(width: 18),
            Text('${month.year}년 ${month.month}월',
                style: AppTextStyles.cardTitle),
            const SizedBox(width: 18),
            const Icon(Icons.chevron_right_rounded, color: AppColors.fg2),
          ],
        ),
      );
}

class _SummaryCell extends StatelessWidget {
  const _SummaryCell({required this.label, required this.value});
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) => Expanded(
        child: Column(
          children: [
            Text(label, style: AppTextStyles.caption),
            const SizedBox(height: 8),
            FittedBox(child: Text(value, style: AppTextStyles.cardTitle)),
          ],
        ),
      );
}

class _VerticalLine extends StatelessWidget {
  const _VerticalLine();
  @override
  Widget build(BuildContext context) =>
      const SizedBox(height: 38, child: VerticalDivider(color: AppColors.line));
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.message});
  final String message;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 24),
        child: Text(message,
            textAlign: TextAlign.center,
            style: AppTextStyles.caption.copyWith(height: 1.6)),
      );
}

String _text(Object? value, {String fallback = ''}) {
  final text = value?.toString().trim() ?? '';
  return text.isEmpty ? fallback : text;
}

int _integer(Object? value) =>
    value is num ? value.round() : int.tryParse('$value') ?? 0;

String _won(int value) {
  final digits = value.abs().toString();
  final formatted =
      digits.replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (match) => ',');
  return '${value < 0 ? '-' : ''}$formatted원';
}

String _amountLabel(Map<String, dynamic> tx) {
  final amount = _integer(tx['amount']).abs();
  return tx['kind'] == 'voucher_use' || tx.containsKey('voucher_id')
      ? '1장'
      : _won(amount);
}

String _title(Map<String, dynamic> tx) {
  final merchant = _text(tx['merchant_name']);
  final title = _text(tx['title'], fallback: '식대 사용');
  return merchant.isEmpty ? title : '$merchant $title';
}

MealSlot _slot(Map<String, dynamic> tx) {
  final date = DateTime.tryParse(_text(tx['created_at']))?.toLocal();
  return (date?.hour ?? 0) < 15 ? MealSlot.lunch : MealSlot.dinner;
}

String _mealLabel(Map<String, dynamic> tx) =>
    _slot(tx) == MealSlot.lunch ? '중식' : '석식';

String _transactionSubtitle(Map<String, dynamic> tx) {
  final parsed = DateTime.tryParse(_text(tx['created_at']))?.toLocal();
  if (parsed == null) return _mealLabel(tx);
  final hour = parsed.hour.toString().padLeft(2, '0');
  final minute = parsed.minute.toString().padLeft(2, '0');
  return '${_mealLabel(tx)} · ${parsed.month}월 ${parsed.day}일 $hour:$minute';
}

bool _isCurrentMonth(Object? raw) {
  final date = DateTime.tryParse(_text(raw))?.toLocal();
  if (date == null) return false;
  final now = DateTime.now();
  return date.year == now.year && date.month == now.month;
}

String _dayLabel(Object? raw) {
  final date = DateTime.tryParse(_text(raw))?.toLocal();
  if (date == null) return '날짜 정보 없음';
  const weekdays = ['월', '화', '수', '목', '금', '토', '일'];
  return '${date.month}월 ${date.day}일 (${weekdays[date.weekday - 1]})';
}

String _roleLabel(Object? raw) => switch ('$raw') {
      'employee' => '회사 임직원',
      'customer' => '일반 사용자',
      _ => '사용자',
    };
