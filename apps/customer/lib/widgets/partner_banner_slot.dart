import 'dart:async';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../data/banner_api.dart';
import '../screens/partner_webview_screen.dart';
import '../theme/app_colors.dart';
import 'ad_badge.dart';

typedef PartnerBannerImageBuilder = Widget Function(
  BuildContext context,
  PartnerBanner banner,
  VoidCallback onError,
);

class BannerImpressionQueue {
  BannerImpressionQueue(
    this._send, {
    this.maxRetries = 2,
    this.retryDelay = const Duration(seconds: 1),
  });

  final Future<void> Function(List<BannerImpression>) _send;
  final int maxRetries;
  final Duration retryDelay;
  final List<_QueuedImpression> _pending = [];
  Future<void>? _worker;
  Timer? _retryTimer;

  void add(BannerImpression impression) {
    _pending.add(_QueuedImpression(impression));
    _schedule(const Duration(milliseconds: 250));
  }

  void _schedule(Duration delay) {
    _retryTimer?.cancel();
    _retryTimer = Timer(delay, () => unawaited(flush()));
  }

  Future<void> flush() {
    final running = _worker;
    if (running != null) return running;
    final completer = Completer<void>();
    _worker = completer.future;
    unawaited(() async {
      try {
        while (_pending.isNotEmpty) {
          final count = _pending.length.clamp(0, 50);
          final batch = _pending.sublist(0, count);
          _pending.removeRange(0, count);
          try {
            await _send(batch.map((entry) => entry.value).toList());
          } catch (_) {
            final retryable =
                batch.where((entry) => ++entry.attempts <= maxRetries).toList();
            _pending.insertAll(0, retryable);
            if (retryable.isNotEmpty) _schedule(retryDelay);
            break;
          }
        }
      } finally {
        _worker = null;
        completer.complete();
      }
    }());
    return completer.future;
  }

  Future<void> dispose() async {
    _retryTimer?.cancel();
    try {
      await flush();
    } catch (_) {
      // Best effort: reporting failures must never escape widget disposal.
    }
  }
}

class _QueuedImpression {
  _QueuedImpression(this.value);

  final BannerImpression value;
  int attempts = 0;
}

class PartnerBannerSlot extends StatefulWidget {
  const PartnerBannerSlot({
    super.key,
    required this.api,
    required this.placement,
    this.onCouponIssued,
    this.imageBuilder,
    this.padding = EdgeInsets.zero,
  });

  final BannerApi api;
  final BannerPlacement placement;
  final VoidCallback? onCouponIssued;
  final PartnerBannerImageBuilder? imageBuilder;
  final EdgeInsetsGeometry padding;

  @override
  State<PartnerBannerSlot> createState() => _PartnerBannerSlotState();
}

