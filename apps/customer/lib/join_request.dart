Map<String, dynamic> buildJoinRequestBody({
  required String inviteCode,
  required String displayName,
  required String phone,
  String? department,
  String? employeeNo,
}) {
  return {
    'invite_code': inviteCode,
    'display_name': displayName,
    'phone': phone,
    if (department != null) 'department': department,
    if (employeeNo != null) 'employee_no': employeeNo,
  };
}
