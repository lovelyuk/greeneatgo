/// Buyer-facing load error text shared by every screen.
library;

/// Implemented by exceptions that already carry a buyer-safe message
/// (e.g. ApiException).
abstract interface class LoadErrorMessage {
  String get message;
}

const networkErrorMessage = '인터넷에 연결되어 있지 않아요';

/// Buyer-facing text for any load error (raw socket/exception text is hidden).
String friendlyLoadError(Object error) {
  // ApiException (and other typed errors) already carry a buyer message.
  if (error is LoadErrorMessage) return error.message;
  final text = error.toString();
  if (text.contains('SocketException') ||
      text.contains('Failed host lookup') ||
      text.contains('ClientException') ||
      text.contains('Connection closed') ||
      text.contains('HandshakeException')) {
    return networkErrorMessage;
  }
  return text.replaceFirst('Exception: ', '');
}
