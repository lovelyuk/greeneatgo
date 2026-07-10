import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:qr_code_scanner_plus/qr_code_scanner_plus.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:webview_flutter/webview_flutter.dart';

const supabaseUrl = String.fromEnvironment('SUPABASE_URL');
const supabaseAnonKey = String.fromEnvironment('SUPABASE_ANON_KEY');
const apiBaseUrl = String.fromEnvironment('API_BASE_URL');
const authEmailRedirectTo = String.fromEnvironment('AUTH_EMAIL_REDIRECT_TO', defaultValue: 'https://greeneatgo-api.onrender.com/v1/auth/confirmed');
const defaultMerchantQrToken = String.fromEnvironment('MERCHANT_QR_TOKEN', defaultValue: 'QR-PILOT-KIMCHI');

const kInk = Color(0xFF14351F);
const kCocoa = Color(0xFF1E5631);
const kOrange = Color(0xFF2FB865);
const kTangerine = Color(0xFF7BD88F);
const kCream = Color(0xFFF3FBF4);
const kCard = Color(0xFFFCFEFC);
const kMint = Color(0xFF15A05A);
const kLine = Color(0xFFCDEBD5);

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
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
          labelStyle: const TextStyle(color: Color(0xFF5C7A66), fontWeight: FontWeight.w700),
          hintStyle: const TextStyle(color: Color(0xFF9BB6A3)),
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
      builder: (context, child) {
        final mq = MediaQuery.of(context);
        // 기기 글꼴 크기 설정으로 UI가 과도하게 커지는 것을 방지 (최대 1.2배로 제한)
        return MediaQuery(
          data: mq.copyWith(textScaler: mq.textScaler.clamp(maxScaleFactor: 1.2)),
          child: child!,
        );
      },
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

  Future<Map<String, dynamic>> registerConsumer({required String displayName}) {
    return _request('/consumer/register', method: 'POST', body: {'display_name': displayName});
  }

  Future<Map<String, dynamic>> createTossOrder({required String qrToken, required MerchantProduct product}) {
    return _request('/toss/orders', method: 'POST', body: {'qr_token': qrToken, 'product_id': product.id});
  }

  Future<Map<String, dynamic>> confirmTossPayment({required String paymentKey, required String orderId, required int amount}) {
    return _request('/toss/confirm', method: 'POST', body: {'payment_key': paymentKey, 'order_id': orderId, 'amount': amount});
  }

  Future<Map<String, dynamic>> payProduct({required String qrToken, required MerchantProduct product}) {
    return _request('/pay', method: 'POST', body: {
      'qr_token': qrToken,
      'amount': product.price,
      'product_id': product.id,
      'idempotency_key': '${session.user.id}-${product.id}-${DateTime.now().millisecondsSinceEpoch}',
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


class MerchantProduct {
  MerchantProduct({required this.id, required this.name, required this.price, this.category});
  final String id;
  final String name;
  final int price;
  final String? category;

  factory MerchantProduct.fromJson(Map<String, dynamic> json) => MerchantProduct(
    id: json['id'] as String,
    name: json['name'] as String,
    price: json['price'] as int,
    category: json['category'] as String?,
  );
}

class TodayMenu {
  TodayMenu({required this.title, required this.menuText});
  final String title;
  final String menuText;

  factory TodayMenu.fromJson(Map<String, dynamic> json) => TodayMenu(
    title: json['title'] as String? ?? '오늘의 부페 메뉴',
    menuText: json['menu_text'] as String? ?? '',
  );
}

class MerchantMenu {
  MerchantMenu({required this.merchantName, required this.products, this.todayMenu});
  final String merchantName;
  final List<MerchantProduct> products;
  final TodayMenu? todayMenu;
}

class MenuClient {
  Future<MerchantMenu> getProducts(String qrToken) async {
    final uri = Uri.parse('$apiBaseUrl/merchants/$qrToken/products');
    final response = await http.get(uri);
    final decoded = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = decoded['detail'] as Map<String, dynamic>?;
      throw Exception(detail?['message'] ?? '상품 목록을 불러오지 못했어요');
    }
    final data = decoded['data'] as Map<String, dynamic>;
    final merchant = data['merchant'] as Map<String, dynamic>;
    final items = (data['items'] as List<dynamic>).cast<Map<String, dynamic>>();
    final todayMenuJson = data['today_menu'] as Map<String, dynamic>?;
    return MerchantMenu(
      merchantName: displayMerchantName(merchant['name'] as String?),
      products: items.map(MerchantProduct.fromJson).toList(),
      todayMenu: todayMenuJson == null ? null : TodayMenu.fromJson(todayMenuJson),
    );
  }
}

String won(num? value) => '${(value ?? 0).round().toString().replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+(?!\d))'), (m) => '${m[1]},')}원';

