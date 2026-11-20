import 'package:flutter/material.dart';

import 'theme/app_colors.dart';

/// One restaurant the buyer can use (`GET /restaurants`).
class Restaurant {
  const Restaurant({
    required this.id,
    required this.name,
    this.address = '',
    this.category = '',
    this.voucherBalance = 0,
    this.voucherPrice,
  });

  factory Restaurant.fromJson(Map<String, dynamic> json) => Restaurant(
        id: '${json['id'] ?? ''}',
        name: '${json['name'] ?? ''}'.trim(),
        address: '${json['address'] ?? ''}'.trim(),
        category: '${json['category'] ?? ''}'.trim(),
        voucherBalance: (json['voucher_balance'] as num?)?.round() ?? 0,
        voucherPrice: (json['voucher_price'] as num?)?.round(),
      );

  final String id;
  final String name;
  final String address;
  final String category;
  final int voucherBalance;
  final int? voucherPrice;

  /// "address · 식권 8,000원" (parts that are missing are left out).
  String get subtitle => [
        if (address.isNotEmpty) address,
        if (voucherPrice != null) '식권 ${_won(voucherPrice!)}',
      ].join(' · ');
}

List<Restaurant> restaurantsFromResponse(Map<String, dynamic> data) {
  final items = data['items'];
  if (items is! List) return const [];
  return items
      .whereType<Map>()
      .map((item) => Restaurant.fromJson(item.cast<String, dynamic>()))
      .where((restaurant) => restaurant.id.isNotEmpty && restaurant.name.isNotEmpty)
      .toList();
}

/// The restaurant every screen is showing: the saved choice when it is still in
/// the list, otherwise the first one (the server sorts held vouchers first).
Restaurant? pickRestaurant(List<Restaurant> restaurants, String? savedId) {
  if (restaurants.isEmpty) return null;
  for (final restaurant in restaurants) {
    if (restaurant.id == savedId) return restaurant;
  }
  return restaurants.first;
}

String _won(int value) =>
    '${value.toString().replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+(?!\d))'), (match) => '${match[1]},')}원';

/// Shares the restaurant list and the current choice with the purchase and QR
/// pages, which are built outside the dashboard shell.
class RestaurantScope extends InheritedWidget {
  const RestaurantScope({
    super.key,
    required this.restaurants,
    required this.selected,
    required this.onPick,
    required super.child,
  });

  final List<Restaurant> restaurants;
  final Restaurant? selected;

  /// Opens the restaurant picker.
  final VoidCallback onPick;

  static RestaurantScope? maybeOf(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<RestaurantScope>();

  @override
  bool updateShouldNotify(RestaurantScope oldWidget) =>
      oldWidget.restaurants != restaurants || oldWidget.selected != selected;
}

/// Home: which restaurant the wallet, menu and notices belong to. The change
/// button is always there, also while only one restaurant exists.
class RestaurantBar extends StatelessWidget {
  const RestaurantBar({super.key, required this.restaurant, required this.onPick});

  final Restaurant restaurant;
  final VoidCallback onPick;

  @override
  Widget build(BuildContext context) => Material(
        color: AppColors.card,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: AppColors.line),
        ),
        child: InkWell(
          key: const ValueKey('restaurant-bar'),
          borderRadius: BorderRadius.circular(16),
          onTap: onPick,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 11, 12, 11),
            child: Row(children: [
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                    color: AppColors.cardHi,
                    borderRadius: BorderRadius.circular(10)),
                child: const Icon(Icons.storefront_rounded,
                    color: AppColors.blueSoft, size: 18),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(restaurant.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            color: AppColors.fg,
                            fontSize: 15,
                            fontWeight: FontWeight.w700)),
                    if (restaurant.subtitle.isNotEmpty)
                      Text(restaurant.subtitle,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              color: AppColors.fg2, fontSize: 12)),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              const Text('식당 변경',
                  style: TextStyle(
                      color: AppColors.blueSoft,
                      fontSize: 13,
                      fontWeight: FontWeight.w700)),
              const Icon(Icons.expand_more_rounded,
                  color: AppColors.blueSoft, size: 18),
            ]),
          ),
        ),
      );
}

/// Purchase: which restaurant's vouchers are being bought.
class RestaurantPurchaseChip extends StatelessWidget {
  const RestaurantPurchaseChip({super.key});

