import 'package:flutter/material.dart';

import 'theme/app_colors.dart';
import 'package:webview_flutter/webview_flutter.dart';

/// Normalized payment confirmation information used by the completion screen.
class PaymentCompletionData {
  const PaymentCompletionData({
    required this.amount,
    required this.method,
    required this.methodLabel,
    required this.approvedAt,
    required this.transactionId,
    required this.issuerName,
    required this.maskedCardNumber,
    required this.authorizationNumber,
    required this.bankName,
    required this.cashReceiptAuthorizationNumber,
    required this.cashReceiptStatus,
    required this.salesSlipUrl,
    required this.cashReceiptUrl,
  });

  factory PaymentCompletionData.fromConfirmDto(Map<String, dynamic> json) {
    final data = _map(json['data']) ?? json;
    final payment = _map(data['payment']) ?? const <String, dynamic>{};
    final receipts = _map(data['receipts']) ?? const <String, dynamic>{};

    String text(Map<String, dynamic> source, String key) =>
        (source[key] ?? '').toString().trim();
    String firstText(List<(Map<String, dynamic>, String)> candidates) {
      for (final (source, key) in candidates) {
        final value = text(source, key);
        if (value.isNotEmpty) return value;
      }
      return '';
    }

    return PaymentCompletionData(
      amount: (data['amount'] as num?)?.round() ?? 0,
      method: text(payment, 'method').toUpperCase(),
      methodLabel: text(payment, 'method_label'),
      approvedAt: text(payment, 'approved_at'),
      transactionId: text(payment, 'transaction_id'),
      issuerName: _cleanProviderLabel(text(payment, 'issuer_name')),
      maskedCardNumber: text(payment, 'masked_card_number'),
      authorizationNumber: text(payment, 'authorization_number'),
      bankName: text(payment, 'bank_name'),
      cashReceiptAuthorizationNumber:
          text(payment, 'cash_receipt_authorization_number'),
      cashReceiptStatus: firstText([
        (payment, 'cash_receipt_status'),
        (payment, 'cashReceiptStatus'),
        (receipts, 'cash_receipt_status'),
        (receipts, 'cashReceiptStatus'),
        (data, 'cash_receipt_status'),
        (data, 'cashReceiptStatus'),
      ]).toUpperCase(),
      salesSlipUrl: text(receipts, 'sales_slip_url'),
      cashReceiptUrl: text(receipts, 'cash_receipt_url'),
    );
  }

  /// Used for point-only orders, where provider confirmation is not performed.
  factory PaymentCompletionData.pointOnly(Map<String, dynamic> order) {
    return PaymentCompletionData(
      amount: (order['point_amount'] as num?)?.round() ??
          (order['amount'] as num?)?.round() ??
          0,
      method: 'POINT',
      methodLabel: '포인트',
      approvedAt: '',
      transactionId: (order['order_id'] ?? '').toString().trim(),
      issuerName: '',
      maskedCardNumber: '',
      authorizationNumber: '',
      bankName: '',
      cashReceiptAuthorizationNumber: '',
      cashReceiptStatus: '',
      salesSlipUrl: '',
      cashReceiptUrl: '',
    );
  }

  final int amount;
  final String method;
  final String methodLabel;
  final String approvedAt;
  final String transactionId;
  final String issuerName;
  final String maskedCardNumber;
  final String authorizationNumber;
  final String bankName;
  final String cashReceiptAuthorizationNumber;
  final String cashReceiptStatus;
  final String salesSlipUrl;
  final String cashReceiptUrl;

  bool get isCard => method == 'CARD' || method == 'NAVERPAY';
  bool get isBank => method == 'BANK';

  String get displayedMethod {
    if (methodLabel.isNotEmpty) return methodLabel;
    if (isCard) return '카드';
    if (isBank) return '계좌이체';
    return method;
  }

  String get accountLabel => isCard ? '카드번호' : '이용은행';

  String get accountValue {
    if (isCard) {
      return [issuerName, maskedCardNumber]
          .where((value) => value.isNotEmpty)
          .join(' ');
    }
    return bankName;
  }

  bool get showSalesSlip => (isCard || isBank) && salesSlipUrl.isNotEmpty;

  bool get showCashReceipt =>
      isBank && cashReceiptStatus == 'ISSUED' && cashReceiptUrl.isNotEmpty;
}

Map<String, dynamic>? _map(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return value.cast<String, dynamic>();
  return null;
}

String _cleanProviderLabel(String value) =>
    value.contains('\ufffd') ? '' : value;

