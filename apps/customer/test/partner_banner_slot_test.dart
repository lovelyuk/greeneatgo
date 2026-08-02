import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/data/banner_api.dart';
import 'package:greeneatgo_customer/widgets/ad_badge.dart';
import 'package:greeneatgo_customer/widgets/partner_banner_slot.dart';

Map<String, dynamic> bannerJson(
  String id, {
  String openMode = 'in_app',
  String alt = '파트너 이벤트',
  bool rewardAvailable = true,
}) =>
    {
      'id': id,
      'image_url': 'https://cdn.example/$id.webp',
      'image_alt': alt,
      'open_mode': openMode,
      'partner_name': '파트너 $id',
      'reward': {
        'type': 'coupon',
        'amount': 1,
        'available': rewardAvailable,
        'label': '쿠폰 받기',
      },
    };

class BannerBackend {
  BannerBackend(this.items, {this.clickResponse});

  final List<Map<String, dynamic>> items;
  final BannerTransportResponse? clickResponse;
  int clickCount = 0;
  final List<Map<String, dynamic>> impressionBodies = [];

  Future<BannerTransportResponse> call(
    String method,
    String path, {
    Map<String, dynamic>? body,
    required BannerAuthentication authentication,
  }) async {
    if (method == 'GET') {
      return BannerTransportResponse(
          200,
          jsonEncode({
            'ok': true,
            'data': {'items': items},
            'error': null,
          }));
    }
    if (path.endsWith('/click')) {
      clickCount++;
      if (clickResponse != null) return clickResponse!;
      return BannerTransportResponse(
        200,
        jsonEncode({
          'ok': true,
          'data': {
            'link_url': null,
            'reward_granted': false,
            'reward_type': null,
            'amount': null,
            'balance_after': null,
            'user_coupon_id': null,
            'reason': 'NOT_AVAILABLE',
          },
          'error': null,
        }),
      );
    }
    impressionBodies.add(body!);
    return BannerTransportResponse(
        200,
        jsonEncode({
          'ok': true,
          'data': {'accepted': 1},
          'error': null,
        }));
  }
}

Widget testImage(
  BuildContext context,
  PartnerBanner banner,
  VoidCallback onError,
) =>
    ColoredBox(
      key: ValueKey('image-${banner.id}'),
      color: Colors.green,
    );

Future<void> pumpSlot(
  WidgetTester tester,
  BannerBackend backend, {
  PartnerBannerImageBuilder? imageBuilder,
  Size size = const Size(800, 600),
  double textScale = 1,
  VoidCallback? onCouponIssued,
}) async {
  await tester.binding.setSurfaceSize(size);
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(
    MediaQuery(
      data: MediaQueryData(textScaler: TextScaler.linear(textScale)),
      child: MaterialApp(
        home: Scaffold(
          body: PartnerBannerSlot(
            api: BannerApi(backend.call),
            placement: BannerPlacement.homeBottom,
            imageBuilder: imageBuilder ?? testImage,
            onCouponIssued: onCouponIssued,
          ),
        ),
      ),
    ),
  );
  await tester.pump();
}

void main() {
  testWidgets('empty response occupies no space', (tester) async {
    final backend = BannerBackend([]);
    await pumpSlot(tester, backend);

    expect(find.byType(PageView), findsNothing);
    expect(tester.getSize(find.byType(PartnerBannerSlot)), Size.zero);
  });

  testWidgets('one banner is static, labeled 광고, and has semantics',
      (tester) async {
    final semantics = tester.ensureSemantics();
    final backend = BannerBackend([
      bannerJson('one', alt: '여름 한정 행사'),
    ]);
    await pumpSlot(tester, backend);

    expect(find.byType(PageView), findsNothing);
    expect(find.byType(AdBadge), findsOneWidget);
    expect(find.text('광고'), findsOneWidget);
    expect(
      find.bySemanticsLabel('광고, 여름 한정 행사, 파트너 one, 쿠폰 받기'),
      findsOneWidget,
    );
    semantics.dispose();
  });

  testWidgets('multiple banners use PageView and dots; every page shows 광고',
      (tester) async {
    final backend = BannerBackend([
      bannerJson('one'),
      bannerJson('two'),
      bannerJson('three'),
    ]);
    await pumpSlot(tester, backend);

    expect(find.byKey(const Key('partner-banner-page-view')), findsOneWidget);
    expect(find.byType(AnimatedContainer), findsNWidgets(3));
    for (var index = 0; index < 3; index++) {
      expect(find.text('광고'), findsWidgets);
      expect(find.byType(AdBadge), findsWidgets);
      if (index < 2) {
        await tester.drag(
          find.byKey(const Key('partner-banner-page-view')),
          const Offset(-700, 0),
        );
        await tester.pumpAndSettle();
      }
    }
  });

  testWidgets('five rapid taps issue one click and lock lasts 1.5 seconds',
      (tester) async {
    final backend = BannerBackend([bannerJson('one')]);
    await pumpSlot(tester, backend);
    final target = find.byKey(const ValueKey('partner-banner-one'));

    for (var index = 0; index < 5; index++) {
      await tester.tap(target);
    }
    await tester.pump();
    expect(backend.clickCount, 1);

    await tester.pump(const Duration(milliseconds: 1499));
    await tester.tap(target);
    await tester.pump();
    expect(backend.clickCount, 1);

    await tester.pump(const Duration(milliseconds: 2));
    await tester.tap(target);
    await tester.pump();
    expect(backend.clickCount, 2);
    await tester.pump(const Duration(milliseconds: 1500));
  });

  testWidgets('an image failure removes exactly that banner', (tester) async {
    final backend = BannerBackend([
      bannerJson('bad'),
      bannerJson('good'),
    ]);
    final failed = <String>{};
    await pumpSlot(
      tester,
      backend,
      imageBuilder: (context, banner, onError) {
        if (banner.id == 'bad' && failed.add(banner.id)) {
          onError();
        }
        return testImage(context, banner, onError);
      },
    );
    await tester.pump();

    expect(find.byKey(const ValueKey('partner-banner-bad')), findsNothing);
    expect(find.byKey(const ValueKey('partner-banner-good')), findsOneWidget);
    expect(find.byType(PageView), findsNothing);
    expect(find.byType(AdBadge), findsOneWidget);
  });

  testWidgets('360x640 with text scale 1.3 has no overflow', (tester) async {
    final backend = BannerBackend([
      bannerJson('small', alt: '매우 긴 접근성 배너 설명'),
      bannerJson('second'),
    ]);
    await pumpSlot(
      tester,
      backend,
      size: const Size(360, 640),
      textScale: 1.3,
    );

    expect(find.text('광고'), findsWidgets);
    expect(tester.takeException(), isNull);
  });
}
