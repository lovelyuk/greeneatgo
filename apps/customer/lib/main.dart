import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';

const supabaseUrl = String.fromEnvironment('SUPABASE_URL');
const supabaseAnonKey = String.fromEnvironment('SUPABASE_ANON_KEY');
const apiBaseUrl = String.fromEnvironment('API_BASE_URL');
const authEmailRedirectTo = String.fromEnvironment('AUTH_EMAIL_REDIRECT_TO', defaultValue: 'https://greeneatgo-api.onrender.com/v1/auth/confirmed');

const kInk = Color(0xFF23190F);
const kCocoa = Color(0xFF4A2A14);
const kOrange = Color(0xFFFF7A1A);
const kTangerine = Color(0xFFFFA629);
const kCream = Color(0xFFFFF7E8);
const kCard = Color(0xFFFFFCF4);
const kMint = Color(0xFF23B26D);
const kLine = Color(0xFFFFDEAA);

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (supabaseUrl.isNotEmpty && supabaseAnonKey.isNotEmpty) {
    await Supabase.initialize(url: supabaseUrl, publishableKey: supabaseAnonKey);
  }
  runApp(const GreeneatGoApp());
}

class GreeneatGoApp extends StatelessWidget {
  const GreeneatGoApp({super.key});

  @override
  Widget build(BuildContext context) {
    final base = ThemeData(useMaterial3: true, fontFamily: 'Roboto');
    return MaterialApp(
      title: '그린잇',
      debugShowCheckedModeBanner: false,
      theme: base.copyWith(
        scaffoldBackgroundColor: kCream,
        colorScheme: ColorScheme.fromSeed(seedColor: kOrange, brightness: Brightness.light, primary: kOrange, secondary: kTangerine, surface: kCard),
        textTheme: base.textTheme.apply(bodyColor: kInk, displayColor: kInk),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: Colors.white,
          labelStyle: const TextStyle(color: Color(0xFF8B6544), fontWeight: FontWeight.w700),
          hintStyle: const TextStyle(color: Color(0xFFB39678)),
          contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(18), borderSide: const BorderSide(color: kLine)),
          enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(18), borderSide: const BorderSide(color: kLine)),
          focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(18), borderSide: const BorderSide(color: kOrange, width: 2)),
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
            backgroundColor: kOrange,
            foregroundColor: Colors.white,
            minimumSize: const Size.fromHeight(54),
            textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w900),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
          ),
        ),
        outlinedButtonTheme: OutlinedButtonThemeData(
          style: OutlinedButton.styleFrom(
            foregroundColor: kCocoa,
            side: const BorderSide(color: kLine, width: 1.4),
            minimumSize: const Size.fromHeight(52),
            textStyle: const TextStyle(fontWeight: FontWeight.w900),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
          ),
        ),
        appBarTheme: const AppBarTheme(backgroundColor: Colors.transparent, elevation: 0, foregroundColor: kInk, centerTitle: false),
      ),
      home: const AppGate(),
    );
  }
}

class ApiClient {
  ApiClient(this.session);
  final Session session;

  Future<Map<String, dynamic>> getMe() async => _request('/me');

  Future<Map<String, dynamic>> requestJoin({required String inviteCode, required String displayName}) {
    return _request('/join/request', method: 'POST', body: {'invite_code': inviteCode, 'display_name': displayName});
  }

  Future<Map<String, dynamic>> _request(String path, {String method = 'GET', Map<String, dynamic>? body}) async {
    final uri = Uri.parse('$apiBaseUrl$path');
    final request = http.Request(method, uri)
      ..headers['Authorization'] = 'Bearer ${session.accessToken}'
      ..headers['Content-Type'] = 'application/json';
    if (body != null) request.body = jsonEncode(body);
    final streamed = await request.send();
    final text = await streamed.stream.bytesToString();
    final decoded = text.isEmpty ? <String, dynamic>{} : jsonDecode(text) as Map<String, dynamic>;
    if (streamed.statusCode < 200 || streamed.statusCode >= 300) {
      final detail = decoded['detail'] as Map<String, dynamic>?;
      throw Exception(detail?['message'] ?? 'API 오류가 발생했어요');
    }
    return decoded['data'] as Map<String, dynamic>;
  }
}

