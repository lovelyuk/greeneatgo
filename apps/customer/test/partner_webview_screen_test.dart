import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/screens/partner_webview_screen.dart';

void main() {
  test('partner WebView policy rejects every non-HTTPS navigation', () {
    expect(isAllowedPartnerNavigation('https://partner.example/path'), isTrue);
    expect(isAllowedPartnerNavigation('HTTPS://partner.example/path'), isTrue);
    expect(isAllowedPartnerNavigation('http://partner.example/path'), isFalse);
    expect(isAllowedPartnerNavigation('javascript:alert(1)'), isFalse);
    expect(isAllowedPartnerNavigation('intent://partner.example'), isFalse);
    expect(isAllowedPartnerNavigation('file:///etc/passwd'), isFalse);
    expect(isAllowedPartnerNavigation('https:///missing-host'), isFalse);
    expect(isAllowedPartnerNavigation('not a url'), isFalse);
  });
}
