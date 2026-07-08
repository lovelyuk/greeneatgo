import 'package:flutter_test/flutter_test.dart';

import 'package:greeneatgo_customer/main.dart';

void main() {
  testWidgets('app shows missing environment guidance when not configured', (WidgetTester tester) async {
    await tester.pumpWidget(const GreeneatGoApp());
    await tester.pump();

    expect(find.text('잠깐, 문제가 생겼어요'), findsOneWidget);
    expect(find.textContaining('앱 환경값이 누락됐어요'), findsOneWidget);
  });
}
