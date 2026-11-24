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