class AppGate extends StatefulWidget {
  const AppGate({super.key});

  @override
  State<AppGate> createState() => _AppGateState();
}

class _AppGateState extends State<AppGate> {
  Session? _session;
  Map<String, dynamic>? _me;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    if (supabaseUrl.isEmpty || supabaseAnonKey.isEmpty || apiBaseUrl.isEmpty) {
      _error = '앱 환경값이 누락됐어요. SUPABASE_URL, SUPABASE_ANON_KEY, API_BASE_URL을 확인해 주세요.';
      _loading = false;
      return;
    }
    _session = Supabase.instance.client.auth.currentSession;
    Supabase.instance.client.auth.onAuthStateChange.listen((event) {
      setState(() => _session = event.session);
      _loadMe();
    });
    _loadMe();
  }

  Future<void> _loadMe() async {
    final session = _session;
    if (session == null) {
      setState(() {
        _me = null;
        _loading = false;
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final me = await ApiClient(session).getMe();
      setState(() => _me = me);
    } catch (error) {
      setState(() => _error = error.toString().replaceFirst('Exception: ', ''));
    } finally {
      setState(() => _loading = false);
    }
  }

  Future<void> _signOut() async {
    await Supabase.instance.client.auth.signOut();
    setState(() {
      _session = null;
      _me = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const BrandLoadingScreen();
    if (_error != null && _session == null) return ErrorScreen(message: _error!);
    if (_session == null) return LoginScreen(onLoggedIn: _loadMe);
    if (_error != null) return ErrorScreen(message: _error!, onRetry: _loadMe, onSignOut: _signOut);

    final status = _me?['status'] as String? ?? 'no_profile';
    if (status == 'no_profile' || status == 'rejected') {
      return InviteCodeScreen(session: _session!, me: _me, onSubmitted: _loadMe, onSignOut: _signOut);
    }
    if (status == 'pending') return PendingScreen(me: _me!, onRefresh: _loadMe, onSignOut: _signOut);
    if (status != 'active') return BlockedScreen(status: status, onRefresh: _loadMe, onSignOut: _signOut);
    return HomeScreen(me: _me!, onRefresh: _loadMe, onSignOut: _signOut);
  }
}

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.onLoggedIn});
  final Future<void> Function() onLoggedIn;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _passwordConfirm = TextEditingController();
  final _displayName = TextEditingController();
  bool _busy = false;
  bool _signupMode = false;
  String? _error;
  String? _info;

  Future<void> _login() async {
    setState(() { _busy = true; _error = null; _info = null; });
    try {
      await Supabase.instance.client.auth.signInWithPassword(email: _email.text.trim(), password: _password.text);
      await widget.onLoggedIn();
    } catch (error) {
      setState(() => _error = _friendlyAuthError(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _signup() async {
    setState(() { _busy = true; _error = null; _info = null; });
    final email = _email.text.trim();
    final password = _password.text;
    final displayName = _displayName.text.trim();

    if (displayName.isEmpty) {
      setState(() { _busy = false; _error = '이름을 입력해 주세요.'; });
      return;
    }
    if (password.length < 6) {
      setState(() { _busy = false; _error = '비밀번호는 6자 이상으로 입력해 주세요.'; });
      return;
    }
    if (password != _passwordConfirm.text) {
      setState(() { _busy = false; _error = '비밀번호 확인이 일치하지 않아요.'; });
      return;
    }

    try {
      final response = await Supabase.instance.client.auth.signUp(
        email: email,
        password: password,
        emailRedirectTo: authEmailRedirectTo,
        data: {'display_name': displayName},
      );
      if (response.session != null) {
        await widget.onLoggedIn();
      } else {
        setState(() {
          _signupMode = false;
          _info = '회원가입 완료! 이메일 인증을 켠 경우 메일 확인 후 로그인해 주세요.';
        });
      }
    } catch (error) {
      setState(() => _error = _friendlyAuthError(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String _friendlyAuthError(Object error) {
    final text = error.toString();
    if (text.contains('Invalid login credentials')) return '이메일 또는 비밀번호가 올바르지 않아요.';
    if (text.contains('User already registered')) return '이미 가입된 이메일이에요. 로그인해 주세요.';
    if (text.contains('Password should be')) return '비밀번호 조건을 확인해 주세요.';
    return text.replaceFirst('AuthException(message: ', '').replaceFirst('Exception: ', '');
  }

  void _toggleMode() {
    setState(() {
      _signupMode = !_signupMode;
      _error = null;
      _info = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return BrandBackground(
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(22, 18, 22, 28),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const SizedBox(height: 10),
            const BrandLogo(),
            const SizedBox(height: 24),
            Container(
              padding: const EdgeInsets.all(22),
              decoration: brandCardDecoration(radius: 30),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                _SnackHero(signupMode: _signupMode),
                const SizedBox(height: 22),
                if (_signupMode) ...[
                  TextField(controller: _displayName, textInputAction: TextInputAction.next, decoration: const InputDecoration(labelText: '이름', prefixIcon: Icon(Icons.badge_outlined))),
                  const SizedBox(height: 12),
                ],
                TextField(controller: _email, keyboardType: TextInputType.emailAddress, textInputAction: TextInputAction.next, decoration: const InputDecoration(labelText: '이메일', prefixIcon: Icon(Icons.mail_outline))),
                const SizedBox(height: 12),
                TextField(controller: _password, obscureText: true, textInputAction: _signupMode ? TextInputAction.next : TextInputAction.done, decoration: const InputDecoration(labelText: '비밀번호', prefixIcon: Icon(Icons.lock_outline))),
                if (_signupMode) ...[
                  const SizedBox(height: 12),
                  TextField(controller: _passwordConfirm, obscureText: true, textInputAction: TextInputAction.done, decoration: const InputDecoration(labelText: '비밀번호 확인', prefixIcon: Icon(Icons.verified_user_outlined))),
                ],
                if (_error != null) BrandNotice(text: _error!, kind: NoticeKind.error),
                if (_info != null) BrandNotice(text: _info!, kind: NoticeKind.success),
                const SizedBox(height: 18),
                FilledButton(onPressed: _busy ? null : (_signupMode ? _signup : _login), child: Text(_busy ? '처리 중...' : (_signupMode ? '직원 계정 만들기' : '따뜻한 한 끼 시작하기'))),
                const SizedBox(height: 10),
                TextButton(onPressed: _busy ? null : _toggleMode, child: Text(_signupMode ? '이미 계정이 있어요' : '처음 사용하는 직원이에요')),
              ]),
            ),
            const SizedBox(height: 16),
            const Text('회원가입 후 회사 초대코드 입력과 관리자 승인을 거쳐 식대 사용이 가능해요.', textAlign: TextAlign.center, style: TextStyle(color: Color(0xFF8B6544), fontWeight: FontWeight.w700)),
          ]),
        ),
      ),
    );
  }
}

class InviteCodeScreen extends StatefulWidget {
  const InviteCodeScreen({super.key, required this.session, required this.me, required this.onSubmitted, required this.onSignOut});
  final Session session;
  final Map<String, dynamic>? me;
  final Future<void> Function() onSubmitted;
  final Future<void> Function() onSignOut;

  @override
  State<InviteCodeScreen> createState() => _InviteCodeScreenState();
}

class _InviteCodeScreenState extends State<InviteCodeScreen> {
  final _name = TextEditingController(text: '테스트 직원');
  final _code = TextEditingController(text: 'PILOT-GREEN-2026');
  bool _busy = false;
  String? _error;

  Future<void> _submit() async {
    setState(() { _busy = true; _error = null; });
    try {
      await ApiClient(widget.session).requestJoin(inviteCode: _code.text.trim(), displayName: _name.text.trim());
      await widget.onSubmitted();
    } catch (error) {
      setState(() => _error = error.toString().replaceFirst('Exception: ', ''));
    } finally {
      setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final rejected = widget.me?['status'] == 'rejected';
    return AppScaffold(
      title: rejected ? '다시 초대코드를 확인해요' : '회사 초대코드 입력',
      subtitle: rejected ? '관리자에게 확인 후 재요청할 수 있어요.' : '회사에서 받은 코드를 입력하면 승인 대기 상태가 됩니다.',
      onSignOut: widget.onSignOut,
      child: BrandPanel(children: [
        const MiniSnackRow(),
        const SizedBox(height: 20),
        TextField(controller: _name, decoration: const InputDecoration(labelText: '이름', prefixIcon: Icon(Icons.person_outline))),
        const SizedBox(height: 12),
        TextField(controller: _code, decoration: const InputDecoration(labelText: '초대코드', prefixIcon: Icon(Icons.confirmation_number_outlined))),
        if (_error != null) BrandNotice(text: _error!, kind: NoticeKind.error),
        const SizedBox(height: 16),
        FilledButton(onPressed: _busy ? null : _submit, child: Text(_busy ? '요청 중...' : '가입 요청 보내기')),
      ]),
    );
  }
}

class PendingScreen extends StatelessWidget {
  const PendingScreen({super.key, required this.me, required this.onRefresh, required this.onSignOut});
  final Map<String, dynamic> me;
  final Future<void> Function() onRefresh;
  final Future<void> Function() onSignOut;

  @override
  Widget build(BuildContext context) {
    return AppScaffold(
      title: '승인 대기 중이에요',
      subtitle: '관리자가 확인하면 바로 한 끼를 시작할 수 있어요.',
      onSignOut: onSignOut,
      child: BrandPanel(children: [
        const Center(child: SnackMascot(size: 96)),
        const SizedBox(height: 16),
        Text('${me['display_name']}님의 가입 요청을 회사 관리자에게 보냈어요.', textAlign: TextAlign.center, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
        const SizedBox(height: 16),
        OutlinedButton(onPressed: onRefresh, child: const Text('승인 상태 새로고침')),
      ]),
    );
  }
}

class BlockedScreen extends StatelessWidget {
  const BlockedScreen({super.key, required this.status, required this.onRefresh, required this.onSignOut});
  final String status;
  final Future<void> Function() onRefresh;
  final Future<void> Function() onSignOut;

  @override
  Widget build(BuildContext context) {
    return AppScaffold(
      title: '사용할 수 없는 계정이에요',
      subtitle: '상태를 확인하고 다시 시도해 주세요.',
      onSignOut: onSignOut,
      child: BrandPanel(children: [
        BrandNotice(text: '현재 상태: $status', kind: NoticeKind.error),
        const SizedBox(height: 16),
        OutlinedButton(onPressed: onRefresh, child: const Text('새로고침')),
      ]),
    );
  }
}

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key, required this.me, required this.onRefresh, required this.onSignOut});
  final Map<String, dynamic> me;
  final Future<void> Function() onRefresh;
  final Future<void> Function() onSignOut;

  @override
  Widget build(BuildContext context) {
    final name = me['display_name'] as String? ?? '직원';
    return AppScaffold(
      title: '오늘도 든든하게',
      subtitle: '$name님, 출출할 땐 회사 식대로 간편하게 해결해요.',
      onSignOut: onSignOut,
      actions: [IconButton(onPressed: onRefresh, icon: const Icon(Icons.refresh_rounded))],
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        _BalanceCard(name: name),
        const SizedBox(height: 16),
        Row(children: [
          Expanded(child: _QuickAction(icon: Icons.qr_code_scanner_rounded, label: 'QR 결제', color: kOrange, onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const PaymentCompletePreview())))),
          const SizedBox(width: 12),
          Expanded(child: _QuickAction(icon: Icons.storefront_rounded, label: '매장 찾기', color: kMint, onTap: () {})),
        ]),
        const SizedBox(height: 24),
        const SectionHeader(title: '최근 이용', action: '이번 주 3회'),
        const SizedBox(height: 10),
        const _HistoryTile(title: '든든 김치찌개', meta: '오늘 중식 · 12:21', price: '-9,000원', emoji: '🍲'),
        const _HistoryTile(title: '샌드위치 박스', meta: '어제 간식 · 16:08', price: '-6,500원', emoji: '🥪'),
      ]),
    );
  }
}