String shortKoreanDate(String? iso) {
  if (iso == null || iso.isEmpty) return '-';
  final date = DateTime.tryParse(iso)?.toLocal();
  if (date == null) return '-';
  return '${date.month}/${date.day} ${date.hour.toString().padLeft(2, '0')}:${date.minute.toString().padLeft(2, '0')}';
}

String recentMeta(Map<String, dynamic> tx) {
  final merchant = displayMerchantName(tx['merchant_name'] as String?);
  final date = shortKoreanDate(tx['created_at'] as String?);
  return '$merchant · $date';
}

String displayMerchantName(String? name) {
  final value = (name ?? '').trim();
  if (value.isEmpty || value == '밥장부 김치찌개' || value == '그린잇 식당') return '돈토';
  return value;
}

String? qrTokenFromScan(String raw) {
  final value = raw.trim();
  if (value.isEmpty) return null;
  final uri = Uri.tryParse(value);
  final qr = uri?.queryParameters['qr'];
  if (qr != null && qr.trim().isNotEmpty) return qr.trim();
  if (value.length <= 120 && !value.contains(' ')) return value;
  return null;
}

List<Map<String, dynamic>> mapList(dynamic value) {
  if (value is! List) return <Map<String, dynamic>>[];
  return value.whereType<Map>().map((item) => item.cast<String, dynamic>()).toList();
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
            const SizedBox(height: 56),
            const BrandTitle(height: 72, alignment: Alignment.center),
            const SizedBox(height: 44),
            Container(
              padding: const EdgeInsets.all(22),
              decoration: brandCardDecoration(radius: 30),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
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
                FilledButton(onPressed: _busy ? null : (_signupMode ? _signup : _login), child: Text(_busy ? '처리 중...' : (_signupMode ? '직원 계정 만들기' : '그린한 한 끼 시작하기'))),
                const SizedBox(height: 10),
                TextButton(onPressed: _busy ? null : _toggleMode, child: Text(_signupMode ? '이미 계정이 있어요' : '처음 사용하는 직원이에요')),
              ]),
            ),
            const SizedBox(height: 16),
            const Text('회원가입 후 회사 초대코드 입력과 관리자 승인을 거쳐 식대 사용이 가능해요.', textAlign: TextAlign.center, style: TextStyle(color: Color(0xFF5C7A66), fontSize: 13, height: 1.5, fontWeight: FontWeight.w700)),
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
  final _name = TextEditingController();
  final _code = TextEditingController();
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

  Future<void> _registerConsumer() async {
    final displayName = _name.text.trim();
    if (displayName.isEmpty) {
      setState(() => _error = '이름을 입력해 주세요.');
      return;
    }
    setState(() { _busy = true; _error = null; });
    try {
      await ApiClient(widget.session).registerConsumer(displayName: displayName);
      await widget.onSubmitted();
    } catch (error) {
      setState(() => _error = error.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final rejected = widget.me?['status'] == 'rejected';
    return AppScaffold(
      title: rejected ? '이용 유형을 다시 선택해요' : '이용 유형 선택',
      subtitle: '장부업체 직원은 초대코드로, 일반 사용자는 토스페이먼츠로 이용할 수 있어요.',
      onSignOut: widget.onSignOut,
      child: BrandPanel(children: [
        const MiniSnackRow(),
        const SizedBox(height: 20),
        TextField(controller: _name, decoration: const InputDecoration(labelText: '이름', prefixIcon: Icon(Icons.person_outline))),
        const SizedBox(height: 16),
        FilledButton.icon(onPressed: _busy ? null : _registerConsumer, icon: const Icon(Icons.credit_card_rounded), label: Text(_busy ? '처리 중...' : '일반 사용자로 시작하기')),
        const SizedBox(height: 10),
        const Text('상품 금액은 토스페이먼츠에서 직접 결제합니다.', textAlign: TextAlign.center, style: TextStyle(color: Color(0xFF5C7A66), fontWeight: FontWeight.w700)),
        const Padding(padding: EdgeInsets.symmetric(vertical: 18), child: Divider(color: kLine)),
        const Text('장부업체 직원', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
        const SizedBox(height: 10),
        TextField(controller: _code, decoration: const InputDecoration(labelText: '회사 초대코드', prefixIcon: Icon(Icons.confirmation_number_outlined))),
        if (_error != null) BrandNotice(text: _error!, kind: NoticeKind.error),
        const SizedBox(height: 16),
        OutlinedButton(onPressed: _busy ? null : _submit, child: Text(_busy ? '요청 중...' : '회사 장부 가입 요청')),
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
        const Center(child: SproutMark(size: 96)),
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
    final name = me['display_name'] as String? ?? '사용자';
    final isConsumer = me['role'] == 'customer';
    final monthUsed = (me['month_used'] as num?) ?? 0;
    final remainingLimit = (me['remaining_limit'] as num?) ?? 0;
    final recentTransactions = mapList(me['recent_transactions']);
    return AppScaffold(
      title: '오늘도 그린하게',
      subtitle: '$name님, 그린하게 챙기는 오늘 한 끼예요.',
      onSignOut: onSignOut,
      actions: [IconButton(onPressed: onRefresh, icon: const Icon(Icons.refresh_rounded))],
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        FutureBuilder<MerchantMenu>(
          future: MenuClient().getProducts(defaultMerchantQrToken),
          builder: (context, snapshot) => _TodayMenuCard(
            todayMenu: snapshot.data?.todayMenu,
            monthUsed: isConsumer ? null : monthUsed,
            remainingLimit: isConsumer ? null : remainingLimit,
            loading: snapshot.connectionState != ConnectionState.done,
            error: snapshot.hasError ? snapshot.error.toString().replaceFirst('Exception: ', '') : null,
          ),
        ),
        const SizedBox(height: 16),
        _QuickAction(icon: isConsumer ? Icons.credit_card_rounded : Icons.qr_code_scanner_rounded, label: isConsumer ? '상품 선택 · 토스 결제' : '돈토 상품 선택', color: kOrange, onTap: () async {
          await Navigator.of(context).push(MaterialPageRoute(builder: (_) => ProductSelectionScreen(session: Supabase.instance.client.auth.currentSession!, isConsumer: isConsumer)));
          await onRefresh();
        }),
        const SizedBox(height: 24),
        const SectionHeader(title: '최근 이용', action: ''),
        const SizedBox(height: 10),
        if (recentTransactions.isEmpty)
          const _EmptyHistoryCard()
        else
          ...recentTransactions.map((tx) => _HistoryTile(
            title: tx['title'] as String? ?? '식대 사용',
            meta: recentMeta(tx),
            price: '-${won(tx['amount'] as num?)}',
            emoji: '🍽️',
          )),
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
              const BrandTitle(height: 30),
              const SizedBox(height: 18),
              Text(title, style: const TextStyle(fontSize: 31, height: 1.08, fontWeight: FontWeight.w900, color: kInk)),
              if (subtitle != null) ...[
                const SizedBox(height: 8),
                Text(subtitle!, style: const TextStyle(fontSize: 15, color: Color(0xFF5C7A66), fontWeight: FontWeight.w700)),
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

class _TodayMenuCard extends StatelessWidget {
  const _TodayMenuCard({required this.todayMenu, required this.monthUsed, required this.remainingLimit, this.loading = false, this.error});
  final TodayMenu? todayMenu;
  final num? monthUsed;
  final num? remainingLimit;
  final bool loading;
  final String? error;

  @override
  Widget build(BuildContext context) {
    final hasMenu = todayMenu != null && todayMenu!.menuText.trim().isNotEmpty;
    final title = loading
        ? '오늘 부페 메뉴 불러오는 중'
        : hasMenu
            ? todayMenu!.title
            : '오늘 등록된 부페 메뉴가 없어요';
    final body = error != null
        ? '메뉴 정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.'
        : loading
            ? '식당관리자가 입력한 오늘 메뉴를 확인하고 있어요.'
            : hasMenu
                ? todayMenu!.menuText
                : '식당관리자가 오늘 메뉴를 등록하면 여기에 표시돼요.';
    return Container(
      padding: const EdgeInsets.all(22),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(30),
        gradient: const LinearGradient(colors: [Color(0xFF2FB865), Color(0xFF7BD88F)], begin: Alignment.topLeft, end: Alignment.bottomRight),
        boxShadow: const [BoxShadow(color: Color(0x332FB865), blurRadius: 22, offset: Offset(0, 12))],
      ),
      child: Stack(children: [
        const Positioned(right: 0, bottom: 0, child: SproutMark(size: 72, light: true)),
        if (monthUsed != null && remainingLimit != null) Positioned(
          right: 0,
          top: 0,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(color: Colors.white24, borderRadius: BorderRadius.circular(18)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              const Text('이번달 사용', style: TextStyle(color: Color(0xFFEAFBF0), fontSize: 11, fontWeight: FontWeight.w900)),
              Text(won(monthUsed), style: const TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w900)),
              const SizedBox(height: 3),
              const Text('남은 한도', style: TextStyle(color: Color(0xFFEAFBF0), fontSize: 11, fontWeight: FontWeight.w900)),
              Text(won(remainingLimit), style: const TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w900)),
            ]),
          ),
        ),
        Padding(
          padding: EdgeInsets.only(right: monthUsed == null ? 74 : 118),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6), decoration: BoxDecoration(color: Colors.white24, borderRadius: BorderRadius.circular(999)), child: const Text('TODAY BUFFET', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 12))),
            const SizedBox(height: 18),
            Text(title, style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w900)),
            const SizedBox(height: 8),
            Text(body, style: const TextStyle(color: Color(0xFFEAFBF0), fontSize: 15, height: 1.45, fontWeight: FontWeight.w800)),
          ]),
        ),
      ]),
    );
  }
}

