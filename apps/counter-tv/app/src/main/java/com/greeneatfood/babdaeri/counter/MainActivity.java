package com.greeneatfood.babdaeri.counter;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.provider.Settings;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.Toast;

/**
 * 밥대리 카운터 for Google TV / Android TV.
 *
 * One screen: the counter web page, full screen. No address bar, the screen
 * stays on, the scan chime plays without a tap, and a lost connection retries
 * by itself. The page is the live web page, so web changes need no new APK.
 */
public class MainActivity extends Activity {
    static final String COUNTER_URL = "https://greeneatgo.vercel.app/counter";
    private static final String HOME_HOST = "greeneatgo.vercel.app";
    private static final long RETRY_MS = 8000;
    private static final long EXIT_WINDOW_MS = 2500;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private FrameLayout root;
    private WebView web;
    private TextView notice;
    private boolean failed;
    private long lastBackAt;

    private final Runnable retry = () -> {
        if (web != null) {
            failed = false;
            web.loadUrl(COUNTER_URL);
        }
    };

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(10, 13, 20));
        setContentView(root);

        notice = new TextView(this);
        notice.setTextColor(Color.WHITE);
        notice.setTextSize(22);
        notice.setGravity(Gravity.CENTER);
        notice.setLineSpacing(0, 1.4f);
        notice.setBackgroundColor(Color.rgb(10, 13, 20));
        notice.setVisibility(View.GONE);

        createWebView();
        root.addView(notice, match());
        if (state == null || web.restoreState(state) == null) {
            web.loadUrl(COUNTER_URL);
        }
        AutoStart.startWakeService(this);
        askAutoStartOnce();
    }

    /**
     * Opening by itself when the TV is switched on needs the "다른 앱 위에 표시"
     * permission. Asked once; the counter works the same without it.
     */
    private void askAutoStartOnce() {
        if (AutoStart.allowed(this)) return;
        final SharedPreferences prefs = getSharedPreferences("counter", MODE_PRIVATE);
        if (prefs.getBoolean("autostart_asked", false)) return;
        prefs.edit().putBoolean("autostart_asked", true).apply();
        new AlertDialog.Builder(this)
                .setTitle("TV를 켜면 자동으로 열까요?")
                .setMessage("다음 화면에서 '밥대리 카운터'의 '다른 앱 위에 표시'를 허용하면, TV를 켤 때 카운터가 바로 열려요.\n\n"
                        + "나중에 하려면: TV 설정 → 앱 → 특수 앱 액세스 → 다른 앱 위에 표시")
                .setPositiveButton("설정 열기", (dialog, which) -> openOverlaySettings())
                .setNegativeButton("나중에", null)
                .show();
    }

    private void openOverlaySettings() {
        Intent[] candidates = {
                new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:" + getPackageName())),
                new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION),
                new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + getPackageName())),
        };
        for (Intent intent : candidates) {
            try {
                startActivity(intent);
                return;
            } catch (RuntimeException notOnThisDevice) {
                // Try the next screen: TV builds do not all have the same settings pages.
            }
        }
        Toast.makeText(this, "TV 설정 → 앱 → 특수 앱 액세스 → 다른 앱 위에 표시에서 허용해 주세요", Toast.LENGTH_LONG).show();
    }

    private static FrameLayout.LayoutParams match() {
        return new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void createWebView() {
        web = new WebView(this);
        web.setBackgroundColor(Color.rgb(10, 13, 20));
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);          // keeps the counter login
        settings.setMediaPlaybackRequiresUserGesture(false);  // scan chime without a tap
        settings.setSupportMultipleWindows(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        // Lets the page know it runs inside this app (screen is kept on natively).
        settings.setUserAgentString(settings.getUserAgentString() + " BapdaeriCounterTV/" + BuildConfig.VERSION_NAME);
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                // Stay on the counter site over https; nothing else opens in this app.
                return !("https".equals(uri.getScheme()) && HOME_HOST.equals(uri.getHost()));
            }

            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                failed = false;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (!failed) {
                    notice.setVisibility(View.GONE);
                    view.requestFocus();
                }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (!request.isForMainFrame()) return;
                failed = true;
                showNotice("인터넷에 연결하지 못했어요\n연결되면 자동으로 다시 열려요");
                handler.removeCallbacks(retry);
                handler.postDelayed(retry, RETRY_MS);
            }

            @Override
            public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
                // The page's process was killed (low memory): rebuild it instead of crashing.
                root.removeView(web);
                web.destroy();
                createWebView();
                web.loadUrl(COUNTER_URL);
                return true;
            }
        });
        web.setFocusable(true);
        web.setFocusableInTouchMode(true);
        root.addView(web, 0, match());
        web.requestFocus();
    }

    private void showNotice(String text) {
        notice.setText(text);
        notice.setVisibility(View.VISIBLE);
    }

    private void immersive() {
        View decor = getWindow().getDecorView();
        decor.setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            immersive();
            if (web != null) web.requestFocus();   // scanner keys go to the page
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (web != null) {
            web.onResume();
            web.resumeTimers();
        }
    }

    @Override
    protected void onPause() {
        if (web != null) web.onPause();
        super.onPause();
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        if (web != null) web.saveState(out);
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        if (web != null) {
            root.removeView(web);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }

    /** Back never leaves by accident: twice within a moment to close the app. */
    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            long now = System.currentTimeMillis();
            if (now - lastBackAt < EXIT_WINDOW_MS) {
                finish();
            } else {
                lastBackAt = now;
                Toast.makeText(this, "한 번 더 누르면 카운터를 닫아요", Toast.LENGTH_SHORT).show();
            }
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }
}