class _PartnerBannerSlotState extends State<PartnerBannerSlot>
    with WidgetsBindingObserver {
  final GlobalKey _visibilityKey = GlobalKey();
  final Set<String> _impressed = {};
  late final BannerImpressionQueue _impressionQueue;
  late final PageController _pageController;
  List<PartnerBanner>? _banners;
  int _page = 0;
  Timer? _autoTimer;
  Timer? _visibilityTimer;
  DateTime? _visibleSince;
  bool _clickLocked = false;
  bool _appActive = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _pageController = PageController();
    _impressionQueue = BannerImpressionQueue(widget.api.impressions);
    _load();
    _visibilityTimer = Timer.periodic(
        const Duration(milliseconds: 250), (_) => _checkVisibility());
  }

  Future<void> _load() async {
    try {
      final banners = await widget.api.getBanners(widget.placement);
      if (!mounted) return;
      setState(() {
        _banners = banners;
        _page = 0;
      });
      _scheduleAutoPlay();
      WidgetsBinding.instance.addPostFrameCallback((_) => _checkVisibility());
    } catch (_) {
      if (mounted) setState(() => _banners = const []);
    }
  }

  void _scheduleAutoPlay() {
    _autoTimer?.cancel();
    if ((_banners?.length ?? 0) < 2) return;
    _autoTimer = Timer.periodic(const Duration(seconds: 5), (_) {
      final banners = _banners;
      if (!mounted || banners == null || banners.length < 2) return;
      final next = (_page + 1) % banners.length;
      _pageController.animateToPage(next,
          duration: const Duration(milliseconds: 350), curve: Curves.easeOut);
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _appActive = state == AppLifecycleState.resumed;
    if (!_appActive) _visibleSince = null;
  }

  void _checkVisibility() {
    final banners = _banners;
    final context = _visibilityKey.currentContext;
    if (!_appActive ||
        !mounted ||
        banners == null ||
        banners.isEmpty ||
        context == null ||
        ModalRoute.of(this.context)?.isCurrent != true) {
      _visibleSince = null;
      return;
    }
    final render = context.findRenderObject();
    if (render is! RenderBox || !render.hasSize || render.size.height <= 0) {
      _visibleSince = null;
      return;
    }
    final topLeft = render.localToGlobal(Offset.zero);
    final rect = topLeft & render.size;
    final window = Offset.zero & MediaQuery.sizeOf(this.context);
    final overlap = rect.intersect(window);
    final ratio = overlap.isEmpty
        ? 0.0
        : overlap.width * overlap.height / (rect.width * rect.height);
    if (ratio < .5) {
      _visibleSince = null;
      return;
    }
    _visibleSince ??= DateTime.now();
    if (DateTime.now().difference(_visibleSince!) >=
        const Duration(seconds: 1)) {
      final id = banners[_page.clamp(0, banners.length - 1)].id;
      if (_impressed.add(id)) {
        _impressionQueue.add(BannerImpression(
          bannerId: id,
          placement: widget.placement,
        ));
      }
    }
  }

  void _removeFailed(String id) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || _banners == null) return;
      final next = _banners!.where((item) => item.id != id).toList();
      if (next.length == _banners!.length) return;
      setState(() {
        _banners = next;
        _page = next.isEmpty ? 0 : _page.clamp(0, next.length - 1);
        _visibleSince = null;
      });
      _scheduleAutoPlay();
    });
  }

  Future<void> _click(PartnerBanner banner) async {
    if (_clickLocked) return;
    _clickLocked = true;
    final minimumLock =
        Future<void>.delayed(const Duration(milliseconds: 1500));
    BannerClickResult result;
    try {
      result = await widget.api.click(banner.id);
    } on BannerApiException catch (error) {
      await minimumLock;
      _clickLocked = false;
      if (!mounted) return;
      if (error.statusCode == 410) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('종료된 광고예요. 새 광고를 불러올게요.')));
        await _load();
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('네트워크 연결을 확인한 뒤 다시 시도해 주세요.')));
      }
      return;
    } catch (_) {
      await minimumLock;
      _clickLocked = false;
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('네트워크 연결을 확인한 뒤 다시 시도해 주세요.')));
      }
      return;
    }

    // Both the request and minimum interval are fulfilled before unlocking.
    await minimumLock;
    _clickLocked = false;
    if (!mounted) return;

    if (result.rewardGranted) {
      final rewardMessage =
          result.rewardType == 'point' && result.amount != null
              ? '${result.amount}P가 지급됐어요.'
              : result.rewardType == 'coupon'
                  ? '쿠폰이 발급됐어요.'
                  : '리워드가 지급됐어요.';
      final couponIssued =
          result.rewardType == 'coupon' || result.userCouponId != null;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(rewardMessage),
        action: couponIssued && widget.onCouponIssued != null
            ? SnackBarAction(
                label: '쿠폰함',
                onPressed: widget.onCouponIssued!,
              )
            : null,
      ));
    }

    final uri = Uri.tryParse(result.linkUrl ?? '');
    if (uri == null ||
        uri.scheme.toLowerCase() != 'https' ||
        uri.host.isEmpty) {
      return;
    }
    try {
      if (banner.openMode == 'external') {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
      } else if (mounted) {
        await Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => PartnerWebviewScreen(
                url: uri, partnerName: banner.partnerName)));
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('네트워크 연결을 확인한 뒤 다시 시도해 주세요.')));
      }
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _autoTimer?.cancel();
    _visibilityTimer?.cancel();
    _pageController.dispose();
    unawaited(_impressionQueue.dispose());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final banners = _banners;
    if (banners == null || banners.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: widget.padding,
      child: Column(
        key: _visibilityKey,
        mainAxisSize: MainAxisSize.min,
        children: [
          AspectRatio(
            aspectRatio: 3,
            child: banners.length == 1
                ? _banner(banners.single)
                : PageView.builder(
                    key: const Key('partner-banner-page-view'),
                    controller: _pageController,
                    itemCount: banners.length,
                    onPageChanged: (value) => setState(() {
                      _page = value;
                      _visibleSince = null;
                    }),
                    itemBuilder: (_, index) => _banner(banners[index]),
                  ),
          ),
          if (banners.length > 1) ...[
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: List.generate(
                banners.length,
                (index) => AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  width: index == _page ? 16 : 6,
                  height: 6,
                  margin: const EdgeInsets.symmetric(horizontal: 3),
                  decoration: BoxDecoration(
                    color: index == _page ? AppColors.blueSoft : AppColors.fg2,
                    borderRadius: BorderRadius.circular(99),
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _banner(PartnerBanner banner) {
    final reward = banner.reward.type == 'none'
        ? '대상 아님'
        : banner.reward.available
            ? banner.reward.label
            : '지급 완료';
    final semantics = '광고, ${banner.imageAlt}, ${banner.partnerName}'
        '${reward.isEmpty ? '' : ', $reward'}';
    final image = widget.imageBuilder?.call(
          context,
          banner,
          () => _removeFailed(banner.id),
        ) ??
        CachedNetworkImage(
          imageUrl: banner.imageUrl,
          fit: BoxFit.cover,
          placeholder: (_, __) => const _BannerShimmer(),
          errorWidget: (_, __, ___) {
            _removeFailed(banner.id);
            return const SizedBox.shrink();
          },
        );
    return Semantics(
      label: semantics,
      button: true,
      excludeSemantics: true,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          key: ValueKey('partner-banner-${banner.id}'),
          onTap: () => _click(banner),
          borderRadius: BorderRadius.circular(22),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(22),
            child: Stack(fit: StackFit.expand, children: [
              image,
              const Positioned(top: 10, right: 10, child: AdBadge()),
              if (reward.isNotEmpty)
                Positioned(
                  left: 10,
                  bottom: 10,
                  child: Container(
                    constraints: const BoxConstraints(maxWidth: 220),
                    padding:
                        const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    decoration: BoxDecoration(
                      color: AppColors.blue,
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Text(reward,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            color: Colors.white,
                            fontSize: 11,
                            fontWeight: FontWeight.w800)),
                  ),
                ),
            ]),
          ),
        ),
      ),
    );
  }
}

class _BannerShimmer extends StatefulWidget {
  const _BannerShimmer();
  @override
  State<_BannerShimmer> createState() => _BannerShimmerState();
}

class _BannerShimmerState extends State<_BannerShimmer>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
      vsync: this, duration: const Duration(milliseconds: 1100))
    ..repeat();
  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _controller,
        builder: (_, __) => DecoratedBox(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment(-1.5 + _controller.value * 3, 0),
              end: Alignment(-.5 + _controller.value * 3, 0),
              colors: const [AppColors.card, AppColors.cardHi, AppColors.card],
            ),
          ),
        ),
      );
}