class ProductSelectionScreen extends StatefulWidget {
  const ProductSelectionScreen({super.key, required this.session, required this.isConsumer});
  final Session session;
  final bool isConsumer;

  @override
  State<ProductSelectionScreen> createState() => _ProductSelectionScreenState();
}

class _ProductSelectionScreenState extends State<ProductSelectionScreen> {
  late final Future<MerchantMenu> _menu = MenuClient().getProducts(defaultMerchantQrToken);

  @override
  Widget build(BuildContext context) {
    return AppScaffold(
      title: '상품을 선택해요',
      subtitle: widget.isConsumer
          ? '식당 상품을 고른 뒤 토스페이먼츠에서 직접 결제합니다.'
          : '금액 입력 없이 식당에서 등록한 상품 중 하나를 골라 결제합니다.',
      child: FutureBuilder<MerchantMenu>(
        future: _menu,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const BrandPanel(children: [Center(child: CircularProgressIndicator())]);
          }
          if (snapshot.hasError) {
            return BrandPanel(children: [BrandNotice(text: snapshot.error.toString().replaceFirst('Exception: ', ''), kind: NoticeKind.error)]);
          }
          final menu = snapshot.data!;
          if (menu.products.isEmpty) {
            return const BrandPanel(children: [BrandNotice(text: '식당관리자 페이지에 등록된 메뉴가 없어요.', kind: NoticeKind.error)]);
          }
          return BrandPanel(children: [
            if (menu.todayMenu != null && menu.todayMenu!.menuText.isNotEmpty) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(color: const Color(0xFFEAF7EC), borderRadius: BorderRadius.circular(20), border: Border.all(color: kLine)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(menu.todayMenu!.title, style: const TextStyle(color: kCocoa, fontSize: 17, fontWeight: FontWeight.w900)),
                  const SizedBox(height: 8),
                  Text(menu.todayMenu!.menuText, style: const TextStyle(color: Color(0xFF5C7A66), fontSize: 15, height: 1.45, fontWeight: FontWeight.w800)),
                ]),
              ),
            ],
            const SizedBox(height: 14),
            ...menu.products.map((product) => Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: InkWell(
                onTap: () async {
                  final paid = await Navigator.of(context).push<bool>(MaterialPageRoute(
                    builder: (_) => widget.isConsumer
                        ? TossPaymentScreen(session: widget.session, product: product, qrToken: defaultMerchantQrToken)
                        : QrScanPaymentScreen(session: widget.session, product: product),
                  ));
                  if (!context.mounted) return;
                  if (paid == true) Navigator.of(context).pop(true);
                },
                borderRadius: BorderRadius.circular(20),
                child: Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20), border: Border.all(color: kLine)),
                  child: Row(children: [
                    Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(product.name, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
                      const SizedBox(height: 4),
                      Text(product.category ?? '그린잇 메뉴', style: const TextStyle(color: Color(0xFF5C7A66), fontWeight: FontWeight.w800)),
                    ])),
                    Text(won(product.price), style: const TextStyle(color: kOrange, fontSize: 20, fontWeight: FontWeight.w900)),
                  ]),
                ),
              ),
            )),
          ]);
        },
      ),
    );
  }
}

