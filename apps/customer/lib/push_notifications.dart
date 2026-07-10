import 'dart:async';
import 'dart:convert';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';

const firebaseEnabled =
    bool.fromEnvironment('FIREBASE_ENABLED', defaultValue: false);
const firebaseApiKey = String.fromEnvironment('FIREBASE_API_KEY');
const firebaseAppId = String.fromEnvironment('FIREBASE_APP_ID');
const firebaseMessagingSenderId =
    String.fromEnvironment('FIREBASE_MESSAGING_SENDER_ID');
const firebaseProjectId = String.fromEnvironment('FIREBASE_PROJECT_ID');

FirebaseOptions get appFirebaseOptions => const FirebaseOptions(
      apiKey: firebaseApiKey,
      appId: firebaseAppId,
      messagingSenderId: firebaseMessagingSenderId,
      projectId: firebaseProjectId,
    );

bool get hasCompleteFirebaseOptions =>
    firebaseApiKey.isNotEmpty &&
    firebaseAppId.isNotEmpty &&
    firebaseMessagingSenderId.isNotEmpty &&
    firebaseProjectId.isNotEmpty;

@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  if (!firebaseEnabled || !hasCompleteFirebaseOptions) return;
  if (Firebase.apps.isEmpty) {
    await Firebase.initializeApp(options: appFirebaseOptions);
  }
}

class PushNotifications {
  PushNotifications._();

  static final instance = PushNotifications._();

  bool _initialized = false;
  String _apiBaseUrl = '';
  String? _accountId;
  StreamSubscription<String>? _tokenRefreshSubscription;

  bool get isAvailable => _initialized;

  Future<void> initialize({required String apiBaseUrl}) async {
    _apiBaseUrl = apiBaseUrl;
    if (!firebaseEnabled) return;
    if (!hasCompleteFirebaseOptions) {
      debugPrint('FCM disabled: Firebase client dart-defines are incomplete.');
      return;
    }
    try {
      await Firebase.initializeApp(options: appFirebaseOptions);
      FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);
      _initialized = true;
    } catch (error) {
      debugPrint('FCM initialization failed: ${error.runtimeType}');
    }
  }

  Stream<RemoteMessage> get foregroundMessages =>
      _initialized ? FirebaseMessaging.onMessage : const Stream.empty();

  Stream<RemoteMessage> get openedMessages =>
      _initialized ? FirebaseMessaging.onMessageOpenedApp : const Stream.empty();

  Future<RemoteMessage?> initialMessage() async =>
      _initialized ? FirebaseMessaging.instance.getInitialMessage() : null;

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
      debugPrint('FCM refreshed token synchronization failed: ${error.runtimeType}');
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
    final session = Supabase.instance.client.auth.currentSession;
    if (accountId == null || session == null) return;
    final platform = defaultTargetPlatform == TargetPlatform.iOS
        ? 'ios'
        : defaultTargetPlatform == TargetPlatform.android
            ? 'android'
            : null;
    if (platform == null) return;
    final response = await http.post(
      Uri.parse('$_apiBaseUrl/device-tokens'),
      headers: {
        'Authorization': 'Bearer ${session.accessToken}',
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
    final session = Supabase.instance.client.auth.currentSession;
    if (session == null) return;
    final response = await http.delete(
      Uri.parse('$_apiBaseUrl/device-tokens'),
      headers: {
        'Authorization': 'Bearer ${session.accessToken}',
        'Content-Type': 'application/json',
      },
      body: jsonEncode({'fcm_token': fcmToken}),
    );
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw StateError('Device token removal failed (${response.statusCode})');
    }
  }
}
