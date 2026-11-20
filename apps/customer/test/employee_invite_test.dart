import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greeneatgo_customer/employee_invite.dart';

void main() {
  setUp(resetEmployeeInviteMemory);

  test('the offer is read from /me and ignored when incomplete', () {
    final offer = EmployeeInviteOffer.fromMe({
      'employee_invite_offer': {'invite_id': 'inv-1', 'company_name': ' 테스트회사 ', 'department': '개발팀'},
    });
    expect((offer!.inviteId, offer.companyName), ('inv-1', '테스트회사'));
    expect(EmployeeInviteOffer.fromMe({'employee_invite_offer': null}), isNull);
    expect(EmployeeInviteOffer.fromMe(const {}), isNull);
    expect(EmployeeInviteOffer.fromMe({'employee_invite_offer': {'invite_id': 'inv-1'}}), isNull);
    expect(EmployeeInviteOffer.fromMe({'employee_invite_offer': {'company_name': '테스트회사'}}), isNull);
  });

  test('an offer is asked once per app session; a different offer is asked again', () {
    const first = EmployeeInviteOffer(inviteId: 'inv-1', companyName: '테스트회사');
    expect(shouldAskEmployeeInvite(first), isTrue);
    expect(shouldAskEmployeeInvite(first), isFalse);
    expect(shouldAskEmployeeInvite(const EmployeeInviteOffer(inviteId: 'inv-2', companyName: '다른회사')), isTrue);
    expect(shouldAskEmployeeInvite(null), isFalse);
  });

  Future<bool?> ask(WidgetTester tester, String buttonKey) async {
    bool? answer;
    var answered = false;
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (context) => TextButton(
          onPressed: () async {
            answer = await showEmployeeInviteDialog(
                context, const EmployeeInviteOffer(inviteId: 'inv-1', companyName: '테스트회사'));
            answered = true;
          },
          child: const Text('open'),
        ),
      ),
    ));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(find.text('테스트회사 직원으로 전환할까요?'), findsOneWidget);
    expect(find.textContaining('거절하면 회사 관리자에게 거절한 것으로 표시돼요.'), findsOneWidget);
    // Tapping outside does not answer for the member.
    await tester.tapAt(const Offset(5, 5));
    await tester.pumpAndSettle();
    expect(answered, isFalse);
    await tester.tap(find.byKey(ValueKey(buttonKey)));
    await tester.pumpAndSettle();
    expect(answered, isTrue);
    return answer;
  }

  testWidgets('전환하기 answers true', (tester) async => expect(await ask(tester, 'employee-invite-accept'), isTrue));
  testWidgets('거절 answers false', (tester) async => expect(await ask(tester, 'employee-invite-decline'), isFalse));
  testWidgets('나중에 answers nothing', (tester) async => expect(await ask(tester, 'employee-invite-later'), isNull));
}