class TossPaymentScreen extends StatefulWidget {
  const TossPaymentScreen({super.key, required this.session, required this.product, required this.qrToken});
  final Session session;
  final MerchantProduct product;
  final String qrToken;

  @override
  State<TossPaymentScreen> createState() => _TossPaymentScreenState();
}

class _TossPaymentScreenState extends State<TossPaymentScreen> {
  late final WebViewController _controller;
  bool _loading = true;
  bool _confirming = false;
  bool _completed = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(NavigationDelegate(
        onPageFinished: (_) { if (mounted) setState(() => _loading = false); },
        onWebResourceError: (error) {
          if (error.isForMainFrame == true && mounted) setState(() { _loading = false; _error = '결제화면을 불러오지 못했어요: ${error.description}'; });
        },
        onNavigationRequest: _onNavigationRequest,
      ));
    _createOrder();
  }

  Future<void> _createOrder() async {
    setState(() { _loading = true; _error = null; });
    try {
      final order = await ApiClient(widget.session).createTossOrder(qrToken: widget.qrToken, product: widget.product);
      await _controller.loadRequest(Uri.parse(order['checkout_url'] as String));
    } catch (error) {
      if (mounted) setState(() { _loading = false; _error = error.toString().replaceFirst('Exception: ', ''); });
    }
  }

  FutureOr<NavigationDecision> _onNavigationRequest(NavigationRequest request) async {
    final uri = Uri.parse(request.url);
    if (uri.path.endsWith('/toss/redirect/success')) {
      await _confirm(uri);
      return NavigationDecision.prevent;
    }
    if (uri.path.endsWith('/toss/redirect/fail')) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = uri.queryParameters['message'] ?? '결제가 취소되었어요.';
        });
      }
      return NavigationDecision.prevent;
    }
    if (uri.scheme != 'http' && uri.scheme != 'https') {
      final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (!opened && mounted) {
        setState(() => _error = '결제 앱을 열 수 없어요. 해당 앱이 설치되어 있는지 확인해 주세요.');
      }
      return NavigationDecision.prevent;
    }
    return NavigationDecision.navigate;
  }

  Future<void> _confirm(Uri uri) async {
    if (_confirming || _completed) return;
    final paymentKey = uri.queryParameters['paymentKey'];
    final orderId = uri.queryParameters['orderId'];
    final amount = int.tryParse(uri.queryParameters['amount'] ?? '');
    if (paymentKey == null || orderId == null || amount == null) {
      setState(() => _error = '결제 승인 정보가 올바르지 않아요.');
      return;
    }
    setState(() { _confirming = true; _loading = true; _error = null; });
    try {
      await ApiClient(widget.session).confirmTossPayment(paymentKey: paymentKey, orderId: orderId, amount: amount);
      if (mounted) setState(() { _completed = true; _loading = false; });
    } catch (error) {
      if (mounted) setState(() { _loading = false; _error = error.toString().replaceFirst('Exception: ', ''); });
    } finally {
      _confirming = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_completed) {
      return Scaffold(
        backgroundColor: kOrange,
        body: SafeArea(child: Center(child: Padding(
          padding: const EdgeInsets.all(24),
          child: Container(
            padding: const EdgeInsets.all(28),
            decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(34)),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.check_circle_rounded, color: kOrange, size: 104),
              const SizedBox(height: 18),
              const Text('결제완료', style: TextStyle(fontSize: 36, fontWeight: FontWeight.w900)),
              const SizedBox(height: 10),
              Text(widget.product.name, style: const TextStyle(color: Color(0xFF5C7A66), fontSize: 20, fontWeight: FontWeight.w800)),
              Text(won(widget.product.price), style: const TextStyle(color: kOrange, fontSize: 46, fontWeight: FontWeight.w900)),
              const SizedBox(height: 18),
              FilledButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('식당 이용하기')),
            ]),
          ),
        ))),
      );
    }
    return Scaffold(
      appBar: AppBar(title: Text('${widget.product.name} 결제')),
      body: Stack(children: [
        WebViewWidget(controller: _controller),
        if (_loading) const ColoredBox(color: kCream, child: Center(child: CircularProgressIndicator())),
        if (_error != null) ColoredBox(
          color: kCream,
          child: Center(child: Padding(
            padding: const EdgeInsets.all(24),
            child: BrandPanel(children: [
              BrandNotice(text: _error!, kind: NoticeKind.error),
              const SizedBox(height: 16),
              FilledButton(onPressed: _createOrder, child: const Text('다시 결제하기')),
              TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('상품 선택으로 돌아가기')),
            ]),
          )),
        ),
      ]),
    );
  }
}

