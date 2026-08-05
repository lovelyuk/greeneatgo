import 'package:flutter/material.dart';

abstract final class AppColors {
  // Dark navy authentication palette. Keep these names stable so later dark
  // theme stages can reuse the exact same values.
  static const navyBase = Color(0xFF0E1C2B);
  static const navySurface = Color(0xFF16293C);
  static const navySurfaceAlt = Color(0xFF14283A);
  static const navyBorder = Color(0xFF2A3B4F);
  static const navyBorderStrong = Color(0xFF3A4C61);
  static const limeGreen = Color(0xFF9DBF63);
  static const textOnLime = Color(0xFF0E1C2B);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF7B8FA5);
  static const textMuted = Color(0xFF6B819A);
  static const textPlaceholder = Color(0xFF4F6580);
  static const textLink = Color(0xFF8FA3B8);
  static const spinnerTrack = Color(0xFF25394E);

  static const bg = Color(0xFF0A0D14);
  static const card = Color(0xFF131A2A);
  static const cardHi = Color(0xFF1B2436);
  static const line = Color(0xFF212B3E);
  static const lineSoft = Color(0xFF161E2E);
  static const blue = Color(0xFF2C5FFF);
  static const blueSoft = Color(0xFF5B87FF);
  static const paper = Color(0xFFF4F1E9);
  static const ink = Color(0xFF131A2A);
  static const gold = Color(0xFFC9A227);
  static const fg = Color(0xFFFFFFFF);
  static const fg2 = Color(0xFF8A93A6);
  static const danger = Color(0xFFFF7A7A);
  static const paperMuted = Color(0xFFD8D5CC);
  static const ticketLine = Color(0xFFCFC7B4);
  static const ticketPurchase = Color(0xFFC64F00);
  static const timeline = Color(0xFF232D42);
  static const progressTrack = Color(0xFF202A3D);
  static const dinnerText = Color(0xFFA9B4CA);

  // SOL-style payment state surfaces.
  static const paymentBg = Color(0xFF0B111F);
  static const paymentSurface = Color(0xFF151D2F);
  static const paymentLine = Color(0x14FFFFFF);
  static const paymentPrimary = Color(0xFF0046FF);
  static const paymentPrimaryLight = Color(0xFF5B8CFF);
  static const paymentCream = Color(0xFFF4EFE1);
  static const paymentCreamDark = Color(0xFFEAE3D1);
  static const paymentCreamInk = Color(0xFF161B26);
  static const paymentMuted = Color(0xFF8A93A7);
  static const paymentDanger = Color(0xFFFF5F57);
}
