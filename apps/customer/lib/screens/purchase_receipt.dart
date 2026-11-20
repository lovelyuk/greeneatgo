import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../load_error.dart';
import '../payment_completion.dart';
import '../theme/app_colors.dart';

/// 구매 내역 → 영수증. Loads one owned order (`GET /payments/history/{id}`) and
/// shows the same paper receipt as right after payment, plus refund state and
/// the values the provider's slip page asks for.
class PurchaseReceiptScreen extends StatefulWidget {
  const PurchaseReceiptScreen({super.key, required this.load, this.onOpenReceipt});

  final Future<Map<String, dynamic>> Function() load;
  final void Function(BuildContext context, String title, String url)?
      onOpenReceipt;

  @override
  State<PurchaseReceiptScreen> createState() => _PurchaseReceiptScreenState();
}

class _PurchaseReceiptScreenState extends State<PurchaseReceiptScreen> {
  late Future<Map<String, dynamic>> _future = widget.load();

  @override
  Widget build(BuildContext context) => FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const _ReceiptFrame(
              child: Center(
                  child: CircularProgressIndicator(color: AppColors.blue)),
            );
          }
          final data = snapshot.data;
          final completion = _map(data?['completion']);
          if (snapshot.hasError || completion == null) {
            return _ReceiptFrame(
              child: Center(
                child: Padding(
                  padding: const EdgeInsets.all(28),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    Text(
                        snapshot.hasError
                            ? friendlyLoadError(snapshot.error!)
                            : '영수증을 불러오지 못했어요.',
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                            color: AppColors.fg2, fontSize: 15, height: 1.5)),
                    const SizedBox(height: 16),
                    FilledButton(
                      key: const ValueKey('purchase-receipt-retry'),
                      style: FilledButton.styleFrom(
                        backgroundColor: AppColors.blue,
                        foregroundColor: Colors.white,
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14)),
                        textStyle: const TextStyle(
                            fontFamily: 'Pretendard',
                            fontWeight: FontWeight.w700),
                      ),
                      onPressed: () => setState(() {
                        _future = widget.load();
                      }),
                      child: const Text('다시 시도'),
                    ),
                  ]),
                ),
              ),
            );
          }
          final summary = _map(data?['summary']) ?? const <String, dynamic>{};
          final refund = _map(data?['refund']);
          final lookup = _map(_map(data?['receipt'])?['lookup']);
          final product = '${summary['product_name'] ?? ''}'.trim();
          final merchant = '${summary['merchant_name'] ?? ''}'.trim();
          final slipTitle = '${data?['slip_title'] ?? ''}'.trim();
          final payment = _map(completion['payment']) == null
              ? PaymentCompletionData.pointOnly(completion)
              : PaymentCompletionData.fromConfirmDto(completion);
          final hasSlip = payment.salesSlipUrl.isNotEmpty;
          return PaymentCompletionScreen(
            key: const ValueKey('purchase-receipt'),
            payment: payment,
            title: '결제 영수증',
            headline: product.isEmpty ? '식권 구매' : product,
            subline: merchant,
            showCheck: false,
            showBack: true,
            salesSlipTitle: slipTitle.isEmpty ? null : slipTitle,
            notice: refund == null ? null : _RefundNotice(refund: refund),
            footer:
                hasSlip && lookup != null ? _SlipLookup(lookup: lookup) : null,
            doneLabel: '닫기',
            onDone: () => Navigator.of(context).pop(),
            onOpenReceipt: widget.onOpenReceipt,
          );
        },
      );
}

class _ReceiptFrame extends StatelessWidget {
  const _ReceiptFrame({required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) => DefaultTextStyle.merge(
        style: const TextStyle(fontFamily: 'Pretendard'),
        child: Scaffold(
          backgroundColor: AppColors.bg,
          appBar: AppBar(
            backgroundColor: AppColors.bg,
            foregroundColor: AppColors.fg,
            surfaceTintColor: AppColors.bg,
            centerTitle: true,
            title: const Text('결제 영수증',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
          ),
          body: child,
        ),
      );
}

class _RefundNotice extends StatelessWidget {
  const _RefundNotice({required this.refund});
  final Map<String, dynamic> refund;

  @override
  Widget build(BuildContext context) {
    final done = refund['status'] == 'completed';
    final amount = refund['refund_amount'];
    final when = '${refund['completed_at'] ?? ''}';
    final parts = [
      if (amount is num) formatPaymentAmount(amount),
      if (done && when.isNotEmpty) formatPaymentDateTime(when),
    ];
    return Container(
      key: const ValueKey('purchase-receipt-refund'),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.line),
      ),
      child: Row(children: [
        const Icon(Icons.undo_rounded, color: AppColors.blueSoft, size: 20),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(done ? '환불 완료된 결제예요' : '환불을 처리하고 있어요',
                  style: const TextStyle(
                      color: AppColors.fg,
                      fontSize: 14.5,
                      fontWeight: FontWeight.w700)),
              if (parts.isNotEmpty) ...[
                const SizedBox(height: 2),
                Text(parts.join(' · '),
                    style:
                        const TextStyle(color: AppColors.fg2, fontSize: 13)),
              ],
            ],
          ),
        ),
      ]),
    );
  }
}

/// The provider's slip page asks the viewer to confirm the payment first
/// (date, amount, approval or order number): show those values with a copy button.
class _SlipLookup extends StatelessWidget {
  const _SlipLookup({required this.lookup});
  final Map<String, dynamic> lookup;

  @override
  Widget build(BuildContext context) {
    final number = '${lookup['number'] ?? ''}';
    final amount = lookup['amount'];
    final label = lookup['number_type'] == 'approval' ? '승인번호' : '주문번호';
    return Container(
      key: const ValueKey('purchase-receipt-lookup'),
      padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('전표 화면에서 조회 정보를 물으면 아래 값을 넣어 주세요',
              style: TextStyle(color: AppColors.fg2, fontSize: 12.5)),
          const SizedBox(height: 8),
          Row(children: [
            Expanded(
              child: Text(
                [
                  if ('${lookup['date'] ?? ''}'.isNotEmpty)
                    '결제일 ${lookup['date']}',
                  if (amount is num) '금액 ${formatPaymentAmount(amount)}',
                  if (number.isNotEmpty) '$label $number',
                ].join('\n'),
                style: const TextStyle(
                    color: AppColors.fg, fontSize: 14, height: 1.5),
              ),
            ),
            if (number.isNotEmpty)
              TextButton(
                key: const ValueKey('purchase-receipt-copy'),
                style: TextButton.styleFrom(
                  foregroundColor: AppColors.blueSoft,
                  textStyle: const TextStyle(
                      fontFamily: 'Pretendard', fontWeight: FontWeight.w700),
                ),
                onPressed: () {
                  final messenger = ScaffoldMessenger.of(context);
                  messenger.showSnackBar(
                      SnackBar(content: Text('$label를 복사했어요')));
                  Clipboard.setData(ClipboardData(text: number));
                },
                child: Text('$label 복사'),
              ),
          ]),
        ],
      ),
    );
  }
}

Map<String, dynamic>? _map(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return value.cast<String, dynamic>();
  return null;
}