class QrScanPaymentScreen extends StatefulWidget {
  const QrScanPaymentScreen({super.key, required this.session, required this.product});
  final Session session;
  final MerchantProduct product;

  @override
  State<QrScanPaymentScreen> createState() => _QrScanPaymentScreenState();
}

class _QrScanPaymentScreenState extends State<QrScanPaymentScreen> {
  final GlobalKey _qrKey = GlobalKey(debugLabel: 'GREENEAT_QR');
  QRViewController? _controller;
  StreamSubscription<Barcode>? _scanSubscription;
  bool _handled = false;
  String? _error;

  @override
  void dispose() {
    _scanSubscription?.cancel();
    super.dispose();
  }

  void _onQRViewCreated(QRViewController controller) {
    _controller = controller;
    _scanSubscription = controller.scannedDataStream.listen((scanData) {
      _handleRawScan(scanData.code);
    }, onError: (error) {
      if (!mounted) return;
      setState(() => _error = '카메라를 시작하지 못했어요: $error');
    });
  }

  void _onPermissionSet(QRViewController controller, bool granted) {
    if (!mounted || granted) return;
    setState(() => _error = '카메라 권한이 꺼져 있어요. 앱 설정에서 카메라 권한을 허용해 주세요.');
  }

  void _handleRawScan(String? raw) {
    if (_handled || raw == null) return;
    final token = qrTokenFromScan(raw);
    if (token == null) {
      setState(() => _error = '그린잇 결제 QR이 아니에요. 매장 QR을 다시 스캔해 주세요.');
      return;
    }
    _handled = true;
    _controller?.pauseCamera();
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => PaymentCompletePreview(session: widget.session, product: widget.product, qrToken: token)));
  }

  @override
  Widget build(BuildContext context) {
    return AppScaffold(
      title: '매장 QR을 스캔해요',
      subtitle: '${widget.product.name} · ${won(widget.product.price)}',
      child: BrandPanel(children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(24),
          child: SizedBox(
            height: 320,
            child: QRView(
              key: _qrKey,
              onQRViewCreated: _onQRViewCreated,
              onPermissionSet: _onPermissionSet,
              formatsAllowed: const [BarcodeFormat.qrcode],
              overlay: QrScannerOverlayShape(
                borderColor: kOrange,
                borderRadius: 18,
                borderLength: 28,
                borderWidth: 8,
                cutOutSize: 230,
              ),
            ),
          ),
        ),
        const SizedBox(height: 14),
        const Text('상품 선택 후 매장에 비치된 결제 QR을 스캔하면 결제가 진행됩니다.', textAlign: TextAlign.center, style: TextStyle(color: Color(0xFF5C7A66), fontWeight: FontWeight.w800, height: 1.45)),
        if (_error != null) ...[
          BrandNotice(text: _error!, kind: NoticeKind.error),
          OutlinedButton(onPressed: () {
            setState(() => _error = null);
            _controller?.resumeCamera();
          }, child: const Text('카메라 다시 켜기')),
        ],
      ]),
    );
  }
}

