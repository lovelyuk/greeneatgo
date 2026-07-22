import 'dart:async';
import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:http/http.dart' as http;

import 'firebase_config.dart';

@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  if (!firebaseEnabled || !hasCompleteFirebaseOptions) return;
  await ensureFirebaseInitialized();
}

class PushNotifications {
  PushNotifications._();

  static final instance = PushNotifications._();

  bool _initialized = false;
  String _apiBaseUrl = '';
  String? _accountId;
  StreamSubscription<String>? _tokenRefreshSubscription;
  final FlutterLocalNotificationsPlugin _localNotifications =
      FlutterLocalNotificationsPlugin();

  static const AndroidNotificationChannel _announcementChannel =
      AndroidNotificationChannel(
    'greeneat_announcements',
    'Green eat 공지',
    description: '공지와 포인트 충전 알림을 표시합니다.',
    importance: Importance.max,
  );

  bool get isAvailable => _initialized;

  Future<void> initialize({required String apiBaseUrl}) async {
    _apiBaseUrl = apiBaseUrl;
    if (!firebaseEnabled) return;
    if (!hasCompleteFirebaseOptions) {
      debugPrint('FCM disabled: Firebase client dart-defines are incomplete.');
      return;
    }
    try {
      await ensureFirebaseInitialized();
      FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);
      await _localNotifications.initialize(
        settings: const InitializationSettings(
          android: AndroidInitializationSettings('ic_stat_notification'),
          iOS: DarwinInitializationSettings(),
        ),
      );
      await _localNotifications
          .resolvePlatformSpecificImplementation<
              AndroidFlutterLocalNotificationsPlugin>()
          ?.createNotificationChannel(_announcementChannel);
      await FirebaseMessaging.instance
          .setForegroundNotificationPresentationOptions(
        alert: true,
        badge: true,
        sound: true,
      );
      _initialized = true;
    } catch (error) {
      debugPrint('FCM initialization failed: ${error.runtimeType}');
    }
  }

  Stream<RemoteMessage> get foregroundMessages =>
      _initialized ? FirebaseMessaging.onMessage : const Stream.empty();

  Stream<RemoteMessage> get openedMessages => _initialized
      ? FirebaseMessaging.onMessageOpenedApp
      : const Stream.empty();

  Future<RemoteMessage?> initialMessage() async =>
      _initialized ? FirebaseMessaging.instance.getInitialMessage() : null;

  Future<void> showForegroundNotification(RemoteMessage message) async {
    if (!_initialized) return;
    final title = message.notification?.title ?? 'Green eat 알림';
    final body = message.notification?.body ?? '';
    await _localNotifications.show(
      id: message.messageId?.hashCode ??
          DateTime.now().millisecondsSinceEpoch.remainder(2147483647),
      title: title,
      body: body,
      notificationDetails: const NotificationDetails(
        android: AndroidNotificationDetails(
          'greeneat_announcements',
          'Green eat 공지',
          channelDescription: '공지와 포인트 충전 알림을 표시합니다.',
          importance: Importance.max,
          priority: Priority.high,
          icon: 'ic_stat_notification',
          playSound: true,
        ),
        iOS: DarwinNotificationDetails(
          presentAlert: true,
          presentBadge: true,
          presentSound: true,
        ),
      ),
      payload: jsonEncode(message.data),
    );
  }

  Future<void> activateForAccount(String accountId) async {
    if (!_initialized) return;
    _accountId = accountId;
    await _tokenRefreshSubscription?.cancel();
    _tokenRefreshSubscription =
        FirebaseMessaging.instance.onTokenRefresh.listen((token) {
      unawaited(_handleTokenRefresh(token));
    });
    try {
      final settings = await FirebaseMessaging.instance.requestPermission(
        alert: true,
        badge: true,
        sound: true,
      );
      if (settings.authorizationStatus == AuthorizationStatus.denied) return;
      final token = await FirebaseMessaging.instance.getToken();
      if (token != null && token.isNotEmpty) await _register(token);
    } catch (error) {
      debugPrint('FCM token synchronization failed: ${error.runtimeType}');
    }
  }

  Future<void> _handleTokenRefresh(String token) async {
    try {
      await _register(token);
    } catch (error) {
      debugPrint(
          'FCM refreshed token synchronization failed: ${error.runtimeType}');
    }
  }

  Future<void> deactivateBeforeLogout() async {
    if (!_initialized) return;
    await _tokenRefreshSubscription?.cancel();
    _tokenRefreshSubscription = null;
    try {
      final token = await FirebaseMessaging.instance.getToken();
      if (token != null && token.isNotEmpty) await _unregister(token);
      await FirebaseMessaging.instance.deleteToken();
    } catch (error) {
      debugPrint('FCM logout cleanup failed: ${error.runtimeType}');
    } finally {
      _accountId = null;
    }
  }

  Future<void> _register(String fcmToken) async {
    final accountId = _accountId;
    final user = FirebaseAuth.instance.currentUser;
    if (accountId == null || user == null) return;
    final idToken = await user.getIdToken();
    if (idToken == null || idToken.isEmpty) return;
    final platform = defaultTargetPlatform == TargetPlatform.iOS
        ? 'ios'
        : defaultTargetPlatform == TargetPlatform.android
            ? 'android'
            : null;
    if (platform == null) return;
    final response = await http.post(
      Uri.parse('$_apiBaseUrl/device-tokens'),
      headers: {
        'Authorization': 'Bearer $idToken',
        'Content-Type': 'application/json',
      },
      body: jsonEncode({
        'account_id': accountId,
        'fcm_token': fcmToken,
        'platform': platform,
      }),
    );
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw StateError('Device token API failed (${response.statusCode})');
    }
  }

  Future<void> _unregister(String fcmToken) async {
    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return;
    final idToken = await user.getIdToken();
    if (idToken == null || idToken.isEmpty) return;
    final response = await http.delete(
      Uri.parse('$_apiBaseUrl/device-tokens'),
      headers: {
        'Authorization': 'Bearer $idToken',
        'Content-Type': 'application/json',
      },
      body: jsonEncode({'fcm_token': fcmToken}),
    );
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw StateError('Device token removal failed (${response.statusCode})');
    }
  }
}
