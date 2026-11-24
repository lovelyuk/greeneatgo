import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/company_meal.dart';

// 2026-11-18 is a Wednesday, 2026-11-21 a Saturday. Times are KST.
DateTime kst(int hour, int minute, {int day = 18, int second = 0}) =>
    DateTime.utc(2026, 11, day, hour, minute, second).subtract(const Duration(hours: 9));

Map<String, dynamic> me({List<Map<String, String>>? windows, bool weekendAllowed = true, Map<String, String>? limit}) => {
      'company_meal': {
        'available': true,
        'limit_block': limit,
        'windows': windows ??
            [
              {'name': '중식', 'start': '11:30', 'end': '13:30'},
              {'name': '석식', 'start': '18:00', 'end': '19:30'},
            ],
        'weekend_allowed': weekendAllowed,
      },
    };

void main() {
  test('meal hours are judged on the clock, with the same edges as the server', () {
    final status = CompanyMealStatus.fromMe(me())!;
    final lunch = status.at(kst(12, 0));
    expect((lunch.available, lunch.title, lunch.detail), (true, '회사 식대 사용 가능', '지금 중식 시간이에요 · 11:30~13:30'));
    expect(status.at(kst(11, 30)).available, isTrue);
    expect(status.at(kst(13, 30)).available, isTrue);
    expect(status.at(kst(13, 30, second: 1)).available, isFalse);
    expect(status.at(kst(11, 29, second: 59)).available, isFalse);
    final off = status.at(kst(15, 0));
    expect((off.available, off.title, off.detail),
        (false, '지금은 회사 식대를 쓸 수 없어요', '사용 시간 · 중식\u00A011:30~13:30 · 석식\u00A018:00~19:30'));
    expect(status.at(kst(18, 30)).detail, '지금 석식 시간이에요 · 18:00~19:30');
  });

  test('no hours set means any time; weekend rule and limits give their own reason', () {
    final open = CompanyMealStatus.fromMe(me(windows: []))!.at(kst(3, 0));
    expect((open.available, open.detail), (true, '언제든 사용할 수 있어요'));
    final weekend = CompanyMealStatus.fromMe(me(weekendAllowed: false))!;
    expect(weekend.at(kst(12, 0, day: 21)).detail, '주말에는 사용할 수 없어요');
    expect(weekend.at(kst(12, 0)).available, isTrue);
    expect(CompanyMealStatus.fromMe(me())!.at(kst(12, 0, day: 21)).available, isTrue);
    // A used-up limit wins over the time of day.
    final limited = CompanyMealStatus.fromMe(
        me(limit: {'code': 'MONTHLY_LIMIT', 'message': '이번 달 한도 200,000원을 모두 썼어요'}))!.at(kst(12, 0));
    expect((limited.available, limited.detail), (false, '이번 달 한도 200,000원을 모두 썼어요'));
  });

  test('missing or malformed data is ignored instead of guessed', () {
    expect(CompanyMealStatus.fromMe(const {}), isNull);
    expect(CompanyMealStatus.fromMe({'company_meal': null}), isNull);
    final odd = CompanyMealStatus.fromMe(me(windows: [
      {'name': '중식', 'start': '99:99', 'end': '13:30'},
      {'name': '석식', 'start': '18:00', 'end': '19:30'},
    ]))!;
    expect(odd.windows.length, 1);
    expect(odd.at(kst(12, 0)).available, isFalse);
    // A window that passes midnight.
    final night = CompanyMealStatus.fromMe(me(windows: [{'name': '야식', 'start': '22:00', 'end': '02:00'}]))!;
    expect(night.at(kst(23, 0)).available, isTrue);
    expect(night.at(kst(1, 0)).available, isTrue);
    expect(night.at(kst(12, 0)).available, isFalse);
  });

  Future<List<String>> pump(WidgetTester tester, {required Map<String, dynamic> data, required DateTime now, int personal = 0}) async {
    final taps = <String>[];
    await tester.pumpWidget(MaterialApp(
      theme: ThemeData(
        filledButtonTheme: FilledButtonThemeData(style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(54))),
      ),
      home: Scaffold(
        body: SingleChildScrollView(
          child: LedgerMealCard(
            status: CompanyMealStatus.fromMe(data),
            personalBalance: personal,
            couponCountLabel: '1',
            pointBalanceLabel: '500P',
            monthUsage: '16,000원',
            onTapQr: () => taps.add('qr'),
            onBuyTicket: () => taps.add('buy'),
            now: () => now,
          ),
        ),
      ),
    ));
    return taps;
  }

  testWidgets('company tab is the default: status, no voucher count, no buy button', (tester) async {
    final taps = await pump(tester, data: me(), now: kst(12, 0));
    expect(find.byKey(const ValueKey('company-meal-available')), findsOneWidget);
    expect(find.text('회사 식대 사용 가능'), findsOneWidget);
    expect(find.text('지금 중식 시간이에요 · 11:30~13:30'), findsOneWidget);
    expect(find.byKey(const ValueKey('buy-ticket-button')), findsNothing);
    expect(find.byKey(const ValueKey('ticket-balance-unit')), findsNothing);
    expect(find.byKey(const ValueKey('ticket-balance-digit-0')), findsNothing);
    expect(find.text('회사 식대'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('use-ticket-qr-button')));
    expect(taps, ['qr']);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('outside the hours it says so, and points to personal vouchers when there are some', (tester) async {
    await pump(tester, data: me(), now: kst(15, 0), personal: 2);
    expect(find.byKey(const ValueKey('company-meal-blocked')), findsOneWidget);
    expect(find.text('지금은 회사 식대를 쓸 수 없어요'), findsOneWidget);
    expect(find.text('사용 시간 · 중식\u00A011:30~13:30 · 석식\u00A018:00~19:30'), findsOneWidget);
    expect(find.text('내 식권 2장으로는 결제할 수 있어요'), findsOneWidget);
    await pump(tester, data: me(), now: kst(15, 0));
    expect(find.textContaining('내 식권'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('personal tab is the ordinary voucher card with the buy button', (tester) async {
    final taps = await pump(tester, data: me(), now: kst(12, 0), personal: 3);
    await tester.tap(find.byKey(const ValueKey('meal-tab-personal')));
    await tester.pump();
    expect(find.byKey(const ValueKey('company-meal-available')), findsNothing);
    expect(find.byKey(const ValueKey('ticket-balance-unit')), findsOneWidget);
    expect(find.text('남은 식권'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('buy-ticket-button')));
    expect(taps, ['buy']);
    await tester.tap(find.byKey(const ValueKey('meal-tab-company')));
    await tester.pump();
    expect(find.byKey(const ValueKey('company-meal-available')), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('without a status from the server the card makes no claim', (tester) async {
    await pump(tester, data: const {}, now: kst(12, 0));
    expect(find.byKey(const ValueKey('company-meal-unknown')), findsOneWidget);
    expect(find.text('회사 장부로 결제해요'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });
  testWidgets('the blocked title stays on one line on a 360dp phone', (tester) async {
    final pretendard = FontLoader('Pretendard')
      ..addFont(rootBundle.load('assets/fonts/Pretendard-Regular.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-SemiBold.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-Bold.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-ExtraBold.otf'));
    await pretendard.load();
    tester.view.physicalSize = const Size(360, 760);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: ThemeData(fontFamily: 'Pretendard'),
      home: Scaffold(
        backgroundColor: const Color(0xFF0B0F17),
        body: SingleChildScrollView(
          // Same side padding as the home page.
          padding: const EdgeInsets.fromLTRB(18, 8, 18, 0),
          child: RepaintBoundary(
            key: const ValueKey('blocked-card'),
            child: LedgerMealCard(
              status: CompanyMealStatus.fromMe(me()),
              personalBalance: 2,
              couponCountLabel: '1',
              pointBalanceLabel: '500P',
              monthUsage: '16,000원',
              onTapQr: () {},
              onBuyTicket: () {},
              now: () => kst(15, 0),
            ),
          ),
        ),
      ),
    ));
    final title = find.byKey(const ValueKey('company-meal-title'));
    expect(tester.widget<Text>(title).data, '지금은 회사 식대를 쓸 수 없어요');
    final paragraph = tester.renderObject<RenderParagraph>(
        find.descendant(of: title, matching: find.byType(RichText)));
    int lines(double fontSize) {
      final painter = TextPainter(
        text: TextSpan(
            text: '지금은 회사 식대를 쓸 수 없어요',
            style: paragraph.text.style!.copyWith(fontSize: fontSize)),
        textDirection: TextDirection.ltr,
      )..layout(maxWidth: paragraph.constraints.maxWidth);
      final count = painter.computeLineMetrics().length;
      painter.dispose();
      return count;
    }

    expect(paragraph.text.style!.fontSize, 15);
    expect(lines(15), 1);
    // The old size wrapped onto a second line.
    expect(lines(17), 2);
    await expectLater(find.byKey(const ValueKey('blocked-card')),
        matchesGoldenFile('goldens/company_meal_blocked_360.png'));
    await tester.pumpWidget(const SizedBox());
  });
}