String formatPaymentAmount(num amount) =>
    '${amount.round().toString().replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+(?!\d))'), (match) => '${match[1]},')}원';

String formatPaymentDateTime(String value) {
  if (value.trim().isEmpty) return '-';
  final parsed = DateTime.tryParse(value);
  if (parsed == null) return value;
  final date = parsed.isUtc ? parsed.toLocal() : parsed;
  String two(int number) => number.toString().padLeft(2, '0');
  return '${date.year}.${two(date.month)}.${two(date.day)} '
      '${two(date.hour)}:${two(date.minute)}:${two(date.second)}';
}

class PaymentCompletionScreen extends StatelessWidget {
  const PaymentCompletionScreen({
    super.key,
    required this.payment,
    this.onDone,
    this.onOpenReceipt,
  });

  final PaymentCompletionData payment;
  final VoidCallback? onDone;
  final void Function(BuildContext context, String title, String url)?
      onOpenReceipt;

  void _openReceipt(BuildContext context, String title, String url) {
    final callback = onOpenReceipt;
    if (callback != null) {
      callback(context, title, url);
      return;
    }
    Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => ReceiptWebViewScreen(title: title, url: url),
    ));
  }

  @override
  Widget build(BuildContext context) {
    // D3: current dark design + paper receipt (same paper tone as the home
    // meal ticket), blue check. Replaces the white page with olive accents.
    return DefaultTextStyle.merge(
      style: const TextStyle(fontFamily: 'Pretendard'),
      child: Scaffold(
      backgroundColor: AppColors.bg,
      appBar: AppBar(
        automaticallyImplyLeading: false,
        backgroundColor: AppColors.bg,
        foregroundColor: AppColors.fg,
        surfaceTintColor: AppColors.bg,
        centerTitle: true,
        title: const Text(
          '결제 완료',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
        ),
      ),
      body: SafeArea(
        bottom: false,
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 28),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Center(
                child: Container(
                  key: const ValueKey('payment-done-check'),
                  width: 64,
                  height: 64,
                  decoration: BoxDecoration(
                    color: AppColors.blue,
                    shape: BoxShape.circle,
                    boxShadow: [
                      BoxShadow(
                          color: AppColors.blue.withValues(alpha: 0.18),
                          spreadRadius: 9),
                    ],
                  ),
                  child: const Icon(Icons.check_rounded,
                      color: Colors.white, size: 38),
                ),
              ),
              const SizedBox(height: 20),
              const Text(
                '결제가 완료되었습니다',
                textAlign: TextAlign.center,
                style: TextStyle(
                    color: AppColors.fg,
                    fontSize: 24,
                    fontWeight: FontWeight.w900),
              ),
              const SizedBox(height: 6),
              const Text(
                '이용해 주셔서 감사합니다.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppColors.fg2, fontSize: 14),
              ),
              const SizedBox(height: 22),
              _PaperReceipt(payment: payment),
              if (payment.showSalesSlip || payment.showCashReceipt) ...[
                const SizedBox(height: 12),
                if (payment.showSalesSlip)
                  _DarkOutlineButton(
                    label: payment.isCard ? '카드 매출전표 보기' : '계좌이체 전표 보기',
                    onPressed: () => _openReceipt(
                      context,
                      payment.isCard ? '카드 매출전표' : '계좌이체 전표',
                      payment.salesSlipUrl,
                    ),
                  ),
                if (payment.showCashReceipt) ...[
                  const SizedBox(height: 8),
                  _DarkOutlineButton(
                    label: '현금영수증 보기',
                    onPressed: () =>
                        _openReceipt(context, '현금영수증', payment.cashReceiptUrl),
                  ),
                ],
              ],
            ],
          ),
        ),
      ),
      bottomNavigationBar: Container(
        color: AppColors.bg,
        child: SafeArea(
          minimum: const EdgeInsets.fromLTRB(20, 10, 20, 16),
          child: SizedBox(
            height: 54,
            child: FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.blue,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16)),
                textStyle: const TextStyle(
                    fontFamily: 'Pretendard',
                    fontSize: 16,
                    fontWeight: FontWeight.w800),
              ),
              onPressed: onDone ?? () => Navigator.of(context).pop(true),
              child: const Text('확인'),
            ),
          ),
        ),
      ),
    ));
  }
}

/// Paper meal-ticket receipt: amount on top, perforation, detail rows.
class _PaperReceipt extends StatelessWidget {
  const _PaperReceipt({required this.payment});
  final PaymentCompletionData payment;

