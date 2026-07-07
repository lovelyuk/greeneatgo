import 'package:flutter/material.dart';

void main() => runApp(const greeneatGoApp());

class greeneatGoApp extends StatelessWidget {
  const greeneatGoApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '밥장부',
      theme: ThemeData(colorSchemeSeed: const Color(0xFF2F80ED), useMaterial3: true),
      home: const HomeScreen(),
    );
  }
}

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('밥장부')),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const _BalanceCard(),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const PaymentCompletePreview())),
            icon: const Icon(Icons.qr_code_scanner),
            label: const Text('QR 결제'),
          ),
          const SizedBox(height: 24),
          const Text('최근 내역', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
          const ListTile(title: Text('밥장부 김치찌개'), subtitle: Text('중식 · 12:21'), trailing: Text('-9,000원')),
        ]),
      ),
    );
  }
}

class _BalanceCard extends StatelessWidget {
  const _BalanceCard();

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: const [
          Text('남은 식대', style: TextStyle(fontSize: 16)),
          SizedBox(height: 8),
          Text('191,000원', style: TextStyle(fontSize: 34, fontWeight: FontWeight.w800)),
          SizedBox(height: 8),
          Text('중식 진행중 · 1식 한도 10,000원'),
        ]),
      ),
    );
  }
}

class PaymentCompletePreview extends StatelessWidget {
  const PaymentCompletePreview({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0E7A4F),
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: const [
              Icon(Icons.check_circle, color: Colors.white, size: 96),
              SizedBox(height: 24),
              Text('결제완료', style: TextStyle(color: Colors.white, fontSize: 38, fontWeight: FontWeight.bold)),
              SizedBox(height: 16),
              Text('밥장부 김치찌개', style: TextStyle(color: Colors.white, fontSize: 24)),
              SizedBox(height: 8),
              Text('9,000원', style: TextStyle(color: Colors.white, fontSize: 52, fontWeight: FontWeight.w900)),
              SizedBox(height: 16),
              Text('거래번호 123456 · 서버시각 표시 예정', style: TextStyle(color: Colors.white70, fontSize: 16)),
            ]),
          ),
        ),
      ),
    );
  }
}