class PaymentCompletePreview extends StatefulWidget {
  const PaymentCompletePreview({super.key, required this.session, required this.product, required this.qrToken});
  final Session session;
  final MerchantProduct product;
  final String qrToken;

  @override
  State<PaymentCompletePreview> createState() => _PaymentCompletePreviewState();
}

class _PaymentCompletePreviewState extends State<PaymentCompletePreview> {
  late final Future<Map<String, dynamic>> _payment = ApiClient(widget.session).payProduct(qrToken: widget.qrToken, product: widget.product);

  @override
  Widget build(BuildContext context) {
    final priceText = won(widget.product.price);
    return Scaffold(
      backgroundColor: kOrange,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: FutureBuilder<Map<String, dynamic>>(
              future: _payment,
              builder: (context, snapshot) {
                final payment = snapshot.data?['payment'] as Map<String, dynamic>?;
                final merchant = snapshot.data?['merchant'] as Map<String, dynamic>?;
                final txCode = payment?['tx_code'] as String? ?? '-';
                final merchantName = displayMerchantName(merchant?['name'] as String?);
                final hasError = snapshot.hasError;
                final loading = snapshot.connectionState != ConnectionState.done;
                return Container(
                  padding: const EdgeInsets.all(28),
                  decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(34), boxShadow: const [BoxShadow(color: Color(0x33000000), blurRadius: 26, offset: Offset(0, 16))]),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    const SproutMark(size: 104),
                    const SizedBox(height: 18),
                    Text(loading ? '결제중' : hasError ? '결제실패' : '결제완료', style: const TextStyle(color: kInk, fontSize: 36, fontWeight: FontWeight.w900)),
                    const SizedBox(height: 10),
                    if (loading) const CircularProgressIndicator() else if (hasError) Text(snapshot.error.toString().replaceFirst('Exception: ', ''), textAlign: TextAlign.center, style: const TextStyle(color: Colors.red, fontWeight: FontWeight.w800)) else ...[
                      Text(widget.product.name, textAlign: TextAlign.center, style: const TextStyle(color: Color(0xFF5C7A66), fontSize: 22, fontWeight: FontWeight.w800)),
                      const SizedBox(height: 6),
                      Text(priceText, style: const TextStyle(color: kOrange, fontSize: 50, fontWeight: FontWeight.w900)),
                      const SizedBox(height: 14),
                      Text('$merchantName · 거래번호 $txCode', textAlign: TextAlign.center, style: const TextStyle(color: Color(0xFF5C7A66), fontWeight: FontWeight.w700)),
                    ],
                    const SizedBox(height: 18),
                    OutlinedButton(onPressed: loading ? null : () => Navigator.of(context).pop(!hasError), child: Text(hasError ? '다시 스캔하기' : '확인')),
                  ]),
                );
              },
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
        gradient: LinearGradient(colors: [Color(0xFFEAF7EC), Color(0xFFF3FBF4), Color(0xFFD9F0DE)], begin: Alignment.topLeft, end: Alignment.bottomRight),
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
  boxShadow: const [BoxShadow(color: Color(0x1A2FB865), blurRadius: 24, offset: Offset(0, 14))],
);

