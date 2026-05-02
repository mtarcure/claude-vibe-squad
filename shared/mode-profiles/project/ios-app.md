---
name: ios-app
extends: project
status: active
---

# Project Profile: iOS App

Swift / SwiftUI projects targeting iOS, iPadOS, macOS (Catalyst), watchOS.

## Auto-detection signals

- Xcode project (`.xcodeproj`, `.xcworkspace`)
- `Package.swift` (Swift Package Manager)
- `.swift` source files
- Operator mentions "iOS app" / "Swift project"

## Phase customizations

### Phase 1 Intake
- Test command: `xcodebuild test -scheme <Scheme>` or via Xcode CLI
- Build: `xcodebuild build`
- Distribution: TestFlight / App Store / direct IPA

### Phase 2 Design
- architect + designer (Content cross-Lead) for UI work
- SwiftUI vs UIKit decision (mostly SwiftUI for new code)
- Navigation pattern (NavigationStack, TabView, etc.)
- State management (Observable, environment objects)

### Phase 4 Build
- backend-engineer (treat as ios-engineer for context — Swift/SwiftUI work)
- frontend-engineer (similarly contextualized for SwiftUI)
- Tools: Xcode CLI, swiftlint, swift-format

### Phase 6 Test
- XCTest (unit + integration)
- XCUITest (e2e UI)
- Visual regression: XCUITest screenshot diff
- Accessibility: Xcode's Accessibility Inspector + audit
- Real device + simulator (don't ship simulator-only tested)

### Phase 8 Release
- TestFlight build + submission OR App Store full submission
- Changelog in App Store release notes format
- App Store Connect via fastlane (preferred)
- Privacy nutrition labels updated

## Specialists most active

- backend-engineer (Swift work)
- frontend-engineer (SwiftUI)
- ui-engineer (visual fidelity)
- test-engineer (XCTest + XCUITest)
- devops-engineer (fastlane, App Store Connect)
- designer (Content cross-Lead)

## Distribution mechanisms

- TestFlight (beta) — fastlane pilot upload
- App Store (production) — fastlane deliver
- Ad-hoc (direct IPA) — fastlane match for signing

## iOS-specific concerns

- Certificate / profile management (fastlane match)
- App Store review guidelines compliance
- Privacy manifest (PrivacyInfo.xcprivacy) for SDKs
- Deep link / Universal Links setup
- Push notification provisioning if applicable
