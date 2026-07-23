package com.greeneat.greeneatgo

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
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
                result.success(false)
                return@setMethodCallHandler
            }
            result.success(openIntentUrl(url))
        }
    }

    private fun openIntentUrl(url: String): Boolean {
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
            return false
        }

        return try {
            startActivity(intent)
            true
        } catch (_: ActivityNotFoundException) {
            val fallbackUrl = intent.getStringExtra("browser_fallback_url")
            if (!fallbackUrl.isNullOrBlank() &&
                (fallbackUrl.startsWith("https://") || fallbackUrl.startsWith("http://"))) {
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(fallbackUrl)))
                    true
                } catch (_: ActivityNotFoundException) {
                    false
                }
            } else {
                val packageName = intent.`package` ?: return false
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=$packageName")))
                    true
                } catch (_: ActivityNotFoundException) {
                    false
                }
            }
        }
    }
}
