---
name: android-app
extends: project
status: active
---

# Project Profile: Android App

Kotlin (preferred) or Java projects targeting Android. Build via Gradle / Android Studio.

## Auto-detection signals

- `build.gradle` / `build.gradle.kts`
- `AndroidManifest.xml`
- `.kt` / `.java` source files in Android project layout
- Operator mentions "Android app" / "Kotlin project"

## Phase customizations

### Phase 1 Intake
- Test command: `./gradlew test`
- Build: `./gradlew assembleDebug` / `assembleRelease`
- Distribution: Play Store, internal testing, APK direct

### Phase 2 Design
- Jetpack Compose (preferred new) vs XML layouts (legacy)
- Architecture: MVVM / MVI with ViewModel + StateFlow
- DI: Hilt / Koin

### Phase 4 Build
- Kotlin / Coroutines / Flow patterns
- Compose UI patterns
- Tools: Android Studio CLI tools, ktlint, detekt

### Phase 6 Test
- JUnit (unit)
- Espresso / Compose Testing (UI)
- Visual regression: Paparazzi (Square's Compose-friendly)
- Accessibility: Accessibility Scanner
- Multiple device profiles + Android version targets

### Phase 8 Release
- Play Store: fastlane supply for upload
- Internal testing track first
- Review Play guidelines for new APIs / permissions
- Crashlytics setup verified

## Specialists most active

- backend-engineer (Kotlin work)
- frontend-engineer (Compose)
- ui-engineer
- test-engineer
- devops-engineer (fastlane / Play Console)

## Android-specific concerns

- Foreground service permissions (newer Android tightens these)
- Background work via WorkManager
- Push: FCM
- Manifest permissions audit (don't request what you don't need)
- Target SDK / minimum SDK strategy