  @override
  Widget build(BuildContext context) {
    final scope = RestaurantScope.maybeOf(context);
    final restaurant = scope?.selected;
    if (scope == null || restaurant == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 4, 18, 6),
      child: Row(children: [
        Flexible(
          child: Material(
            color: AppColors.paper,
            shape: const StadiumBorder(),
            child: InkWell(
              key: const ValueKey('restaurant-purchase-chip'),
              customBorder: const StadiumBorder(),
              onTap: scope.onPick,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(12, 7, 8, 7),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  const Icon(Icons.storefront_rounded,
                      color: AppColors.ink, size: 16),
                  const SizedBox(width: 6),
                  Flexible(
                    child: Text(restaurant.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            color: AppColors.ink,
                            fontSize: 13.5,
                            fontWeight: FontWeight.w700)),
                  ),
                  const Icon(Icons.expand_more_rounded,
                      color: AppColors.ink, size: 18),
                ]),
              ),
            ),
          ),
        ),
        const SizedBox(width: 10),
        const Text('이 식당에서만 쓸 수 있어요',
            style: TextStyle(color: AppColors.fg2, fontSize: 12.5)),
      ]),
    );
  }
}

/// QR: one QR for every restaurant; the list shows what is held where.
class RestaurantBalanceList extends StatelessWidget {
  const RestaurantBalanceList({super.key});

  @override
  Widget build(BuildContext context) {
    final held = (RestaurantScope.maybeOf(context)?.restaurants ?? const [])
        .where((restaurant) => restaurant.voucherBalance > 0)
        .toList();
    if (held.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Container(
        key: const ValueKey('restaurant-balance-list'),
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.line),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (var i = 0; i < held.length; i++) ...[
              if (i != 0) const Divider(height: 16, color: AppColors.lineSoft),
              Row(children: [
                Expanded(
                  child: Text(held[i].name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          color: AppColors.fg, fontSize: 14)),
                ),
                Text('${held[i].voucherBalance}장',
                    style: const TextStyle(
                        color: AppColors.flipDigit,
                        fontSize: 15,
                        fontWeight: FontWeight.w800)),
              ]),
            ],
            const SizedBox(height: 10),
            const Text('찍은 식당의 식권이 1장 사용돼요. 식권이 없는 식당에서는 사용되지 않아요.',
                style: TextStyle(
                    color: AppColors.fg2, fontSize: 12, height: 1.45)),
          ],
        ),
      ),
    );
  }
}

/// Bottom sheet "식당 고르기": restaurants with held vouchers first, the rest
/// below, narrowed by a name/area search. Returns the chosen restaurant.
Future<Restaurant?> showRestaurantPicker(
  BuildContext context, {
  required List<Restaurant> restaurants,
  required String? selectedId,
}) =>
    showModalBottomSheet<Restaurant>(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF0F1524),
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(26))),
      builder: (_) =>
          _RestaurantPicker(restaurants: restaurants, selectedId: selectedId),
    );

class _RestaurantPicker extends StatefulWidget {
  const _RestaurantPicker({required this.restaurants, required this.selectedId});
  final List<Restaurant> restaurants;
  final String? selectedId;

  @override
  State<_RestaurantPicker> createState() => _RestaurantPickerState();
}