class AppScaffold extends StatelessWidget {
  const AppScaffold({super.key, required this.title, required this.child, this.subtitle, this.onSignOut, this.actions = const []});
  final String title;
  final String? subtitle;
  final Widget child;
  final Future<void> Function()? onSignOut;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    return BrandBackground(
      child: Scaffold(
        backgroundColor: Colors.transparent,
        appBar: AppBar(actions: [...actions, if (onSignOut != null) IconButton(onPressed: onSignOut, icon: const Icon(Icons.logout_rounded))]),
        body: SafeArea(
          top: false,
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 28),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              const BrandLogo(compact: true),
              const SizedBox(height: 18),
              Text(title, style: const TextStyle(fontSize: 31, height: 1.08, fontWeight: FontWeight.w900, color: kInk)),
              if (subtitle != null) ...[
                const SizedBox(height: 8),
                Text(subtitle!, style: const TextStyle(fontSize: 15, color: Color(0xFF7A5637), fontWeight: FontWeight.w700)),
              ],
              const SizedBox(height: 22),
              child,
            ]),
          ),
        ),
      ),
    );
  }
}

class ErrorScreen extends StatelessWidget {
  const ErrorScreen({super.key, required this.message, this.onRetry, this.onSignOut});
  final String message;
  final Future<void> Function()? onRetry;
  final Future<void> Function()? onSignOut;

