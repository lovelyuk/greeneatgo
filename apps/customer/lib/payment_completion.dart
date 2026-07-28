import 'package:flutter/material.dart';
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
      issuerName: text(payment, 'issuer_name'),
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
    final green = Theme.of(context).colorScheme.primary;
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        automaticallyImplyLeading: false,
        backgroundColor: Colors.white,
        centerTitle: true,
        title: const Text(
          '결제 완료',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
        ),
      ),
      body: SafeArea(
        bottom: false,
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(24, 24, 24, 28),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Center(
                child: Container(
                  width: 72,
                  height: 72,
                  decoration:
                      BoxDecoration(color: green, shape: BoxShape.circle),
                  child: const Icon(Icons.check_rounded,
                      color: Colors.white, size: 46),
                ),
              ),
              const SizedBox(height: 20),
              const Text(
                '결제가 완료되었습니다',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 24, fontWeight: FontWeight.w900),
              ),
              const SizedBox(height: 8),
              const Text(
                '이용해 주셔서 감사합니다.',
                textAlign: TextAlign.center,
                style: TextStyle(color: Color(0xFF8A8A8A), fontSize: 15),
              ),
              const SizedBox(height: 36),
              const Text('결제 금액',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Color(0xFF777777), fontSize: 14)),
              const SizedBox(height: 8),
              Text(
                formatPaymentAmount(payment.amount),
                textAlign: TextAlign.center,
                style:
                    const TextStyle(fontSize: 34, fontWeight: FontWeight.w900),
              ),
              const SizedBox(height: 32),
              const Divider(color: Color(0xFFE5E5E5)),
              const SizedBox(height: 18),
              _DetailRow(label: '결제수단', value: payment.displayedMethod),
              _DetailRow(
                  label: payment.accountLabel, value: payment.accountValue),
              _DetailRow(label: '승인번호', value: payment.authorizationNumber),
              _DetailRow(
                  label: '거래일시',
                  value: formatPaymentDateTime(payment.approvedAt)),
              _DetailRow(label: '거래번호(TRXID)', value: payment.transactionId),
              if (payment.showSalesSlip || payment.showCashReceipt) ...[
                const SizedBox(height: 12),
                if (payment.showSalesSlip)
                  OutlinedButton(
                    onPressed: () => _openReceipt(
                      context,
                      payment.isCard ? '카드 매출전표' : '계좌이체 전표',
                      payment.salesSlipUrl,
                    ),
                    child: Text(payment.isCard ? '카드 매출전표 보기' : '계좌이체 전표 보기'),
                  ),
                if (payment.showCashReceipt) ...[
                  const SizedBox(height: 10),
                  OutlinedButton(
                    onPressed: () =>
                        _openReceipt(context, '현금영수증', payment.cashReceiptUrl),
                    child: const Text('현금영수증 보기'),
                  ),
                ],
              ],
            ],
          ),
        ),
      ),
      bottomNavigationBar: SafeArea(
        minimum: const EdgeInsets.fromLTRB(24, 10, 24, 16),
        child: FilledButton(
          onPressed: onDone ?? () => Navigator.of(context).pop(true),
          child: const Text('확인'),
        ),
      ),
    );
  }
}

class _DetailRow extends StatelessWidget {
  const _DetailRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 9),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 128,
              child: Text(label,
                  style:
                      const TextStyle(color: Color(0xFF777777), fontSize: 14)),
            ),
            Expanded(
              child: Text(
                value.isEmpty ? '-' : value,
                textAlign: TextAlign.right,
                style:
                    const TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
              ),
            ),
          ],
        ),
      );
}

/// Minimal reusable in-app browser for payment receipts.
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