/// 좌측 정렬 브랜드 타이틀. 여러 화면에서 공통으로 사용한다.
/// assets/brand/greenit_title.png 가 있으면 그 이미지를, 없으면 워드마크 텍스트로 표시한다.
class BrandTitle extends StatelessWidget {
  const BrandTitle({super.key, this.height = 40, this.alignment = Alignment.centerLeft});
  final double height;
  final AlignmentGeometry alignment;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: alignment,
      child: Image.asset(
        'assets/brand/greenit_title.png',
        height: height,
        fit: BoxFit.contain,
        errorBuilder: (context, error, stackTrace) => Text(
          '그린잇',
          style: TextStyle(fontSize: height * 0.66, fontWeight: FontWeight.w900, color: kCocoa, letterSpacing: -1),
        ),
      ),
    );
  }
}

class SproutMark extends StatelessWidget {
  const SproutMark({super.key, this.size = 72, this.light = false});
  final double size;
  final bool light;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(
        painter: _SproutPainter(
          leaf: light ? Colors.white : kTangerine,
          leafDark: light ? const Color(0xFFEAFBF0) : kMint,
          stem: light ? Colors.white : kCocoa,
        ),
      ),
    );
  }
}

class _SproutPainter extends CustomPainter {
  _SproutPainter({required this.leaf, required this.leafDark, required this.stem});
  final Color leaf;
  final Color leafDark;
  final Color stem;

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;