  @override
  Widget build(BuildContext context) {
    return AppScaffold(
      title: '잠깐, 문제가 생겼어요',
      subtitle: '네트워크와 계정 상태를 확인해 주세요.',
      onSignOut: onSignOut,
      child: BrandPanel(children: [
        BrandNotice(text: message, kind: NoticeKind.error),
        if (onRetry != null) Padding(padding: const EdgeInsets.only(top: 16), child: OutlinedButton(onPressed: onRetry, child: const Text('다시 시도'))),
      ]),
    );
  }
}

class _BalanceCard extends StatelessWidget {
  const _BalanceCard({required this.name});
  final String name;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(22),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(30),
        gradient: const LinearGradient(colors: [Color(0xFFFF8A1F), Color(0xFFFFB12A)], begin: Alignment.topLeft, end: Alignment.bottomRight),
        boxShadow: const [BoxShadow(color: Color(0x33FF7A1A), blurRadius: 22, offset: Offset(0, 12))],
      ),
      child: Stack(children: [
        const Positioned(right: 0, top: 0, child: SnackMascot(size: 72, light: true)),
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6), decoration: BoxDecoration(color: Colors.white24, borderRadius: BorderRadius.circular(999)), child: const Text('LUNCH WALLET', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 12))),
          const SizedBox(height: 18),
          Text('$name님 남은 식대', style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          const Text('191,000원', style: TextStyle(color: Colors.white, fontSize: 38, fontWeight: FontWeight.w900)),
          const SizedBox(height: 14),
          const Text('중식 진행중 · 1식 한도 10,000원', style: TextStyle(color: Color(0xFFFFF8E8), fontWeight: FontWeight.w800)),
        ]),
      ]),
    );
  }
}

