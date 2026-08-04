import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme/app_colors.dart';

typedef InviteJoinSubmit = Future<void> Function({
  required String inviteCode,
  required String department,
  required String employeeNo,
});

class InviteCodeEntryScreen extends StatefulWidget {
  const InviteCodeEntryScreen({
    super.key,
    required this.displayName,
    required this.phone,
    required this.onSubmit,
  });

  final String displayName;
  final String phone;
  final InviteJoinSubmit onSubmit;

  @override
  State<InviteCodeEntryScreen> createState() => _InviteCodeEntryScreenState();
}

class _InviteCodeEntryScreenState extends State<InviteCodeEntryScreen> {
  final _inviteCode = TextEditingController();
  final _department = TextEditingController();
  final _employeeNo = TextEditingController();
  bool _submitting = false;
  String? _error;
  String? _success;

  bool get _canSubmit =>
      !_submitting &&
      _success == null &&
      _inviteCode.text.trim().isNotEmpty &&
      _department.text.trim().isNotEmpty &&
      _employeeNo.text.trim().isNotEmpty;

  @override
  void initState() {
    super.initState();
    _inviteCode.addListener(_fieldsChanged);
    _department.addListener(_fieldsChanged);
    _employeeNo.addListener(_fieldsChanged);
  }

  void _fieldsChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _inviteCode.dispose();
    _department.dispose();
    _employeeNo.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_canSubmit) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      await widget.onSubmit(
        inviteCode: _inviteCode.text.trim(),
        department: _department.text.trim(),
        employeeNo: _employeeNo.text.trim(),
      );
      if (!mounted) return;
      setState(() => _success = '가입 요청을 보냈어요. 회사 관리자의 승인을 기다려 주세요.');
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.toString().replaceFirst('Exception: ', '');
      });
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  ThemeData _darkTheme(BuildContext context) {
    final base = Theme.of(context);
    final border = OutlineInputBorder(
      borderRadius: BorderRadius.circular(12),
      borderSide: const BorderSide(color: AppColors.navyBorder),
    );
    return base.copyWith(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: AppColors.navyBase,
      canvasColor: AppColors.navyBase,
      colorScheme: const ColorScheme.dark(
        primary: AppColors.limeGreen,
        onPrimary: AppColors.textOnLime,
        surface: AppColors.navySurface,
        onSurface: AppColors.textPrimary,
        error: Color(0xFFFF8A8A),
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.navyBase,
        foregroundColor: AppColors.textPrimary,
        elevation: 0,
        surfaceTintColor: Colors.transparent,
        systemOverlayStyle: SystemUiOverlayStyle.light,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.navySurface,
        labelStyle: const TextStyle(color: AppColors.textSecondary),
        hintStyle: const TextStyle(color: AppColors.textPlaceholder),
        enabledBorder: border,
        focusedBorder: border.copyWith(
          borderSide: const BorderSide(
            color: AppColors.navyBorderStrong,
            width: 1.5,
          ),
        ),
        disabledBorder: border,
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size.fromHeight(52),
          backgroundColor: AppColors.limeGreen,
          foregroundColor: AppColors.textOnLime,
          disabledBackgroundColor: AppColors.navyBorder,
          disabledForegroundColor: AppColors.textMuted,
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          textStyle: const TextStyle(
            fontFamily: 'Pretendard',
            fontSize: 16,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(foregroundColor: AppColors.textLink),
      ),
      dialogTheme: const DialogThemeData(
        backgroundColor: AppColors.navySurface,
        surfaceTintColor: Colors.transparent,
        titleTextStyle: TextStyle(color: AppColors.textPrimary),
        contentTextStyle: TextStyle(color: AppColors.textSecondary),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: Theme(
        data: _darkTheme(context),
        child: Scaffold(
          appBar: AppBar(
            leading: IconButton(
              tooltip: '뒤로가기',
              onPressed: () => Navigator.of(context).pop(_success != null),
              icon: const Icon(Icons.arrow_back_ios_new_rounded),
            ),
            title: const Text(
              '초대코드 입력',
              style: TextStyle(fontSize: 19, fontWeight: FontWeight.w700),
            ),
          ),
          body: SafeArea(
            top: false,
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 28),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text(
                    '회사 가입 정보',
                    style: TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 24,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    '회사에서 안내받은 정보를 입력해 주세요. 요청 후 회사 관리자의 승인이 필요해요.',
                    style: TextStyle(
                      color: AppColors.textSecondary,
                      fontSize: 14,
                      height: 1.5,
                    ),
                  ),
                  const SizedBox(height: 24),
                  TextField(
                    key: const ValueKey('invite-code-field'),
                    controller: _inviteCode,
                    enabled: !_submitting && _success == null,
                    textInputAction: TextInputAction.next,
                    decoration: const InputDecoration(
                      labelText: '초대코드',
                      hintText: '초대코드를 입력해 주세요',
                    ),
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    key: const ValueKey('department-field'),
                    controller: _department,
                    enabled: !_submitting && _success == null,
                    textInputAction: TextInputAction.next,
                    decoration: const InputDecoration(
                      labelText: '부서',
                      hintText: '소속 부서를 입력해 주세요',
                    ),
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    key: const ValueKey('employee-no-field'),
                    controller: _employeeNo,
                    enabled: !_submitting && _success == null,
                    textInputAction: TextInputAction.done,
                    onSubmitted: (_) => _submit(),
                    decoration: const InputDecoration(
                      labelText: '사번',
                      hintText: '사번을 입력해 주세요',
                    ),
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 14),
                    Text(
                      _error!,
                      key: const ValueKey('invite-submit-error'),
                      style: const TextStyle(
                        color: Color(0xFFFF8A8A),
                        fontSize: 13,
                        height: 1.45,
                      ),
                    ),
                  ],
                  if (_success != null) ...[
                    const SizedBox(height: 14),
                    Text(
                      _success!,
                      key: const ValueKey('invite-submit-success'),
                      style: const TextStyle(
                        color: AppColors.limeGreen,
                        fontSize: 13,
                        height: 1.45,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                  const SizedBox(height: 24),
                  FilledButton(
                    key: const ValueKey('invite-submit-button'),
                    onPressed: _canSubmit ? _submit : null,
                    child: Text(_submitting
                        ? '요청 중...'
                        : _success == null
                            ? '가입 요청하기'
                            : '요청 완료'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
