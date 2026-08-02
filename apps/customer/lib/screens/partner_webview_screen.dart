import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:webview_flutter/webview_flutter.dart';

bool isAllowedPartnerNavigation(String rawUrl) {
  final uri = Uri.tryParse(rawUrl);
  return uri != null &&
      uri.scheme.toLowerCase() == 'https' &&
      uri.host.isNotEmpty;
}

class PartnerWebviewScreen extends StatefulWidget {
  const PartnerWebviewScreen({
    super.key,
    required this.url,
    required this.partnerName,
  });

  final Uri url;
  final String partnerName;

  @override
  State<PartnerWebviewScreen> createState() => _PartnerWebviewScreenState();
}

class _PartnerWebviewScreenState extends State<PartnerWebviewScreen> {
  late final WebViewController _controller;
  Uri? _currentUrl;
  int _progress = 0;

  @override
  void initState() {
    super.initState();
    if (isAllowedPartnerNavigation(widget.url.toString())) {
      _currentUrl = widget.url;
    }
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(
        NavigationDelegate(
          onNavigationRequest: (request) {
            if (!isAllowedPartnerNavigation(request.url)) {
              return NavigationDecision.prevent;
            }
            _setCurrentUrl(request.url);
            return NavigationDecision.navigate;
          },
          onPageStarted: _setCurrentUrl,
          onUrlChange: (change) {
            final url = change.url;
            if (url != null) _setCurrentUrl(url);
          },
          onProgress: (value) {
            if (mounted) setState(() => _progress = value);
          },
        ),
      );
    final initialUrl = _currentUrl;
    if (initialUrl != null) _controller.loadRequest(initialUrl);
  }

  void _setCurrentUrl(String rawUrl) {
    if (!isAllowedPartnerNavigation(rawUrl)) return;
    final uri = Uri.parse(rawUrl);
    if (mounted && uri != _currentUrl) setState(() => _currentUrl = uri);
  }

  void _close() {
    if (mounted) Navigator.of(context).pop();
  }

  Future<void> _systemBack() async {
    if (await _controller.canGoBack()) {
      await _controller.goBack();
    } else {
      _close();
    }
  }

  Future<void> _openExternal() async {
    final url = _currentUrl;
    if (url != null) {
      await launchUrl(url, mode: LaunchMode.externalApplication);
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
        canPop: false,
        onPopInvokedWithResult: (didPop, _) {
          if (!didPop) unawaited(_systemBack());
        },
        child: Scaffold(
          appBar: AppBar(
            leading: IconButton(
              tooltip: '닫기',
              icon: const Icon(Icons.close),
              onPressed: _close,
            ),
            title: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.partnerName,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                Text(
                  _currentUrl?.host ?? '',
                  key: const Key('partner-current-domain'),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.labelSmall,
                ),
              ],
            ),
            actions: [
              IconButton(
                tooltip: '외부 브라우저에서 열기',
                icon: const Icon(Icons.open_in_new_rounded),
                onPressed: _currentUrl == null ? null : _openExternal,
              ),
            ],
            bottom: _progress < 100
                ? PreferredSize(
                    preferredSize: const Size.fromHeight(2),
                    child: LinearProgressIndicator(value: _progress / 100),
                  )
                : null,
          ),
          body: _currentUrl == null
              ? const Center(child: Text('안전하지 않은 주소는 열 수 없어요.'))
              : WebViewWidget(controller: _controller),
        ),
      );
}