class PaymentCompletePreview extends StatelessWidget {
  const PaymentCompletePreview({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: kOrange,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Container(
              padding: const EdgeInsets.all(28),
              decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(34), boxShadow: const [BoxShadow(color: Color(0x33000000), blurRadius: 26, offset: Offset(0, 16))]),
              child: const Column(mainAxisSize: MainAxisSize.min, children: [
                SnackMascot(size: 104),
                SizedBox(height: 18),
                Text('결제완료', style: TextStyle(color: kInk, fontSize: 36, fontWeight: FontWeight.w900)),
                SizedBox(height: 10),
                Text('든든 김치찌개', style: TextStyle(color: Color(0xFF7A5637), fontSize: 22, fontWeight: FontWeight.w800)),
                SizedBox(height: 6),
                Text('9,000원', style: TextStyle(color: kOrange, fontSize: 50, fontWeight: FontWeight.w900)),
                SizedBox(height: 14),
                Text('거래번호 123456 · 서버시각 표시 예정', textAlign: TextAlign.center, style: TextStyle(color: Color(0xFF8B6544), fontWeight: FontWeight.w700)),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

class BrandBackground extends StatelessWidget {
  const BrandBackground({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        gradient: LinearGradient(colors: [Color(0xFFFFF4D9), Color(0xFFFFF9EE), Color(0xFFFFE5B7)], begin: Alignment.topLeft, end: Alignment.bottomRight),
      ),
      child: Stack(children: [
        Positioned(top: -70, right: -45, child: _Blob(size: 180, color: kTangerine.withValues(alpha: .35))),
        Positioned(bottom: -80, left: -60, child: _Blob(size: 210, color: kOrange.withValues(alpha: .16))),
        child,
      ]),
    );
  }
}

class _Blob extends StatelessWidget {
  const _Blob({required this.size, required this.color});
  final double size;
  final Color color;
  @override
  Widget build(BuildContext context) => Container(width: size, height: size, decoration: BoxDecoration(color: color, shape: BoxShape.circle));
}

BoxDecoration brandCardDecoration({double radius = 26}) => BoxDecoration(
  color: kCard,
  borderRadius: BorderRadius.circular(radius),
  border: Border.all(color: kLine, width: 1.4),
  boxShadow: const [BoxShadow(color: Color(0x1AFF8A1F), blurRadius: 24, offset: Offset(0, 14))],
);

class BrandLogo extends StatelessWidget {
  const BrandLogo({super.key, this.compact = false});
  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Row(children: [
      SnackMascot(size: compact ? 42 : 54),
      const SizedBox(width: 10),
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('그린잇', style: TextStyle(fontSize: compact ? 22 : 27, fontWeight: FontWeight.w900, color: kCocoa, letterSpacing: -.8)),
        if (!compact) const Text('회사 식대가 맛있어지는 시간', style: TextStyle(color: Color(0xFF8B6544), fontWeight: FontWeight.w800)),
      ]),
    ]);
  }
}

class SnackMascot extends StatelessWidget {
  const SnackMascot({super.key, this.size = 72, this.light = false});
  final double size;
  final bool light;

