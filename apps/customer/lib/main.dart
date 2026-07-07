import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';

const supabaseUrl = String.fromEnvironment('SUPABASE_URL');
const supabaseAnonKey = String.fromEnvironment('SUPABASE_ANON_KEY');
const apiBaseUrl = String.fromEnvironment('API_BASE_URL');

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (supabaseUrl.isNotEmpty && supabaseAnonKey.isNotEmpty) {
    await Supabase.initialize(url: supabaseUrl, anonKey: supabaseAnonKey);
  }
  runApp(const GreeneatGoApp());
}

class GreeneatGoApp extends StatelessWidget {
  const GreeneatGoApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '밥장부',
      theme: ThemeData(colorSchemeSeed: const Color(0xFF2F80ED), useMaterial3: true),
      home: const AppGate(),
    );
  }
}

class ApiClient {
  ApiClient(this.session);
  final Session session;

  Future<Map<String, dynamic>> getMe() async {
    return _request('/me');
  }

  Future<Map<String, dynamic>> requestJoin({required String inviteCode, required String displayName}) async {
    return _request('/join/request', method: 'POST', body: {
      'invite_code': inviteCode,
      'display_name': displayName,
    });
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
    if (_loading) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    if (_error != null && _session == null) return ErrorScreen(message: _error!);
    if (_session == null) return LoginScreen(onLoggedIn: _loadMe);
    if (_error != null) return ErrorScreen(message: _error!, onRetry: _loadMe, onSignOut: _signOut);

    final status = _me?['status'] as String? ?? 'no_profile';
    if (status == 'no_profile' || status == 'rejected') {
      return InviteCodeScreen(session: _session!, me: _me, onSubmitted: _loadMe, onSignOut: _signOut);
    }
    if (status == 'pending') {
      return PendingScreen(me: _me!, onRefresh: _loadMe, onSignOut: _signOut);
    }
    if (status != 'active') {
      return BlockedScreen(status: status, onRefresh: _loadMe, onSignOut: _signOut);
    }
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
        data: {'display_name': displayName},
      );
      if (response.session != null) {
        await widget.onLoggedIn();
      } else {
        setState(() {
          _signupMode = false;
          _info = '회원가입이 완료됐어요. 이메일 인증을 켠 경우 메일 확인 후 로그인해 주세요.';
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
    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: BoxConstraints(minHeight: MediaQuery.of(context).size.height - 48),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisAlignment: MainAxisAlignment.center, children: [
              const Text('밥장부', style: TextStyle(fontSize: 40, fontWeight: FontWeight.w900)),
              const SizedBox(height: 8),
              Text(_signupMode ? '직원 계정을 만들고 회사 초대코드로 가입 요청을 보내세요.' : '회사 식대 포인트로 주변 식당에서 간편하게 결제하세요.'),
              const SizedBox(height: 32),
              if (_signupMode) ...[
                TextField(controller: _displayName, textInputAction: TextInputAction.next, decoration: const InputDecoration(labelText: '이름', border: OutlineInputBorder())),
                const SizedBox(height: 12),
              ],
              TextField(controller: _email, keyboardType: TextInputType.emailAddress, textInputAction: TextInputAction.next, decoration: const InputDecoration(labelText: '이메일', border: OutlineInputBorder())),
              const SizedBox(height: 12),
              TextField(controller: _password, obscureText: true, textInputAction: _signupMode ? TextInputAction.next : TextInputAction.done, decoration: const InputDecoration(labelText: '비밀번호', border: OutlineInputBorder())),
              if (_signupMode) ...[
                const SizedBox(height: 12),
                TextField(controller: _passwordConfirm, obscureText: true, textInputAction: TextInputAction.done, decoration: const InputDecoration(labelText: '비밀번호 확인', border: OutlineInputBorder())),
              ],
              if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: const TextStyle(color: Colors.red))),
              if (_info != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_info!, style: const TextStyle(color: Color(0xFF047857)))),
              const SizedBox(height: 16),
              FilledButton(onPressed: _busy ? null : (_signupMode ? _signup : _login), child: Text(_busy ? '처리 중...' : (_signupMode ? '회원가입' : '로그인'))),
              const SizedBox(height: 8),
              TextButton(onPressed: _busy ? null : _toggleMode, child: Text(_signupMode ? '이미 계정이 있어요. 로그인' : '처음 사용하는 직원이에요. 회원가입')),
              const SizedBox(height: 8),
              const Text('회원가입 후 회사 초대코드 입력과 관리자 승인을 거쳐야 식대 사용이 가능해요.', style: TextStyle(fontSize: 12, color: Colors.grey)),
            ]),
          ),
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
      title: rejected ? '가입 요청이 거절됐어요' : '회사 초대코드 입력',
      onSignOut: widget.onSignOut,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(rejected ? '관리자에게 확인 후 다시 요청해 주세요.' : '회사에서 받은 초대코드를 입력하면 승인 대기 상태가 돼요.'),
        const SizedBox(height: 20),
        TextField(controller: _name, decoration: const InputDecoration(labelText: '이름', border: OutlineInputBorder())),
        const SizedBox(height: 12),
        TextField(controller: _code, decoration: const InputDecoration(labelText: '초대코드', border: OutlineInputBorder())),
        if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: const TextStyle(color: Colors.red))),
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
      title: '가입 승인 대기 중이에요',
      onSignOut: onSignOut,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        const Icon(Icons.hourglass_top, size: 72, color: Color(0xFF2F80ED)),
        const SizedBox(height: 16),
        Text('${me['display_name']}님의 가입 요청을 회사관리자에게 보냈어요.', textAlign: TextAlign.center),
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
      onSignOut: onSignOut,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('현재 상태: $status'),
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
    return AppScaffold(
      title: '밥장부',
      onSignOut: onSignOut,
      actions: [IconButton(onPressed: onRefresh, icon: const Icon(Icons.refresh))],
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        _BalanceCard(name: me['display_name'] as String? ?? '직원'),
        const SizedBox(height: 16),
        FilledButton.icon(
          onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const PaymentCompletePreview())),
          icon: const Icon(Icons.qr_code_scanner),
          label: const Text('QR 결제'),
        ),
        const SizedBox(height: 24),
        const Text('최근 내역', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
        const ListTile(title: Text('밥장부 김치찌개'), subtitle: Text('중식 · 12:21'), trailing: Text('-9,000원')),
      ]),
    );
  }
}

