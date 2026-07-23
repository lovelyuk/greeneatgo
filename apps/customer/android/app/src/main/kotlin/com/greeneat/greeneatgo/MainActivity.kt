package com.greeneat.greeneatgo

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.util.Log
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    companion object {
        private const val MVACCINE_PACKAGE = "com.TouchEn.mVaccine.webs"
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "com.greeneat.greeneatgo/payment_app"
        ).setMethodCallHandler { call, result ->
            if (call.method != "openIntentUrl") {
                result.notImplemented()
                return@setMethodCallHandler
            }
            val url = call.argument<String>("url")
            if (url.isNullOrBlank()) {
                result.success("failed")
                return@setMethodCallHandler
            }
            result.success(openIntentUrl(url))
        }
    }

    private fun openIntentUrl(url: String): String {
        val normalizedUrl = if (url.startsWith("intent://mvaccine?") && !url.contains("#Intent;")) {
            "$url#Intent;scheme=mvaccine;package=com.TouchEn.mVaccine.webs;end"
        } else {
            url
        }
        val intent = try {
            Intent.parseUri(normalizedUrl, Intent.URI_INTENT_SCHEME).apply {
                addCategory(Intent.CATEGORY_BROWSABLE)
                component = null
                selector = null
            }
        } catch (_: Exception) {
            return "failed"
        }

        val isMVaccine = normalizedUrl.startsWith("intent://mvaccine?") ||
            intent.data?.scheme == "mvaccine"
        if (isMVaccine) intent.setPackage(MVACCINE_PACKAGE)
        Log.i(
            "GreenEatPaymentIntent",
            "scheme=${intent.data?.scheme}, host=${intent.data?.host}, " +
                "package=${intent.`package`}, hasIntentFragment=${url.contains("#Intent;")}"
        )

        return try {
            startActivity(intent)
            "app"
        } catch (_: ActivityNotFoundException) {
            val fallbackUrl = intent.getStringExtra("browser_fallback_url")
            if (!fallbackUrl.isNullOrBlank() &&
                (fallbackUrl.startsWith("https://") || fallbackUrl.startsWith("http://"))) {
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(fallbackUrl)))
                    "fallback"
                } catch (_: ActivityNotFoundException) {
                    "failed"
                }
            } else {
                val packageName = intent.`package` ?: return "failed"
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=$packageName")))
                    "fallback"
                } catch (_: ActivityNotFoundException) {
                    try {
                        startActivity(Intent(
                            Intent.ACTION_VIEW,
                            Uri.parse("https://play.google.com/store/apps/details?id=$packageName")
                        ))
                        "fallback"
                    } catch (_: ActivityNotFoundException) {
                        "failed"
                    }
                }
            }
        }
    }
}