  @override
  Widget build(BuildContext context) {
    final face = light ? Colors.white : kTangerine;
    return SizedBox(
      width: size,
      height: size,
      child: Stack(alignment: Alignment.center, children: [
        Container(width: size, height: size * .78, decoration: BoxDecoration(color: face, borderRadius: BorderRadius.circular(size * .22), border: Border.all(color: light ? Colors.white : kCocoa, width: size * .045))),
        Positioned(top: size * .05, child: Container(width: size * .52, height: size * .18, decoration: BoxDecoration(color: light ? const Color(0xFFFFE7B2) : kOrange, borderRadius: BorderRadius.circular(999)))),
        Positioned(left: size * .30, top: size * .38, child: _Dot(size: size * .075, color: kCocoa)),
        Positioned(right: size * .30, top: size * .38, child: _Dot(size: size * .075, color: kCocoa)),
        Positioned(bottom: size * .22, child: Container(width: size * .26, height: size * .08, decoration: BoxDecoration(color: kCocoa, borderRadius: BorderRadius.circular(999)))),
      ]),
    );
  }
}

class _Dot extends StatelessWidget {
  const _Dot({required this.size, required this.color});
  final double size;
  final Color color;
  @override
  Widget build(BuildContext context) => Container(width: size, height: size, decoration: BoxDecoration(color: color, shape: BoxShape.circle));
}

class _SnackHero extends StatelessWidget {
  const _SnackHero({required this.signupMode});
  final bool signupMode;

  @override
  Widget build(BuildContext context) {
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const SnackMascot(size: 84),
      const SizedBox(width: 14),
      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5), decoration: BoxDecoration(color: const Color(0xFFFFEDD0), borderRadius: BorderRadius.circular(999)), child: const Text('TODAY BOX', style: TextStyle(color: kOrange, fontSize: 12, fontWeight: FontWeight.w900))),
        const SizedBox(height: 8),
        Text(signupMode ? '직원 계정을 만들어요' : '출출할 땐 바로 결제', style: const TextStyle(fontSize: 26, height: 1.04, fontWeight: FontWeight.w900)),
        const SizedBox(height: 6),
        Text(signupMode ? '초대코드와 승인만 끝나면 회사 식대를 사용할 수 있어요.' : '회사 식대 포인트로 주변 식당에서 간편하게 결제하세요.', style: const TextStyle(color: Color(0xFF7A5637), fontWeight: FontWeight.w700)),
      ])),
    ]);
  }
}

