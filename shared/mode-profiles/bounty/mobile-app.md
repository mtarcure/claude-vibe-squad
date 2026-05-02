---
name: mobile-app
extends: bounty
status: active
---

# Bounty Profile: Mobile Application

iOS and Android bounties — deep-link handling, IPC, keychain/keystore, certificate pinning, root/jailbreak detection.

## Auto-detection signals

- Target is an iOS/Android app (App Store / Play Store URL)
- IPA / APK file in scope
- Bounty mentions "mobile app" / "iOS app" / "Android app"

## Phase customizations

### Phase 1 Intelligence
- Download IPA (if iOS, requires real device or sideload setup) or APK
- Static analysis target inventory (resources, assets, intent filters)

### Phase 2 Recon
- Tools: MobSF (Mobile Security Framework), Frida (dynamic), objection
- iOS: theos, IDA, Hopper, Frida + iOS-specific scripts
- Android: jadx, apktool, Frida, Drozer
- Map: deep-link schemes, content providers (Android), URL schemes (iOS), exported activities

### Phase 3 Threat Modeling
- Common mobile vuln classes:
  - Insecure data storage (keychain misuse, NSUserDefaults plaintext)
  - Insecure IPC (exported components without permissions)
  - Certificate pinning bypass
  - Deep-link injection
  - WebView injection
  - Backup-able sensitive data
  - Root/jailbreak detection bypass

### Phase 5/6/7 Exploitation
- Frida hooks for runtime testing
- Burp + mitmproxy (with cert pinning bypass) for network
- adb for Android dynamic testing
- iOS: requires jailbroken device or simulator (may limit certain tests)

### Phase 9 Validation
- Mobile CVSS often lower than equivalent web due to higher attack complexity
- Check program rubric for accepted classes (some exclude rooted-only attacks)

### Phase 10 Report
- Video PoC essential (mobile workflows are visual)
- Include device/OS version, install method, repro steps
- Frida scripts attached if used

## Specialists most active

- exploit-developer (multi-model)
- security-analyst (static analysis)
- scout (component discovery)
- skeptic (reproducibility check across device states)

## Tools-specific notes

- iOS testing typically requires real device (jailbroken or developer)
- Android: emulator + real device for full coverage
- Certificate pinning: Frida scripts well-known for popular apps
