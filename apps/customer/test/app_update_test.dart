import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/app_update.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

AppUpdateInfo _info({bool required = false, bool available = false, String url = 'https://store.example/app', int latest = 65}) =>
    AppUpdateInfo(required: required, available: available, storeUrl: url, latestBuild: latest);

Widget _gate(AppUpdateInfo? answer, {List<String>? opened, DateTime Function()? now, Future<int> Function()? loadBuild}) {
  return MaterialApp(
    home: AppUpdateGate(
      baseUrl: 'https://api.example/v1',
      platform: 'android',
      loadBuild: loadBuild ?? () async => 62,
      now: now ?? () => DateTime(2026, 11, 19),
      openStore: (url) async => opened?.add(url),
      fetch: ({required baseUrl, required platform, required build, client, timeout = const Duration(seconds: 6)}) async => answer,
      child: const Scaffold(body: Text('앱 화면')),
    ),
  );
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('fetch asks the version endpoint and reads the answer', () async {
    late Uri asked;
    final client = MockClient((request) async {
      asked = request.url;
      return http.Response(
          jsonEncode({'ok': true, 'data': {'update_required': true, 'update_available': true, 'store_url': 'https://s', 'latest_build': 70}}), 200);
    });
    final info = await fetchAppUpdate(baseUrl: 'https://api.example/v1', platform: 'android', build: 62, client: client);
    expect(asked.path, '/v1/app/version');
    expect(asked.queryParameters, {'platform': 'android', 'build': '62'});
    expect(info!.required, isTrue);
    expect(info.storeUrl, 'https://s');
    expect(info.latestBuild, 70);
  });

  test('fetch never throws: server error, bad body, network failure, unknown build', () async {
    Future<AppUpdateInfo?> run(MockClient client, {int build = 62}) =>
        fetchAppUpdate(baseUrl: 'https://api.example/v1', platform: 'android', build: build, client: client);
    expect(await run(MockClient((_) async => http.Response('oops', 500))), isNull);
    expect(await run(MockClient((_) async => http.Response('not json', 200))), isNull);
    expect(await run(MockClient((_) async => throw http.ClientException('offline'))), isNull);
    var called = false;
    expect(await run(MockClient((_) async { called = true; return http.Response('{}', 200); }), build: 0), isNull);
    expect(called, isFalse);
  });

  testWidgets('required update replaces the app and opens the store', (tester) async {
    final opened = <String>[];
    await tester.pumpWidget(_gate(_info(required: true, available: true), opened: opened));
    await tester.pumpAndSettle();
    expect(find.text('업데이트가 필요해요'), findsOneWidget);
    expect(find.text('앱 화면'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('app-update-required-button')));
    await tester.pump();
    expect(opened, ['https://store.example/app']);
    // Still blocked after returning: there is no way past the screen.
    expect(find.text('업데이트가 필요해요'), findsOneWidget);
  });

  testWidgets('optional update is offered once a day and "나중에" is remembered', (tester) async {
    final opened = <String>[];
    await tester.pumpWidget(_gate(_info(available: true), opened: opened));
    await tester.pumpAndSettle();
    expect(find.text('앱 화면'), findsOneWidget);
    expect(find.text('새 버전이 나왔어요'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('app-update-later')));
    await tester.pumpAndSettle();
    expect(find.text('새 버전이 나왔어요'), findsNothing);
    expect(opened, isEmpty);

    // Same day, fresh start: not asked again.
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(_gate(_info(available: true), opened: opened));
    await tester.pumpAndSettle();
    expect(find.text('새 버전이 나왔어요'), findsNothing);

    // Next day: asked again, and 업데이트 opens the store.
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(_gate(_info(available: true), opened: opened, now: () => DateTime(2026, 11, 20)));
    await tester.pumpAndSettle();
    expect(find.text('새 버전이 나왔어요'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('app-update-now')));
    await tester.pumpAndSettle();
    expect(opened, ['https://store.example/app']);
  });

  testWidgets('no answer, up to date, or unreadable build: the app just opens', (tester) async {
    await tester.pumpWidget(_gate(null));
    await tester.pumpAndSettle();
    expect(find.text('앱 화면'), findsOneWidget);
    expect(find.byType(Dialog), findsNothing);

    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(_gate(_info()));
    await tester.pumpAndSettle();
    expect(find.text('앱 화면'), findsOneWidget);
    expect(find.byType(Dialog), findsNothing);

    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(_gate(_info(required: true), loadBuild: () async => throw StateError('no plugin')));
    await tester.pumpAndSettle();
    expect(find.text('앱 화면'), findsOneWidget);
  });
}
