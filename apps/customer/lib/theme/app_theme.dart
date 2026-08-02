import 'package:flutter/material.dart';

import 'app_colors.dart';

abstract final class AppTextStyles {
  static const ticketNumber = TextStyle(
    fontSize: 50,
    height: .95,
    fontWeight: FontWeight.w800,
    letterSpacing: -2.5,
    color: AppColors.ink,
  );
  static const screenTitle = TextStyle(
    fontSize: 20,
    height: 1.2,
    fontWeight: FontWeight.w800,
    letterSpacing: -.4,
    color: AppColors.fg,
  );
  static const heroNumber = TextStyle(
    fontSize: 32,
    height: 1.05,
    fontWeight: FontWeight.w800,
    letterSpacing: -.96,
    color: AppColors.fg,
  );
  static const cardTitle = TextStyle(
    fontSize: 15,
    fontWeight: FontWeight.w700,
    color: AppColors.fg,
  );
  static const body = TextStyle(
    fontSize: 14,
    fontWeight: FontWeight.w600,
    color: AppColors.fg,
  );
  static const caption = TextStyle(
    fontSize: 12,
    fontWeight: FontWeight.w600,
    color: AppColors.fg2,
  );
  static const overline = TextStyle(
    fontSize: 10.5,
    fontWeight: FontWeight.w800,
    letterSpacing: 2.1,
    color: AppColors.gold,
  );
}

abstract final class AppRadii {
  static const card = 22.0;
  static const button = 14.0;
  static const icon = 12.0;
}
