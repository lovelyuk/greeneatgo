import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import 'theme/app_colors.dart';

/// Server answer of `GET /app/version`: whether this build must or may update.
class AppUpdateInfo {
  const AppUpdateInfo({
    required this.required,
    required this.available,
    required this.storeUrl,
    required this.latestBuild,
  });

  final bool required;
  final bool available;
  final String storeUrl;
  final int latestBuild;

  static AppUpdateInfo? fromResponse(Object? decoded) {
    if (decoded is! Map) return null;
    final data = decoded['data'];
    if (data is! Map) return null;
    final latest = data['latest_build'];
    return AppUpdateInfo(
      required: data['update_required'] == true,
      available: data['update_available'] == true,
      storeUrl: data['store_url'] is String ? data['store_url'] as String : '',
      latestBuild: latest is int ? latest : 0,
    );
  }
}

/// Asks the server about this build. Any failure answers null: a version check
/// must never keep someone from opening the app and paying for a meal.
Future<AppUpdateInfo?> fetchAppUpdate({
  required String baseUrl,
  required String platform,
  required int build,
  http.Client? client,
  Duration timeout = const Duration(seconds: 6),
}) async {
  if (baseUrl.isEmpty || build <= 0) return null;
  final owned = client == null;
  final httpClient = client ?? http.Client();
  try {
    final uri = Uri.parse('$baseUrl/app/version')
        .replace(queryParameters: {'platform': platform, 'build': '$build'});
    final response = await httpClient.get(uri).timeout(timeout);
    if (response.statusCode != 200) return null;
    return AppUpdateInfo.fromResponse(jsonDecode(utf8.decode(response.bodyBytes)));
  } catch (_) {
    return null;
  } finally {
    if (owned) httpClient.close();
  }
}

Future<int> installedBuildNumber() async {
  final info = await PackageInfo.fromPlatform();
  return int.tryParse(info.buildNumber) ?? 0;
}

String currentUpdatePlatform() => Platform.isIOS ? 'ios' : 'android';

const appUpdateSnoozeKey = 'app_update_snoozed_build_day';

/// Wraps the app: blocks it behind an update screen when the build is too old,
/// and offers (once a day per new build) an optional update otherwise.
class AppUpdateGate extends StatefulWidget {
  const AppUpdateGate({
    super.key,
    required this.child,
    required this.baseUrl,
    this.loadBuild = installedBuildNumber,
    this.platform,
    this.fetch = fetchAppUpdate,
    this.openStore,
    this.now = DateTime.now,
  });

  final Widget child;
  final String baseUrl;
  final Future<int> Function() loadBuild;
  final String? platform;
  final Future<AppUpdateInfo?> Function({
    required String baseUrl,
    required String platform,
    required int build,
    http.Client? client,
    Duration timeout,
  }) fetch;
  final Future<void> Function(String url)? openStore;
  final DateTime Function() now;

  @override
  State<AppUpdateGate> createState() => _AppUpdateGateState();
}

class _AppUpdateGateState extends State<AppUpdateGate>
    with WidgetsBindingObserver {
  AppUpdateInfo? _info;
  bool _offerShown = false;
  bool _checking = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(_check());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Coming back from the store (or a long background): look again, so a
    // required update that was just installed elsewhere or raised meanwhile shows.
    if (state == AppLifecycleState.resumed) unawaited(_check());
  }

  Future<void> _check() async {
    if (_checking) return;
    _checking = true;
    try {
      int build;
      try {
        build = await widget.loadBuild();
      } catch (_) {
        return;
      }
      final info = await widget.fetch(
        baseUrl: widget.baseUrl,
        platform: widget.platform ?? currentUpdatePlatform(),
        build: build,
      );
      if (!mounted || info == null) return;
      setState(() => _info = info);
      if (!info.required && info.available && !_offerShown) {
        _offerShown = true;
        unawaited(_maybeOffer(info));
      }
    } finally {
      _checking = false;
    }
  }

  String _snoozeValue(AppUpdateInfo info) {
    final today = widget.now();
    return '${info.latestBuild}:${today.year}-${today.month}-${today.day}';
  }

  Future<void> _maybeOffer(AppUpdateInfo info) async {
    SharedPreferences? prefs;
    try {
      prefs = await SharedPreferences.getInstance();
      if (prefs.getString(appUpdateSnoozeKey) == _snoozeValue(info)) return;
    } catch (_) {
      // No storage: still offer, just without the once-a-day memory.
    }
    if (!mounted) return;
    final update = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => _UpdateOfferDialog(
        onLater: () => Navigator.of(dialogContext).pop(false),
        onUpdate: () => Navigator.of(dialogContext).pop(true),
      ),
    );
    if (update == true) {
      await _openStore(info.storeUrl);
    } else {
      try {
        await prefs?.setString(appUpdateSnoozeKey, _snoozeValue(info));
      } catch (_) {}
    }
  }

  Future<void> _openStore(String url) async {
    if (url.isEmpty) return;
    final custom = widget.openStore;
    if (custom != null) return custom(url);
    final uri = Uri.tryParse(url);
    if (uri == null) return;
    try {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final info = _info;
    if (info != null && info.required) {
      return _UpdateRequiredScreen(
        hasStore: info.storeUrl.isNotEmpty,
        onUpdate: () => _openStore(info.storeUrl),
      );
    }
    return widget.child;
  }
}