    // 줄기: 아래에서 위로 살짝 뻗는 새싹 대
    final stemPaint = Paint()
      ..color = stem
      ..style = PaintingStyle.stroke
      ..strokeWidth = w * .085
      ..strokeCap = StrokeCap.round;
    final stemPath = Path()
      ..moveTo(w * .5, h * .93)
      ..quadraticBezierTo(w * .5, h * .62, w * .5, h * .40);
    canvas.drawPath(stemPath, stemPaint);

    // 오른쪽 잎 (짙은 톤)
    final rightLeaf = Paint()
      ..color = leafDark
      ..style = PaintingStyle.fill;
    final right = Path()
      ..moveTo(w * .5, h * .52)
      ..cubicTo(w * .75, h * .52, w * .97, h * .30, w * .90, h * .06)
      ..cubicTo(w * .66, h * .06, w * .50, h * .27, w * .5, h * .52)
      ..close();
    canvas.drawPath(right, rightLeaf);

    // 왼쪽 잎 (밝은 톤, 위에)
    final leftLeaf = Paint()
      ..color = leaf
      ..style = PaintingStyle.fill;
    final left = Path()
      ..moveTo(w * .5, h * .54)
      ..cubicTo(w * .25, h * .54, w * .03, h * .32, w * .10, h * .08)
      ..cubicTo(w * .34, h * .08, w * .50, h * .29, w * .5, h * .54)
      ..close();
    canvas.drawPath(left, leftLeaf);
  }

  @override
  bool shouldRepaint(covariant _SproutPainter old) =>
      old.leaf != leaf || old.leafDark != leafDark || old.stem != stem;
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
      _EmojiChip(emoji: '🥗', label: '샐러드'),
      SizedBox(width: 8),
      _EmojiChip(emoji: '🍱', label: '점심'),
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
  Widget build(BuildContext context) => Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
    Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
    if (action.isNotEmpty) Text(action, style: const TextStyle(color: kOrange, fontWeight: FontWeight.w900)),
  ]);
}

class _EmptyHistoryCard extends StatelessWidget {
  const _EmptyHistoryCard();

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 10),
    padding: const EdgeInsets.all(18),
    decoration: brandCardDecoration(radius: 22),
    child: const Row(children: [
      Icon(Icons.receipt_long_outlined, color: kOrange, size: 30),
      SizedBox(width: 12),
      Expanded(child: Text('이용내역이 없어요.', style: TextStyle(fontWeight: FontWeight.w900, color: Color(0xFF5C7A66)))),
    ]),
  );
}

class _HistoryTile extends StatelessWidget {
  const _HistoryTile({required this.title, required this.meta, required this.price, required this.emoji});
  final String title;
  final String meta;
  final String price;
  final String emoji;
  @override
  Widget build(BuildContext context) => Container(margin: const EdgeInsets.only(bottom: 10), padding: const EdgeInsets.all(14), decoration: brandCardDecoration(radius: 22), child: Row(children: [Text(emoji, style: const TextStyle(fontSize: 30)), const SizedBox(width: 12), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: const TextStyle(fontWeight: FontWeight.w900)), Text(meta, style: const TextStyle(color: Color(0xFF5C7A66), fontWeight: FontWeight.w700))])), Text(price, style: const TextStyle(fontWeight: FontWeight.w900, color: kCocoa))]));
}

class BrandLoadingScreen extends StatelessWidget {
  const BrandLoadingScreen({super.key});
  @override
  Widget build(BuildContext context) => BrandBackground(
    child: Scaffold(
      backgroundColor: Colors.transparent,
      body: Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Image.asset('assets/brand/title.png', width: 240, fit: BoxFit.contain),
          const SizedBox(height: 18),
          const CircularProgressIndicator(color: kOrange),
        ]),
      ),
    ),
  );
}
