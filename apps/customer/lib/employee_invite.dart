import 'package:flutter/material.dart';

import 'theme/app_colors.dart';

/// A company registered this personal member's (SMS-verified) number in bulk.
/// `/me` carries it as `employee_invite_offer` until the member answers.
class EmployeeInviteOffer {
  const EmployeeInviteOffer({required this.inviteId, required this.companyName});

  final String inviteId;
  final String companyName;

  static EmployeeInviteOffer? fromMe(Map<String, dynamic> me) {
    final raw = me['employee_invite_offer'];
    if (raw is! Map) return null;
    final id = '${raw['invite_id'] ?? ''}'.trim();
    final company = '${raw['company_name'] ?? ''}'.trim();
    if (id.isEmpty || company.isEmpty) return null;
    return EmployeeInviteOffer(inviteId: id, companyName: company);
  }
}

/// Offers asked in this app session. "나중에" must not bring the question back
/// on every refresh; it returns the next time the app is started.
final Set<String> _askedThisSession = <String>{};

/// True the first time an offer is seen in this session.
bool shouldAskEmployeeInvite(EmployeeInviteOffer? offer) =>
    offer != null && _askedThisSession.add(offer.inviteId);

@visibleForTesting
void resetEmployeeInviteMemory() => _askedThisSession.clear();

/// true = switch to the company, false = refuse (shown to the company admin),
/// null = decide later.
Future<bool?> showEmployeeInviteDialog(
        BuildContext context, EmployeeInviteOffer offer) =>
    showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => DefaultTextStyle.merge(
        style: const TextStyle(fontFamily: 'Pretendard'),
        child: AlertDialog(
          key: const ValueKey('employee-invite-dialog'),
          backgroundColor: AppColors.card,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(22),
            side: const BorderSide(color: AppColors.line),
          ),
          title: Text('${offer.companyName} 직원으로 전환할까요?',
              style: const TextStyle(
                  color: AppColors.fg,
                  fontFamily: 'Pretendard',
                  fontSize: 18,
                  fontWeight: FontWeight.w800)),
          content: Text(
            '${offer.companyName}에서 회원님의 휴대폰 번호를 직원으로 등록했어요.\n\n'
            '전환하면 회사 식대로 식사할 수 있고, 가지고 있는 식권은 "내 식권"으로 계속 쓸 수 있어요.\n\n'
            '거절하면 회사 관리자에게 거절한 것으로 표시돼요.',
            style: const TextStyle(
                color: AppColors.fg2,
                fontFamily: 'Pretendard',
                fontSize: 14,
                height: 1.5),
          ),
          actionsPadding: const EdgeInsets.fromLTRB(18, 0, 18, 16),
          // The buttons are stacked at full width. The app theme gives FilledButton an
          // unbounded minimum width, so placing it in a shrink-wrapped Row next to the
          // other buttons made it disappear on the device.
          actions: [
            SizedBox(
              width: double.maxFinite,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  FilledButton(
                    key: const ValueKey('employee-invite-accept'),
                    style: FilledButton.styleFrom(
                        backgroundColor: AppColors.blue,
                        foregroundColor: Colors.white,
                        minimumSize: const Size.fromHeight(50),
                        textStyle: const TextStyle(
                            fontFamily: 'Pretendard',
                            fontSize: 16,
                            fontWeight: FontWeight.w700)),
                    onPressed: () => Navigator.of(dialogContext).pop(true),
                    child: const Text('전환하기'),
                  ),
                  const SizedBox(height: 6),
                  Row(children: [
                    Expanded(
                      child: TextButton(
                        key: const ValueKey('employee-invite-later'),
                        style: TextButton.styleFrom(
                            foregroundColor: AppColors.fg2,
                            minimumSize: const Size.fromHeight(44),
                            textStyle:
                                const TextStyle(fontFamily: 'Pretendard')),
                        onPressed: () => Navigator.of(dialogContext).pop(),
                        child: const Text('나중에'),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: TextButton(
                        key: const ValueKey('employee-invite-decline'),
                        style: TextButton.styleFrom(
                            foregroundColor: AppColors.danger,
                            minimumSize: const Size.fromHeight(44),
                            textStyle: const TextStyle(
                                fontFamily: 'Pretendard',
                                fontWeight: FontWeight.w700)),
                        onPressed: () => Navigator.of(dialogContext).pop(false),
                        child: const Text('거절'),
                      ),
                    ),
                  ]),
                ],
              ),
            ),
          ],
        ),
      ),
    );
