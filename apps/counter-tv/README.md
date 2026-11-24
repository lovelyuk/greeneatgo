# 밥대리 카운터 (Google TV / Android TV)

A one-screen TV app that opens `https://greeneatgo.vercel.app/counter` full screen:
no address bar, screen kept on, scan chime without a tap, automatic retry when the
connection drops, Back twice to close. The page is the live web page, so changes to
the counter screen need no new APK.

- App id `com.greeneatfood.babdaeri.counter`, shown on the TV home row (leanback banner).
- Signed with the customer app's upload key (`../customer/android/key.properties`, gitignored).
- Build on Windows: set `JAVA_HOME` to Android Studio's `jbr`, add `local.properties`
  with `sdk.dir=...`, then `gradlew.bat assembleRelease` →
  `app/build/outputs/apk/release/app-release.apk`.
- Raise `versionCode` in `app/build.gradle.kts` for every new build.

## Opening when the TV is switched on
`AutoStart` opens the counter after a boot (`BootReceiver`) and when the TV wakes from
standby (`WakeService`, a foreground service listening for the screen coming on).
Android lets an app open a screen from the background only when "다른 앱 위에 표시"
(`SYSTEM_ALERT_WINDOW`) is allowed for it: the app asks once at first launch, or run
`adb shell cmd appops set com.greeneatfood.babdaeri.counter SYSTEM_ALERT_WINDOW allow`.
Without it the home-row icon still works. `BOOT_COMPLETED` cannot be sent from `adb`
(protected broadcast), so test this by really switching the TV off and on.
