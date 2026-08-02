import 'dart:convert';

enum BannerPlacement {
  homeBottom('home_bottom'),
  eventPage('event_page');

  const BannerPlacement(this.apiValue);
  final String apiValue;
}

class BannerTransportResponse {
  const BannerTransportResponse(this.statusCode, this.body);
  final int statusCode;
  final String body;
}

typedef BannerTransport = Future<BannerTransportResponse> Function(
  String method,
  String path, {
  Map<String, dynamic>? body,
  required BannerAuthentication authentication,
});

/// Optional authentication attaches a verified user's token when one exists.
/// A transport must never retry anonymously after presented credentials fail.
enum BannerAuthentication { optional, required, none }

class BannerApiException implements Exception {
  const BannerApiException(this.statusCode, this.message);
  final int statusCode;
  final String message;

  @override
  String toString() => message;
}

class BannerReward {
  const BannerReward({
    required this.type,
    required this.amount,
    required this.available,
    required this.label,
  });

  final String type;
  final int? amount;
  final bool available;
  final String label;

  factory BannerReward.fromJson(Map<String, dynamic> json) => BannerReward(
        type: '${json['type'] ?? ''}',
        amount: (json['amount'] as num?)?.round(),
        available: json['available'] == true,
        label: '${json['label'] ?? ''}',
      );
}

class PartnerBanner {
  const PartnerBanner({
    required this.id,
    required this.imageUrl,
    required this.imageAlt,
    required this.openMode,
    required this.partnerName,
    required this.reward,
  });

  final String id;
  final String imageUrl;
  final String imageAlt;
  final String openMode;
  final String partnerName;
  final BannerReward reward;

  factory PartnerBanner.fromJson(Map<String, dynamic> json) => PartnerBanner(
        id: '${json['id'] ?? ''}',
        imageUrl: '${json['image_url'] ?? ''}',
        imageAlt: '${json['image_alt'] ?? ''}',
        openMode: '${json['open_mode'] ?? ''}',
        partnerName: '${json['partner_name'] ?? ''}',
        reward: BannerReward.fromJson(
          (json['reward'] as Map?)?.cast<String, dynamic>() ?? const {},
        ),
      );
}

class BannerClickResult {
  const BannerClickResult({
    required this.linkUrl,
    required this.rewardGranted,
    required this.rewardType,
    required this.amount,
    required this.balanceAfter,
    required this.userCouponId,
    required this.reason,
  });

  final String? linkUrl;
  final bool rewardGranted;
  final String? rewardType;
  final int? amount;
  final int? balanceAfter;
  final String? userCouponId;
  final String? reason;

  factory BannerClickResult.fromJson(Map<String, dynamic> json) =>
      BannerClickResult(
        linkUrl: json['link_url']?.toString(),
        rewardGranted: json['reward_granted'] == true,
        rewardType: json['reward_type']?.toString(),
        amount: (json['amount'] as num?)?.round(),
        balanceAfter: (json['balance_after'] as num?)?.round(),
        userCouponId: json['user_coupon_id']?.toString(),
        reason: json['reason']?.toString(),
      );
}

class BannerImpression {
  const BannerImpression({required this.bannerId, required this.placement});

  final String bannerId;
  final BannerPlacement placement;

  Map<String, dynamic> toJson() => {
        'banner_id': bannerId,
        'placement': placement.apiValue,
      };
}

class BannerApi {
  const BannerApi(this.transport);
  final BannerTransport transport;

  Future<List<PartnerBanner>> getBanners(BannerPlacement placement) async {
    final response = await transport(
      'GET',
      '/banners?placement=${placement.apiValue}',
      authentication: BannerAuthentication.optional,
    );
    final decoded = _decodeData(response);
    final rawItems = decoded['items'];
    if (rawItems is! List) {
      return const [];
    }
    return rawItems
        .whereType<Map>()
        .map((item) => PartnerBanner.fromJson(item.cast<String, dynamic>()))
        .where((banner) => banner.id.isNotEmpty && banner.imageUrl.isNotEmpty)
        .toList(growable: false);
  }

  Future<BannerClickResult> click(String id) async {
    final response = await transport(
      'POST',
      '/banners/$id/click',
      authentication: BannerAuthentication.optional,
    );
    return BannerClickResult.fromJson(_decodeData(response));
  }

  Future<void> impressions(List<BannerImpression> items) async {
    for (var start = 0; start < items.length; start += 50) {
      final end = (start + 50).clamp(0, items.length);
      final response = await transport(
        'POST',
        '/banners/impressions',
        authentication: BannerAuthentication.optional,
        body: {
          'items':
              items.sublist(start, end).map((item) => item.toJson()).toList(),
        },
      );
      // Impressions intentionally return an empty HTTP 204. Other banner
      // endpoints use the JSON success envelope and still pass through the
      // strict decoder below.
      if (response.statusCode != 204) {
        _decodeData(response);
      }
    }
  }

  Map<String, dynamic> _decodeData(BannerTransportResponse response) {
    Map<String, dynamic> decoded = const {};
    try {
      final value = response.body.isEmpty
          ? <String, dynamic>{}
          : jsonDecode(response.body);
      if (value is Map) {
        decoded = value.cast<String, dynamic>();
      }
    } catch (_) {
      throw BannerApiException(response.statusCode, '서버 응답을 확인할 수 없어요.');
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = decoded['detail'];
      final message = detail is Map ? detail['message'] : detail;
      throw BannerApiException(
        response.statusCode,
        '${message ?? '네트워크 오류가 발생했어요.'}',
      );
    }
    if (decoded['ok'] != true || decoded['error'] != null) {
      throw BannerApiException(
        response.statusCode,
        '서버 응답을 확인할 수 없어요.',
      );
    }
    final data = decoded['data'];
    if (data is! Map) {
      throw BannerApiException(
        response.statusCode,
        '서버 응답을 확인할 수 없어요.',
      );
    }
    return data.cast<String, dynamic>();
  }
}
