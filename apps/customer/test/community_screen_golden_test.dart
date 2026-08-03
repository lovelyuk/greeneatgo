import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/main.dart';
import 'package:greeneatgo_customer/theme/app_colors.dart';
import 'package:greeneatgo_customer/theme/app_theme.dart';

void main() {
  setUpAll(() async {
    final loader = FontLoader('Pretendard')
      ..addFont(rootBundle.load('assets/fonts/Pretendard-Regular.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-SemiBold.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-Bold.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-ExtraBold.otf'));
    await loader.load();
    final icons = FontLoader('MaterialIcons')
      ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await icons.load();
  });

  testWidgets('community announcement uses dark dashboard language at 360px',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(MaterialApp(
      debugShowCheckedModeBanner: false,
      home: RepaintBoundary(
        key: const Key('community-announcement-capture'),
        child: CommunityContent(
          reviews: false,
          loading: false,
          data: const {
            'items': [
              {
                'title': '휴무 및 영업시간 안내',
                'content': '매장 운영 일정이 변경될 수 있으니 방문 전 확인해 주세요.',
                'pinned': true,
                'created_at': '2026-08-01T07:52:06.960477+00:00',
              }
            ],
          },
          reviewable: const [],
          onTabChanged: (_) {},
          onRefresh: () async {},
          onWrite: (_) {},
        ),
      ),
    ));
    await tester.pumpAndSettle();

    expect(find.text('커뮤니티'), findsOneWidget);
    expect(find.text('공지사항'), findsNWidgets(2));
    expect(find.text('리뷰'), findsOneWidget);
    expect(find.text('휴무 및 영업시간 안내'), findsOneWidget);
    expect(find.textContaining('2026-08-01T'), findsNothing);
    expect(find.byIcon(Icons.push_pin_rounded), findsOneWidget);
    expect(tester.takeException(), isNull);
    await expectLater(
      find.byKey(const Key('community-announcement-capture')),
      matchesGoldenFile('goldens/community_announcement_360.png'),
    );
  });

  testWidgets('community tabs expose announcement and review empty states',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      const MaterialApp(home: _CommunityHarness()),
    );
    await tester.pumpAndSettle();

    expect(find.text('등록된 공지사항이 아직 없어요.'), findsOneWidget);
    await tester.tap(find.text('리뷰'));
    await tester.pumpAndSettle();
    expect(find.text('아직 등록된 리뷰가 없어요.'), findsOneWidget);
    expect(find.text('0 (0개 후기)'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('review cards use icon stars, formatted dates and image fallback',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(MaterialApp(
      home: CommunityContent(
        reviews: true,
        loading: false,
        data: const {
          'average_rating': 4.0,
          'review_count': 1,
          'items': [
            {
              'author_name': '이용자',
              'rating': 4,
              'content': '맛있게 잘 먹었습니다.',
              'image_urls': ['https://invalid.invalid/review.webp'],
              'owner_reply': '소중한 후기 감사합니다.',
              'created_at': '2026-08-01T07:52:06.960477+00:00',
            }
          ],
        },
        reviewable: const [],
        onTabChanged: (_) {},
        onRefresh: () async {},
        onWrite: (_) {},
      ),
    ));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    expect(find.text('4.0 (1개 후기)'), findsOneWidget);
    expect(find.textContaining('⭐'), findsNothing);
    expect(find.byIcon(Icons.star_rounded), findsNWidgets(5));
    expect(find.byIcon(Icons.star_border_rounded), findsOneWidget);
    expect(find.textContaining('2026-08-01T'), findsNothing);
    expect(find.textContaining('사장님 답글:'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('community buttons use scoped blue theme without changing global',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(MaterialApp(
      home: RepaintBoundary(
        key: const Key('community-reviewable-capture'),
        child: CommunityContent(
          reviews: true,
          loading: false,
          data: const {
            'average_rating': 0,
            'review_count': 0,
            'items': [],
          },
          reviewable: const [
            {
              'id': 1,
              'created_at': '2026-08-01T07:52:06.960477+00:00',
              'amount': -8000,
            }
          ],
          onTabChanged: (_) {},
          onRefresh: () async {},
          onWrite: (_) {},
        ),
      ),
    ));
    await tester.pumpAndSettle();

    final reviewButton = find.widgetWithText(FilledButton, '리뷰 쓰기');
    final communityTheme = Theme.of(tester.element(reviewButton));
    final filledStyle = communityTheme.filledButtonTheme.style!;
    expect(filledStyle.backgroundColor!.resolve({}), AppColors.blue);
    expect(filledStyle.foregroundColor!.resolve({}), AppColors.fg);
    expect(
      filledStyle.backgroundColor!.resolve({WidgetState.disabled}),
      AppColors.cardHi,
    );
    expect(
      filledStyle.foregroundColor!.resolve({WidgetState.disabled}),
      AppColors.fg2,
    );
    final filledShape =
        filledStyle.shape!.resolve({})! as RoundedRectangleBorder;
    expect(filledShape.borderRadius, BorderRadius.circular(AppRadii.button));

    final outlinedStyle = communityTheme.outlinedButtonTheme.style!;
    expect(outlinedStyle.foregroundColor!.resolve({}), AppColors.blueSoft);
    expect(outlinedStyle.side!.resolve({})!.color, AppColors.line);
    expect(tester.takeException(), isNull);
    await expectLater(
      find.byKey(const Key('community-reviewable-capture')),
      matchesGoldenFile('goldens/community_reviewable_360.png'),
    );

    await tester.pumpWidget(const GreeneatGoApp());
    await tester.pump();
    final app = tester.widget<MaterialApp>(find.byType(MaterialApp));
    expect(
      app.theme!.filledButtonTheme.style!.backgroundColor!.resolve({}),
      kOrange,
    );
  });
}

class _CommunityHarness extends StatefulWidget {
  const _CommunityHarness();

  @override
  State<_CommunityHarness> createState() => _CommunityHarnessState();
}

class _CommunityHarnessState extends State<_CommunityHarness> {
  bool reviews = false;

  @override
  Widget build(BuildContext context) => CommunityContent(
        reviews: reviews,
        loading: false,
        data: const {'items': []},
        reviewable: const [],
        onTabChanged: (index) => setState(() => reviews = index == 1),
        onRefresh: () async {},
        onWrite: (_) {},
      );
}
