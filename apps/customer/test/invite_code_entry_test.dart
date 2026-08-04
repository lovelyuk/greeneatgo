import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/join_request.dart';
import 'package:greeneatgo_customer/screens/invite_code_entry_screen.dart';
import 'package:greeneatgo_customer/theme/app_colors.dart';

void main() {
  setUpAll(() async {
    final pretendard = FontLoader('Pretendard')
      ..addFont(rootBundle.load('assets/fonts/Pretendard-Regular.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-SemiBold.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-Bold.otf'))
      ..addFont(rootBundle.load('assets/fonts/Pretendard-ExtraBold.otf'));
    final materialIcons = FontLoader('MaterialIcons')
      ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await Future.wait([pretendard.load(), materialIcons.load()]);
  });

  test('join payload includes verified profile and employee fields', () {
    expect(
      buildJoinRequestBody(
        inviteCode: 'PILOT',
        displayName: '검증된 고객',
        phone: '01012345678',
        department: '플랫폼팀',
        employeeNo: 'E-100',
      ),
      {
        'invite_code': 'PILOT',
        'display_name': '검증된 고객',
        'phone': '01012345678',
        'department': '플랫폼팀',
        'employee_no': 'E-100',
      },
    );
  });

  Future<void> pumpScreen(
    WidgetTester tester, {
    required InviteJoinSubmit onSubmit,
  }) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(fontFamily: 'Pretendard'),
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(
            textScaler: const TextScaler.linear(1.3),
          ),
          child: child!,
        ),
        home: InviteCodeEntryScreen(
          displayName: '검증된 고객',
          phone: '01012345678',
          onSubmit: onSubmit,
        ),
      ),
    );
    await tester.pump();
  }

  testWidgets('dark 360dp form has exactly the three requested editable fields',
      (tester) async {
    await pumpScreen(tester,
        onSubmit: (
            {required inviteCode,
            required department,
            required employeeNo}) async {});

    expect(find.text('초대코드 입력'), findsOneWidget);
    expect(find.byType(EditableText), findsNWidgets(3));
    expect(find.text('초대코드'), findsOneWidget);
    expect(find.text('부서'), findsOneWidget);
    expect(find.text('사번'), findsOneWidget);
    expect(find.text('이름'), findsNothing);
    expect(find.text('전화번호'), findsNothing);
    final screenContext =
        tester.element(find.byKey(const ValueKey('invite-code-field')));
    expect(Theme.of(screenContext).scaffoldBackgroundColor, AppColors.navyBase);
    final fieldContext =
        tester.element(find.byKey(const ValueKey('invite-code-field')));
    expect(
      Theme.of(fieldContext).inputDecorationTheme.fillColor,
      AppColors.navySurface,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('production invite form golden at 360x640 and text scale 1.3',
      (tester) async {
    await pumpScreen(tester,
        onSubmit: (
            {required inviteCode,
            required department,
            required employeeNo}) async {});
    await expectLater(
      find.byType(InviteCodeEntryScreen),
      matchesGoldenFile('goldens/dark_invite_code_360x640.png'),
    );
  });

  testWidgets('CTA validates all fields and submits trimmed payload once',
      (tester) async {
    Map<String, String>? payload;
    await pumpScreen(tester, onSubmit: (
        {required inviteCode, required department, required employeeNo}) async {
      payload = {
        'invite_code': inviteCode,
        'department': department,
        'employee_no': employeeNo,
      };
    });

    FilledButton button() => tester.widget<FilledButton>(
        find.byKey(const ValueKey('invite-submit-button')));
    expect(button().onPressed, isNull);

    await tester.enterText(
        find.byKey(const ValueKey('invite-code-field')), ' PILOT ');
    expect(button().onPressed, isNull);
    await tester.enterText(
        find.byKey(const ValueKey('department-field')), ' 플랫폼팀 ');
    expect(button().onPressed, isNull);
    await tester.enterText(
        find.byKey(const ValueKey('employee-no-field')), ' E-100 ');
    await tester.pump();
    expect(button().onPressed, isNotNull);

    await tester.tap(find.byKey(const ValueKey('invite-submit-button')));
    await tester.pumpAndSettle();
    expect(payload, {
      'invite_code': 'PILOT',
      'department': '플랫폼팀',
      'employee_no': 'E-100',
    });
    expect(find.byKey(const ValueKey('invite-submit-success')), findsOneWidget);
    expect(find.textContaining('승인을 기다려 주세요'), findsOneWidget);
    expect(button().onPressed, isNull);
    expect(tester.takeException(), isNull);
  });

  testWidgets('loading and server errors are shown honestly', (tester) async {
    final gate = Completer<void>();
    await pumpScreen(tester,
        onSubmit: (
                {required inviteCode,
                required department,
                required employeeNo}) =>
            gate.future);
    await tester.enterText(
        find.byKey(const ValueKey('invite-code-field')), 'PILOT');
    await tester.enterText(
        find.byKey(const ValueKey('department-field')), '플랫폼팀');
    await tester.enterText(
        find.byKey(const ValueKey('employee-no-field')), 'E-100');
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('invite-submit-button')));
    await tester.pump();
    expect(find.text('요청 중...'), findsOneWidget);
    expect(
      tester
          .widget<FilledButton>(
              find.byKey(const ValueKey('invite-submit-button')))
          .onPressed,
      isNull,
    );
    gate.completeError(Exception('유효하지 않은 초대코드예요'));
    await tester.pumpAndSettle();
    expect(find.text('유효하지 않은 초대코드예요'), findsOneWidget);
    expect(find.byKey(const ValueKey('invite-submit-success')), findsNothing);
  });

  testWidgets('back arrow pops the dark form route', (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (context) => Scaffold(
          body: TextButton(
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => InviteCodeEntryScreen(
                displayName: '검증된 고객',
                phone: '01012345678',
                onSubmit: (
                    {required inviteCode,
                    required department,
                    required employeeNo}) async {},
              ),
            )),
            child: const Text('열기'),
          ),
        ),
      ),
    ));
    await tester.tap(find.text('열기'));
    await tester.pumpAndSettle();
    expect(find.text('초대코드 입력'), findsOneWidget);
    await tester.tap(find.byTooltip('뒤로가기'));
    await tester.pumpAndSettle();
    expect(find.text('초대코드 입력'), findsNothing);
    expect(find.text('열기'), findsOneWidget);
  });
}