class AppScaffold extends StatelessWidget {
  const AppScaffold({super.key, required this.title, required this.child, this.onSignOut, this.actions = const []});
  final String title;
  final Widget child;
  final Future<void> Function()? onSignOut;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(title), actions: [...actions, if (onSignOut != null) IconButton(onPressed: onSignOut, icon: const Icon(Icons.logout))]),
      body: SafeArea(child: SingleChildScrollView(padding: const EdgeInsets.all(20), child: child)),
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
      title: '오류',
      onSignOut: onSignOut,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(message, style: const TextStyle(color: Colors.red)),
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
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('$name님 남은 식대', style: const TextStyle(fontSize: 16)),
          const SizedBox(height: 8),
          const Text('191,000원', style: TextStyle(fontSize: 34, fontWeight: FontWeight.w800)),
          const SizedBox(height: 8),
          const Text('중식 진행중 · 1식 한도 10,000원'),
        ]),
      ),
    );
  }
}

class PaymentCompletePreview extends StatelessWidget {
  const PaymentCompletePreview({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0E7A4F),
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: const [
              Icon(Icons.check_circle, color: Colors.white, size: 96),
              SizedBox(height: 24),
              Text('결제완료', style: TextStyle(color: Colors.white, fontSize: 38, fontWeight: FontWeight.bold)),
              SizedBox(height: 16),
              Text('밥장부 김치찌개', style: TextStyle(color: Colors.white, fontSize: 24)),
              SizedBox(height: 8),
              Text('9,000원', style: TextStyle(color: Colors.white, fontSize: 52, fontWeight: FontWeight.w900)),
              SizedBox(height: 16),
              Text('거래번호 123456 · 서버시각 표시 예정', style: TextStyle(color: Colors.white70, fontSize: 16)),
            ]),
          ),
        ),
      ),
    );
  }
}
