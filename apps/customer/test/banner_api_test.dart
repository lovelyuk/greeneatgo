import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/data/banner_api.dart';

Map<String, dynamic> envelope(Map<String, dynamic> data) => {
      'ok': true,
      'data': data,
      'error': null,
    };

void main() {
  test('GET unwraps the exact FastAPI envelope once with optional auth',
      () async {
    late String method;
    late String path;
    late BannerAuthentication sentAuthentication;
    final api = BannerApi((m, p, {body, required authentication}) async {
      method = m;
      path = p;
      sentAuthentication = authentication;
      return BannerTransportResponse(
        200,
        jsonEncode(envelope({
          'items': [
            {
              'id': 'banner-1',
              'image_url': 'https://cdn.example/banner.webp',
              'image_alt': '여름 할인 배너',
              'open_mode': 'external',
              'partner_name': '파트너사',
              'reward': {
                'type': 'point',
                'amount': 300,
                'available': true,
                'label': '300P 받기',
              },
            },
          ],
        })),
      );
    });

    final banners = await api.getBanners(BannerPlacement.homeBottom);

    expect(method, 'GET');
    expect(path, '/banners?placement=home_bottom');
    expect(sentAuthentication, BannerAuthentication.optional);
    expect(banners, hasLength(1));
    expect(banners.single.id, 'banner-1');
    expect(banners.single.imageUrl, 'https://cdn.example/banner.webp');
    expect(banners.single.reward.amount, 300);
  });

  test('click unwraps exact flat data without a second alias layer', () async {
    final api =
        BannerApi((method, path, {body, required authentication}) async {
      expect(method, 'POST');
      expect(path, '/banners/banner-1/click');
      expect(authentication, BannerAuthentication.optional);
      return BannerTransportResponse(
        200,
        jsonEncode(envelope({
          'link_url': 'https://partner.example/event',
          'reward_granted': true,
          'reward_type': 'coupon',
          'amount': 1,
          'balance_after': 1700,
          'user_coupon_id': 'user-coupon-7',
          'reason': 'GRANTED',
        })),
      );
    });

    final click = await api.click('banner-1');
    expect(click.linkUrl, 'https://partner.example/event');
    expect(click.rewardGranted, isTrue);
    expect(click.rewardType, 'coupon');
    expect(click.amount, 1);
    expect(click.balanceAfter, 1700);
    expect(click.userCouponId, 'user-coupon-7');
    expect(click.reason, 'GRANTED');
  });

  test('impression request accepts the exact empty FastAPI 204 response',
      () async {
    Map<String, dynamic>? sentBody;
    final api =
        BannerApi((method, path, {body, required authentication}) async {
      expect(method, 'POST');
      expect(path, '/banners/impressions');
      expect(authentication, BannerAuthentication.optional);
      sentBody = body;
      return const BannerTransportResponse(204, '');
    });

    await api.impressions(const [
      BannerImpression(
        bannerId: 'banner-final',
        placement: BannerPlacement.eventPage,
      ),
    ]);

    expect(sentBody, {
      'items': [
        {'banner_id': 'banner-final', 'placement': 'event_page'},
      ],
    });
  });

  test('FastAPI detail object supplies exact error text', () async {
    final api = BannerApi((method, path,
            {body, required authentication}) async =>
        BannerTransportResponse(
          410,
          jsonEncode({
            'detail': {
              'code': 'BANNER_NOT_AVAILABLE',
              'message': '이 배너는 더 이상 이용할 수 없어요',
            },
          }),
        ));

    await expectLater(
      api.click('gone'),
      throwsA(isA<BannerApiException>()
          .having((error) => error.statusCode, 'status', 410)
          .having((error) => error.message, 'message', '이 배너는 더 이상 이용할 수 없어요')),
    );
  });

  test('legacy root payload is rejected rather than double-guessed', () async {
    final api = BannerApi((method, path,
            {body, required authentication}) async =>
        const BannerTransportResponse(200, '{"items":[]}'));

    await expectLater(
      api.getBanners(BannerPlacement.eventPage),
      throwsA(isA<BannerApiException>()),
    );
  });
}