class _RestaurantPickerState extends State<_RestaurantPicker> {
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final query = _query.trim().toLowerCase();
    final matches = widget.restaurants
        .where((restaurant) =>
            query.isEmpty ||
            restaurant.name.toLowerCase().contains(query) ||
            restaurant.address.toLowerCase().contains(query) ||
            restaurant.category.toLowerCase().contains(query))
        .toList();
    final held = matches.where((r) => r.voucherBalance > 0).toList();
    final others = matches.where((r) => r.voucherBalance <= 0).toList();
    return DefaultTextStyle.merge(
      style: const TextStyle(fontFamily: 'Pretendard'),
      child: Padding(
        padding: EdgeInsets.only(
            bottom: MediaQuery.of(context).viewInsets.bottom),
        child: SafeArea(
          top: false,
          child: ConstrainedBox(
            constraints: BoxConstraints(
                maxHeight: MediaQuery.of(context).size.height * 0.8),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(18, 12, 18, 12),
              child: Column(
                key: const ValueKey('restaurant-picker'),
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Center(
                    child: Container(
                      width: 42,
                      height: 4,
                      margin: const EdgeInsets.only(bottom: 14),
                      decoration: BoxDecoration(
                          color: const Color(0xFF33405C),
                          borderRadius: BorderRadius.circular(9)),
                    ),
                  ),
                  const Text('식당 고르기',
                      style: TextStyle(
                          color: AppColors.fg,
                          fontSize: 19,
                          fontWeight: FontWeight.w800)),
                  const SizedBox(height: 12),
                  TextField(
                    key: const ValueKey('restaurant-search'),
                    onChanged: (value) => setState(() => _query = value),
                    style: const TextStyle(
                        color: AppColors.fg,
                        fontFamily: 'Pretendard',
                        fontSize: 15),
                    cursorColor: AppColors.blueSoft,
                    decoration: InputDecoration(
                      hintText: '식당 이름이나 동네로 찾기',
                      hintStyle: const TextStyle(
                          color: Color(0xFF66728A), fontFamily: 'Pretendard'),
                      prefixIcon: const Icon(Icons.search_rounded,
                          color: AppColors.fg2, size: 20),
                      filled: true,
                      fillColor: AppColors.card,
                      isDense: true,
                      contentPadding: const EdgeInsets.symmetric(vertical: 12),
                      enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(14),
                          borderSide:
                              const BorderSide(color: AppColors.line)),
                      focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(14),
                          borderSide:
                              const BorderSide(color: AppColors.blue)),
                    ),
                  ),
                  Flexible(
                    child: ListView(
                      shrinkWrap: true,
                      padding: const EdgeInsets.only(top: 4),
                      children: [
                        if (matches.isEmpty)
                          const Padding(
                            padding: EdgeInsets.symmetric(vertical: 28),
                            child: Center(
                              child: Text('찾는 식당이 없어요.',
                                  style: TextStyle(
                                      color: AppColors.fg2, fontSize: 14)),
                            ),
                          ),
                        if (held.isNotEmpty) const _PickerGroup('내 식권이 있는 식당'),
                        for (final restaurant in held) _row(restaurant),
                        if (others.isNotEmpty)
                          _PickerGroup(held.isEmpty ? '식당' : '다른 식당'),
                        for (final restaurant in others) _row(restaurant),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _row(Restaurant restaurant) {
    final selected = restaurant.id == widget.selectedId;
    final details = [
      if (restaurant.address.isNotEmpty) restaurant.address,
      if (restaurant.category.isNotEmpty) restaurant.category,
      if (restaurant.voucherBalance <= 0 && restaurant.voucherPrice != null)
        '식권 ${_won(restaurant.voucherPrice!)}',
    ].join(' · ');
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: selected ? const Color(0xFF141E3A) : AppColors.card,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(color: selected ? AppColors.blue : AppColors.line),
        ),
        child: InkWell(
          key: ValueKey('restaurant-option-${restaurant.id}'),
          borderRadius: BorderRadius.circular(16),
          onTap: () => Navigator.of(context).pop(restaurant),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                    color: AppColors.cardHi,
                    borderRadius: BorderRadius.circular(13)),
                child: const Icon(Icons.restaurant_rounded,
                    color: AppColors.blueSoft, size: 20),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(restaurant.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            color: AppColors.fg,
                            fontSize: 15,
                            fontWeight: FontWeight.w700)),
                    if (details.isNotEmpty)
                      Text(details,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              color: AppColors.fg2, fontSize: 12)),
                  ],
                ),
              ),
              const SizedBox(width: 10),
              if (restaurant.voucherBalance > 0)
                Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Text('${restaurant.voucherBalance}장',
                      style: const TextStyle(
                          color: AppColors.flipDigit,
                          fontSize: 15,
                          fontWeight: FontWeight.w800)),
                  const Text('보유',
                      style: TextStyle(color: AppColors.fg2, fontSize: 11.5)),
                ])
              else if (selected)
                const Icon(Icons.check_rounded,
                    color: AppColors.blueSoft, size: 20),
            ]),
          ),
        ),
      ),
    );
  }
}

class _PickerGroup extends StatelessWidget {
  const _PickerGroup(this.label);
  final String label;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 14, bottom: 8),
        child: Text(label,
            style: const TextStyle(
                color: AppColors.fg2,
                fontSize: 12,
                fontWeight: FontWeight.w700)),
      );
}