class BrandPanel extends StatelessWidget {
  const BrandPanel({super.key, required this.children});
  final List<Widget> children;
  @override
  Widget build(BuildContext context) => Container(padding: const EdgeInsets.all(20), decoration: brandCardDecoration(), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children));
}

enum NoticeKind { error, success }

class BrandNotice extends StatelessWidget {
  const BrandNotice({super.key, required this.text, required this.kind});
  final String text;
  final NoticeKind kind;
  @override
  Widget build(BuildContext context) {
    final isError = kind == NoticeKind.error;
    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(color: isError ? const Color(0xFFFFE8E0) : const Color(0xFFE7F8EE), borderRadius: BorderRadius.circular(16), border: Border.all(color: isError ? const Color(0xFFFFB49A) : const Color(0xFFB9E9CC))),
      child: Text(text, style: TextStyle(color: isError ? const Color(0xFFB42318) : const Color(0xFF047857), fontWeight: FontWeight.w800)),
    );
  }
}

class MiniSnackRow extends StatelessWidget {
  const MiniSnackRow({super.key});
  @override
  Widget build(BuildContext context) {
    return const Row(children: [
      _EmojiChip(emoji: '🍱', label: '점심'),
      SizedBox(width: 8),
      _EmojiChip(emoji: '🥪', label: '간식'),
      SizedBox(width: 8),
      _EmojiChip(emoji: '☕', label: '카페'),
    ]);
  }
}

class _EmojiChip extends StatelessWidget {
  const _EmojiChip({required this.emoji, required this.label});
  final String emoji;
  final String label;
  @override
  Widget build(BuildContext context) => Expanded(child: Container(padding: const EdgeInsets.symmetric(vertical: 12), decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(18), border: Border.all(color: kLine)), child: Column(children: [Text(emoji, style: const TextStyle(fontSize: 24)), const SizedBox(height: 4), Text(label, style: const TextStyle(fontWeight: FontWeight.w900, color: kCocoa))])));
}

class _QuickAction extends StatelessWidget {
  const _QuickAction({required this.icon, required this.label, required this.color, required this.onTap});
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => InkWell(onTap: onTap, borderRadius: BorderRadius.circular(24), child: Container(padding: const EdgeInsets.all(18), decoration: brandCardDecoration(radius: 24), child: Column(children: [Icon(icon, color: color, size: 34), const SizedBox(height: 8), Text(label, style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16))])));
}

class SectionHeader extends StatelessWidget {
  const SectionHeader({super.key, required this.title, required this.action});
  final String title;
  final String action;
  @override
  Widget build(BuildContext context) => Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w900)), Text(action, style: const TextStyle(color: kOrange, fontWeight: FontWeight.w900))]);
}

class _HistoryTile extends StatelessWidget {
  const _HistoryTile({required this.title, required this.meta, required this.price, required this.emoji});
  final String title;
  final String meta;
  final String price;
  final String emoji;
  @override
  Widget build(BuildContext context) => Container(margin: const EdgeInsets.only(bottom: 10), padding: const EdgeInsets.all(14), decoration: brandCardDecoration(radius: 22), child: Row(children: [Text(emoji, style: const TextStyle(fontSize: 30)), const SizedBox(width: 12), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: const TextStyle(fontWeight: FontWeight.w900)), Text(meta, style: const TextStyle(color: Color(0xFF8B6544), fontWeight: FontWeight.w700))])), Text(price, style: const TextStyle(fontWeight: FontWeight.w900, color: kCocoa))]));
}

class BrandLoadingScreen extends StatelessWidget {
  const BrandLoadingScreen({super.key});
  @override
  Widget build(BuildContext context) => const BrandBackground(child: Scaffold(backgroundColor: Colors.transparent, body: Center(child: Column(mainAxisSize: MainAxisSize.min, children: [SnackMascot(size: 90), SizedBox(height: 18), CircularProgressIndicator(color: kOrange)]))));
}
