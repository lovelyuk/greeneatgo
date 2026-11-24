package com.greeneatfood.babdaeri.counter;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.provider.Settings;

/**
 * Opens the counter when the TV is switched on.
 *
 * Two cases: a real boot (BootReceiver) and waking from standby, which is what
 * most TVs do on the power button (WakeService listens for the screen coming on).
 * Android only lets an app open a screen from the background when the user has
 * allowed "다른 앱 위에 표시" for it; without that this class does nothing.
 */
public final class AutoStart {
    private AutoStart() {}

    static boolean allowed(Context context) {
        return Settings.canDrawOverlays(context);
    }

    static void openCounter(Context context) {
        if (!allowed(context)) return;
        Intent intent = new Intent(context, MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
        try {
            context.startActivity(intent);
        } catch (RuntimeException ignored) {
            // Refused by the system: the home-row icon still works.
        }
    }

    static void startWakeService(Context context) {
        try {
            Intent service = new Intent(context, WakeService.class);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(service);
            } else {
                context.startService(service);
            }
        } catch (RuntimeException ignored) {
            // Not allowed right now (e.g. started from the background): try again at next launch.
        }
    }

    /** TV finished booting. */
    public static final class BootReceiver extends BroadcastReceiver {
        @Override
        public void onReceive(Context context, Intent intent) {
            startWakeService(context);
            openCounter(context);
        }
    }

    /** Stays alive so the counter comes back when the TV wakes from standby. */
    public static final class WakeService extends Service {
        private static final String CHANNEL = "counter_autostart";
        private final BroadcastReceiver screenOn = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                openCounter(context);
            }
        };
        private boolean registered;

        @Override
        public void onCreate() {
            super.onCreate();
            Notification.Builder builder;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                NotificationManager manager = getSystemService(NotificationManager.class);
                manager.createNotificationChannel(
                        new NotificationChannel(CHANNEL, "자동 실행", NotificationManager.IMPORTANCE_MIN));
                builder = new Notification.Builder(this, CHANNEL);
            } else {
                builder = new Notification.Builder(this);
            }
            Notification notification = builder
                    .setContentTitle("밥대리 카운터")
                    .setContentText("TV를 켜면 카운터가 열려요")
                    .setSmallIcon(android.R.drawable.ic_menu_view)
                    .setOngoing(true)
                    .build();
            try {
                if (Build.VERSION.SDK_INT >= 34) {
                    startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
                } else {
                    startForeground(1, notification);
                }
            } catch (RuntimeException refused) {
                stopSelf();
                return;
            }
            IntentFilter filter = new IntentFilter(Intent.ACTION_SCREEN_ON);
            filter.addAction(Intent.ACTION_DREAMING_STOPPED);   // screen saver ended
            filter.addAction(Intent.ACTION_USER_PRESENT);
            if (Build.VERSION.SDK_INT >= 33) {
                registerReceiver(screenOn, filter, Context.RECEIVER_NOT_EXPORTED);
            } else {
                registerReceiver(screenOn, filter);
            }
            registered = true;
        }

        @Override
        public int onStartCommand(Intent intent, int flags, int startId) {
            return START_STICKY;
        }

        @Override
        public void onDestroy() {
            if (registered) unregisterReceiver(screenOn);
            super.onDestroy();
        }

        @Override
        public IBinder onBind(Intent intent) {
            return null;
        }
    }
}
