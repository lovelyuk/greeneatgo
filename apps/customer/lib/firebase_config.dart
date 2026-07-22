import 'package:firebase_core/firebase_core.dart';

const firebaseApiKey = String.fromEnvironment('FIREBASE_API_KEY');
const firebaseAppId = String.fromEnvironment('FIREBASE_APP_ID');
const firebaseMessagingSenderId =
    String.fromEnvironment('FIREBASE_MESSAGING_SENDER_ID');
const firebaseProjectId = String.fromEnvironment('FIREBASE_PROJECT_ID');
const firebaseEnabled =
    bool.fromEnvironment('FIREBASE_ENABLED', defaultValue: false);

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

/// Initializes the shared default Firebase app exactly once.
///
/// Authentication always requires this configuration. FCM may remain disabled
/// independently with FIREBASE_ENABLED=false.
Future<FirebaseApp> ensureFirebaseInitialized() async {
  if (Firebase.apps.isNotEmpty) return Firebase.app();
  if (!hasCompleteFirebaseOptions) {
    throw StateError('Firebase client dart-defines are incomplete.');
  }
  return Firebase.initializeApp(options: appFirebaseOptions);
}