  @override
  Widget build(BuildContext context) => Container(
        key: const ValueKey('payment-paper-receipt'),
        decoration: BoxDecoration(
          color: AppColors.paper,
          borderRadius: BorderRadius.circular(20),
        ),
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(18, 20, 18, 18),
            child: Column(children: [
              const Text('결제 금액',
                  style: TextStyle(color: Color(0xFF6B6F78), fontSize: 13)),
              const SizedBox(height: 4),
              Text(
                formatPaymentAmount(payment.amount),
                style: const TextStyle(
                    color: AppColors.ink,
                    fontSize: 36,
                    fontWeight: FontWeight.w900,
                    letterSpacing: -0.5),
              ),
            ]),
          ),
          const _ReceiptPerforation(),
          Padding(
            padding: const EdgeInsets.fromLTRB(18, 4, 18, 8),
            child: Column(children: [
              _DetailRow(label: '결제수단', value: payment.displayedMethod),
              _DetailRow(
                  label: payment.accountLabel, value: payment.accountValue),
              _DetailRow(label: '승인번호', value: payment.authorizationNumber),
              _DetailRow(
                  label: '거래일시',
                  value: formatPaymentDateTime(payment.approvedAt)),
              _DetailRow(
                  label: '거래번호(TRXID)',
                  value: payment.transactionId,
                  last: true),
            ]),
          ),
        ]),
      );
}

class _ReceiptPerforation extends StatelessWidget {
  const _ReceiptPerforation();

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 22,
        child: Stack(clipBehavior: Clip.none, children: [
          Positioned.fill(
            child: LayoutBuilder(builder: (context, c) {
              final n = (c.maxWidth / 10).floor();
              return Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: List.generate(
                      n > 2 ? n - 2 : 0,
                      (_) => Container(
                          width: 5, height: 2, color: AppColors.ticketLine)),
                ),
              );
            }),
          ),
          Positioned(
              left: -11,
              top: 0,
              child: Container(
                  width: 22,
                  height: 22,
                  decoration: const BoxDecoration(
                      color: AppColors.bg, shape: BoxShape.circle))),
          Positioned(
              right: -11,
              top: 0,
              child: Container(
                  width: 22,
                  height: 22,
                  decoration: const BoxDecoration(
                      color: AppColors.bg, shape: BoxShape.circle))),
        ]),
      );
}

class _DarkOutlineButton extends StatelessWidget {
  const _DarkOutlineButton({required this.label, required this.onPressed});
  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) => OutlinedButton(
        style: OutlinedButton.styleFrom(
          foregroundColor: const Color(0xFFC9D0DE),
          side: const BorderSide(color: AppColors.line),
          backgroundColor: AppColors.card,
          minimumSize: const Size.fromHeight(48),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        ),
        onPressed: onPressed,
        child: Text(label),
      );
}

class _DetailRow extends StatelessWidget {
  const _DetailRow(
      {required this.label, required this.value, this.last = false});

  final String label;
  final String value;
  final bool last;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(vertical: 10),
        decoration: BoxDecoration(
          border: last
              ? null
              : const Border(bottom: BorderSide(color: Color(0xFFE3DDCE))),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 118,
              child: Text(label,
                  style:
                      const TextStyle(color: Color(0xFF6B6F78), fontSize: 13.5)),
            ),
            Expanded(
              child: Text(
                value.isEmpty ? '-' : value,
                textAlign: TextAlign.right,
                style: const TextStyle(
                    color: AppColors.ink,
                    fontSize: 13.5,
                    fontWeight: FontWeight.w800),
              ),
            ),
          ],
        ),
      );
}

class ReceiptWebViewScreen extends StatefulWidget {
  const ReceiptWebViewScreen({
    super.key,
    required this.title,
    required this.url,
  });

  final String title;
  final String url;

  @override
  State<ReceiptWebViewScreen> createState() => _ReceiptWebViewScreenState();
}

class _ReceiptWebViewScreenState extends State<ReceiptWebViewScreen> {
  late final WebViewController _controller;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(NavigationDelegate(
        onPageFinished: (_) {
          if (mounted) setState(() => _loading = false);
        },
      ))
      ..loadRequest(Uri.parse(widget.url));
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(widget.title)),
        body: Stack(
          children: [
            WebViewWidget(controller: _controller),
            if (_loading) const Center(child: CircularProgressIndicator()),
          ],
        ),
      );
}