class _UpdateRequiredScreen extends StatelessWidget {
  const _UpdateRequiredScreen({required this.hasStore, required this.onUpdate});

  final bool hasStore;
  final VoidCallback onUpdate;

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      child: Scaffold(
        key: const ValueKey('app-update-required'),
        backgroundColor: AppColors.bg,
        body: SafeArea(
          child: DefaultTextStyle.merge(
            style: const TextStyle(fontFamily: 'Pretendard'),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
              child: Column(
                children: [
                  const Spacer(),
                  Container(
                    width: 76,
                    height: 76,
                    decoration: const BoxDecoration(
                        color: AppColors.cardHi, shape: BoxShape.circle),
                    child: const Icon(Icons.system_update_alt_rounded,
                        color: AppColors.blueSoft, size: 36),
                  ),
                  const SizedBox(height: 22),
                  const Text('업데이트가 필요해요',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                          color: AppColors.fg,
                          fontSize: 23,
                          fontWeight: FontWeight.w800)),
                  const SizedBox(height: 10),
                  Text(
                      hasStore
                          ? '지금 버전은 더 이상 사용할 수 없어요.\n새 버전으로 업데이트한 뒤 이용해 주세요.'
                          : '지금 버전은 더 이상 사용할 수 없어요.\n스토어에서 밥대리를 업데이트해 주세요.',
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                          color: AppColors.fg2, fontSize: 15, height: 1.5)),
                  const Spacer(),
                  if (hasStore)
                    SizedBox(
                      width: double.infinity,
                      height: 54,
                      child: FilledButton(
                        key: const ValueKey('app-update-required-button'),
                        onPressed: onUpdate,
                        style: FilledButton.styleFrom(
                          backgroundColor: AppColors.blue,
                          foregroundColor: Colors.white,
                          shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(16)),
                          textStyle: const TextStyle(
                              fontFamily: 'Pretendard',
                              fontSize: 16,
                              fontWeight: FontWeight.w700),
                        ),
                        child: const Text('업데이트하기'),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _UpdateOfferDialog extends StatelessWidget {
  const _UpdateOfferDialog({required this.onLater, required this.onUpdate});

  final VoidCallback onLater;
  final VoidCallback onUpdate;

  @override
  Widget build(BuildContext context) {
    const label = TextStyle(
        fontFamily: 'Pretendard', fontSize: 15, fontWeight: FontWeight.w700);
    return Dialog(
      key: const ValueKey('app-update-offer'),
      backgroundColor: AppColors.card,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
      child: DefaultTextStyle.merge(
        style: const TextStyle(fontFamily: 'Pretendard'),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(22, 24, 22, 18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('새 버전이 나왔어요',
                  style: TextStyle(
                      color: AppColors.fg,
                      fontSize: 19,
                      fontWeight: FontWeight.w800)),
              const SizedBox(height: 8),
              const Text('업데이트하면 더 안정적으로 이용할 수 있어요.',
                  style: TextStyle(
                      color: AppColors.fg2, fontSize: 14.5, height: 1.45)),
              const SizedBox(height: 20),
              Row(children: [
                Expanded(
                  child: SizedBox(
                    height: 48,
                    child: OutlinedButton(
                      key: const ValueKey('app-update-later'),
                      onPressed: onLater,
                      style: OutlinedButton.styleFrom(
                        foregroundColor: AppColors.fg,
                        side: const BorderSide(color: AppColors.line),
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14)),
                        textStyle: label,
                      ),
                      child: const Text('나중에'),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: SizedBox(
                    height: 48,
                    child: FilledButton(
                      key: const ValueKey('app-update-now'),
                      onPressed: onUpdate,
                      style: FilledButton.styleFrom(
                        backgroundColor: AppColors.blue,
                        foregroundColor: Colors.white,
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14)),
                        textStyle: label,
                      ),
                      child: const Text('업데이트'),
                    ),
                  ),
                ),
              ]),
            ],
          ),
        ),
      ),
    );
  }
}
