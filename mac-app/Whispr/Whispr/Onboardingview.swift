import SwiftUI
import AppKit

// =========================================================
// OnboardingView — multi-step guided tour
//
// Step 0: Welcome
// Step 1: Preferences (usage, career, style, language)
// Step 2: Guide — how to record (hotkeys + HUD)
// Step 3: Guide — Home & History
// Step 4: Guide — Dictionary
// Step 5: Guide — Snippets
// Step 6: All done
// =========================================================

struct OnboardingView: View {
    let onComplete: () -> Void

    @State private var step             : Int        = 0
    @State private var selectedUsage    : Set<String> = []
    @State private var selectedInterests: Set<String> = []
    @State private var writingStyle     : String     = "casual"
    @State private var language         : String     = "English"
    @State private var isSaving         : Bool       = false

    private let accent = Color(red: 0.498, green: 0.467, blue: 0.867)
    private var client: LocalBackendClient { AppManager.shared.localBackendClient }
    private let totalSteps = 7

    var body: some View {
        ZStack {
            Color(NSColor.windowBackgroundColor).ignoresSafeArea()

            VStack(spacing: 0) {
                // Progress dots
                HStack(spacing: 6) {
                    ForEach(0..<totalSteps, id: \.self) { i in
                        Circle()
                            .fill(i == step ? accent : Color.secondary.opacity(0.25))
                            .frame(width: i == step ? 8 : 6, height: i == step ? 8 : 6)
                            .animation(.easeInOut(duration: 0.2), value: step)
                    }
                }
                .padding(.top, 24)
                .padding(.bottom, 20)

                // Content
                Group {
                    switch step {
                    case 0: stepWelcome
                    case 1: stepPreferences
                    case 2: stepRecording
                    case 3: stepHomeHistory
                    case 4: stepDictionary
                    case 5: stepSnippets
                    default: stepDone
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)

                // Navigation
                HStack(spacing: 12) {
                    if step > 0 && step < totalSteps - 1 {
                        Button("Back") { withAnimation { step -= 1 } }
                            .buttonStyle(.plain)
                            .font(.system(size: 13))
                            .foregroundColor(.secondary)
                    }

                    Spacer()

                    if step == 0 {
                        Button("Skip setup") { saveAndFinish(skip: true) }
                            .buttonStyle(.plain)
                            .font(.system(size: 12))
                            .foregroundColor(.secondary)
                    }

                    if step < totalSteps - 1 {
                        Button(step == 1 ? "Save & Continue" : "Next") {
                            if step == 1 {
                                savePreferences { withAnimation { step += 1 } }
                            } else {
                                withAnimation { step += 1 }
                            }
                        }
                        .buttonStyle(.plain)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(.white)
                        .padding(.horizontal, 24)
                        .padding(.vertical, 10)
                        .background(isSaving ? accent.opacity(0.5) : accent)
                        .cornerRadius(10)
                        .disabled(isSaving)
                    } else {
                        Button("Get started") { saveAndFinish(skip: false) }
                            .buttonStyle(.plain)
                            .font(.system(size: 14, weight: .semibold))
                            .foregroundColor(.white)
                            .padding(.horizontal, 24)
                            .padding(.vertical, 10)
                            .background(accent)
                            .cornerRadius(10)
                    }
                }
                .padding(.horizontal, 40)
                .padding(.bottom, 28)
                .padding(.top, 16)
            }
        }
        .frame(width: 620, height: 700)
    }

    // =========================================================
    // Step 0 — Welcome
    // =========================================================

    private var stepWelcome: some View {
        VStack(spacing: 20) {
            Spacer()
            ZStack {
                RoundedRectangle(cornerRadius: 20)
                    .fill(accent)
                    .frame(width: 72, height: 72)
                Image(systemName: "mic.fill")
                    .font(.system(size: 32, weight: .semibold))
                    .foregroundColor(.white)
            }
            Text("Welcome to Whispr")
                .font(.system(size: 26, weight: .bold))
            Text("Whispr turns your voice into clean, formatted text — right where you're typing.\nThis quick tour will show you how everything works.")
                .font(.system(size: 14))
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 420)
            Spacer()
        }
        .padding(.horizontal, 40)
    }

    // =========================================================
    // Step 1 — Preferences
    // =========================================================

    private var stepPreferences: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Tell us about yourself")
                .font(.system(size: 20, weight: .bold))
                .padding(.horizontal, 40)

            Text("Whispr uses this to personalise transcription for you.")
                .font(.system(size: 13))
                .foregroundColor(.secondary)
                .padding(.horizontal, 40)
                .padding(.bottom, 8)

            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 20) {

                    VStack(alignment: .leading, spacing: 8) {
                        Label("I mainly use Whispr for", systemImage: "waveform")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(.secondary)
                            .textCase(.uppercase)
                            .tracking(0.4)
                        let cols = [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)]
                        LazyVGrid(columns: cols, spacing: 10) {
                            ForEach(usageOptions) { opt in
                                OnbPill(option: opt, selected: selectedUsage.contains(opt.label), accent: accent) {
                                    toggle(opt.label, in: &selectedUsage)
                                }
                            }
                        }
                    }

                    Divider()

                    VStack(alignment: .leading, spacing: 8) {
                        Label("My area of work", systemImage: "person.text.rectangle")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(.secondary)
                            .textCase(.uppercase)
                            .tracking(0.4)
                        let cols2 = [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)]
                        LazyVGrid(columns: cols2, spacing: 10) {
                            ForEach(interestOptions) { opt in
                                OnbPill(option: opt, selected: selectedInterests.contains(opt.label), accent: accent) {
                                    toggle(opt.label, in: &selectedInterests)
                                }
                            }
                        }
                    }

                    Divider()

                    HStack(alignment: .top, spacing: 24) {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Writing style")
                                .font(.system(size: 11, weight: .semibold))
                                .foregroundColor(.secondary)
                                .textCase(.uppercase)
                                .tracking(0.4)
                            HStack(spacing: 6) {
                                ForEach(["Casual", "Formal", "Technical"], id: \.self) { s in
                                    let on = writingStyle == s.lowercased()
                                    Button { writingStyle = s.lowercased() } label: {
                                        Text(s)
                                            .font(.system(size: 12, weight: on ? .semibold : .regular))
                                            .padding(.horizontal, 12).padding(.vertical, 6)
                                            .background(on ? accent.opacity(0.12) : Color.clear)
                                            .foregroundColor(on ? accent : .secondary)
                                            .cornerRadius(20)
                                            .overlay(RoundedRectangle(cornerRadius: 20)
                                                .stroke(on ? accent : Color.secondary.opacity(0.3),
                                                        lineWidth: on ? 1 : 0.5))
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                        }

                        Spacer()

                        VStack(alignment: .leading, spacing: 8) {
                            Text("Output language")
                                .font(.system(size: 11, weight: .semibold))
                                .foregroundColor(.secondary)
                                .textCase(.uppercase)
                                .tracking(0.4)
                            Picker("", selection: $language) {
                                ForEach(Config.supportedLanguages, id: \.self) { Text($0).tag($0) }
                            }
                            .pickerStyle(.menu).labelsHidden().frame(width: 140)
                        }
                    }
                }
                .padding(20)
                .background(
                    RoundedRectangle(cornerRadius: 12)
                        .fill(Color(NSColor.controlBackgroundColor))
                )
                .padding(.horizontal, 40)
            }
        }
    }

    // =========================================================
    // Step 2 — How to record
    // =========================================================

    private var stepRecording: some View {
        VStack(spacing: 28) {
            Spacer()
            VStack(spacing: 6) {
                Text("How to record")
                    .font(.system(size: 20, weight: .bold))
                Text("Whispr lives in your menu bar. Use these hotkeys from any app.")
                    .font(.system(size: 13)).foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
            }

            VStack(spacing: 12) {
                OnbGuideRow(
                    icon: "mic.fill",
                    iconColor: accent,
                    title: "Start recording",
                    detail: "Press ⌥ Space anywhere on your Mac. The floating indicator will appear at the bottom of your screen.",
                    badge: "⌥ Space"
                )
                OnbGuideRow(
                    icon: "stop.circle.fill",
                    iconColor: .red,
                    title: "Stop & transcribe",
                    detail: "Press ⌥ S to stop. Whispr cleans your speech and pastes it into the active app automatically.",
                    badge: "⌥ S"
                )
                OnbGuideRow(
                    icon: "menubar.rectangle",
                    iconColor: .secondary,
                    title: "Menu bar icon",
                    detail: "Click the Whispr icon in your menu bar to start/stop recording, change language, or open the main window.",
                    badge: nil
                )
            }
            .padding(.horizontal, 40)

            Spacer()
        }
    }

    // =========================================================
    // Step 3 — Home & History
    // =========================================================

    private var stepHomeHistory: some View {
        VStack(spacing: 28) {
            Spacer()
            VStack(spacing: 6) {
                Text("Home & History")
                    .font(.system(size: 20, weight: .bold))
                Text("Every transcription is saved so you can find it later.")
                    .font(.system(size: 13)).foregroundColor(.secondary)
            }

            VStack(spacing: 12) {
                OnbGuideRow(
                    icon: "house",
                    iconColor: accent,
                    title: "Home",
                    detail: "See your transcription stats, recent recordings, and quickly copy any past output.",
                    badge: nil
                )
                OnbGuideRow(
                    icon: "clock",
                    iconColor: accent,
                    title: "History",
                    detail: "Full list of all past recordings with the raw audio text and the cleaned output side by side. Searchable.",
                    badge: nil
                )
            }
            .padding(.horizontal, 40)

            Spacer()
        }
    }

    // =========================================================
    // Step 4 — Dictionary
    // =========================================================

    private var stepDictionary: some View {
        VStack(spacing: 28) {
            Spacer()
            VStack(spacing: 6) {
                Text("Personal Dictionary")
                    .font(.system(size: 20, weight: .bold))
                Text("Teach Whispr the words that matter to you.")
                    .font(.system(size: 13)).foregroundColor(.secondary)
            }

            VStack(spacing: 12) {
                OnbGuideRow(
                    icon: "book.closed",
                    iconColor: accent,
                    title: "Auto-learned terms",
                    detail: "Whispr automatically picks up recurring proper nouns, course codes, and brand names from your recordings.",
                    badge: "Auto"
                )
                OnbGuideRow(
                    icon: "plus.circle",
                    iconColor: .green,
                    title: "Add your own",
                    detail: "Go to Dictionary in the main window to add terms manually. Add aliases so Whispr knows how the speech model might mishear them.",
                    badge: nil
                )
                OnbGuideRow(
                    icon: "wand.and.stars",
                    iconColor: .orange,
                    title: "Update Dictionary",
                    detail: "Use \"Update Dictionary\" in the menu bar to run the AI learning on your recent recordings.",
                    badge: nil
                )
            }
            .padding(.horizontal, 40)

            Spacer()
        }
    }

    // =========================================================
    // Step 5 — Snippets
    // =========================================================

    private var stepSnippets: some View {
        VStack(spacing: 28) {
            Spacer()
            VStack(spacing: 6) {
                Text("Voice Snippets")
                    .font(.system(size: 20, weight: .bold))
                Text("Say a trigger word and Whispr expands it automatically.")
                    .font(.system(size: 13)).foregroundColor(.secondary)
            }

            VStack(spacing: 12) {
                OnbGuideRow(
                    icon: "text.bubble",
                    iconColor: accent,
                    title: "How it works",
                    detail: "Say \"zoom link\" → output becomes \"zoom link (https://zoom.us/j/...)\".\nThe trigger stays in the text and the expansion is appended in brackets.",
                    badge: nil
                )
                OnbGuideRow(
                    icon: "plus.circle",
                    iconColor: .green,
                    title: "Add a snippet",
                    detail: "Open Snippets in the main window. Add a trigger word and its expansion — your email, a meeting link, a common phrase.",
                    badge: nil
                )
            }
            .padding(.horizontal, 40)

            Spacer()
        }
    }

    // =========================================================
    // Step 6 — Done
    // =========================================================

    private var stepDone: some View {
        VStack(spacing: 20) {
            Spacer()
            ZStack {
                RoundedRectangle(cornerRadius: 20)
                    .fill(Color.green.opacity(0.15))
                    .frame(width: 72, height: 72)
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 40))
                    .foregroundColor(.green)
            }
            Text("You're all set!")
                .font(.system(size: 26, weight: .bold))
            Text("Press ⌥ Space anywhere to start your first recording.\nWhispr will paste the cleaned text into whatever app you're using.")
                .font(.system(size: 14))
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 420)
            Spacer()
        }
        .padding(.horizontal, 40)
    }

    // =========================================================
    // Helpers
    // =========================================================

    private let usageOptions: [OnbOption] = [
        .init(label: "Dictation / typing", icon: "keyboard"),
        .init(label: "Draft an email",     icon: "envelope"),
        .init(label: "Code comments",      icon: "chevron.left.forwardslash.chevron.right"),
        .init(label: "Meeting notes",      icon: "note.text"),
        .init(label: "Chat messages",      icon: "bubble.left"),
        .init(label: "Documents",          icon: "doc.text"),
        .init(label: "Academic writing",   icon: "graduationcap"),
        .init(label: "Personal notes",     icon: "pencil"),
    ]

    private let interestOptions: [OnbOption] = [
        .init(label: "Software / Tech", icon: "laptopcomputer"),
        .init(label: "Medicine",        icon: "cross.case"),
        .init(label: "Law",             icon: "building.columns"),
        .init(label: "Finance",         icon: "chart.line.uptrend.xyaxis"),
        .init(label: "Education",       icon: "books.vertical"),
        .init(label: "Design / Art",    icon: "paintbrush"),
        .init(label: "Research",        icon: "flask"),
        .init(label: "Business",        icon: "briefcase"),
    ]

    private func toggle(_ label: String, in set: inout Set<String>) {
        if set.contains(label) { set.remove(label) } else { set.insert(label) }
    }

    private func savePreferences(completion: @escaping () -> Void) {
        isSaving = true
        let profile: [String: Any] = [
            "usage_type":    Array(selectedUsage),
            "career_area":   selectedInterests.first ?? "",
            "primary_apps":  [] as [String],
            "writing_style": writingStyle,
            "language":      language,
        ]
        client.saveOnboardingProfile(profile) { _ in
            DispatchQueue.main.async {
                self.isSaving = false
                completion()
            }
        }
    }

    private func saveAndFinish(skip: Bool) {
        if skip {
            client.saveOnboardingProfile([:]) { _ in
                DispatchQueue.main.async { self.onComplete() }
            }
        } else {
            onComplete()
        }
    }
}

// =========================================================
// OnbGuideRow — icon + title + detail + optional badge
// =========================================================

private struct OnbGuideRow: View {
    let icon      : String
    let iconColor : Color
    let title     : String
    let detail    : String
    let badge     : String?

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            ZStack {
                RoundedRectangle(cornerRadius: 8)
                    .fill(iconColor.opacity(0.12))
                    .frame(width: 36, height: 36)
                Image(systemName: icon)
                    .font(.system(size: 16))
                    .foregroundColor(iconColor)
            }
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 8) {
                    Text(title)
                        .font(.system(size: 13, weight: .semibold))
                    if let badge {
                        Text(badge)
                            .font(.system(size: 11, design: .monospaced))
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(Color(NSColor.controlBackgroundColor))
                            .cornerRadius(4)
                            .overlay(RoundedRectangle(cornerRadius: 4)
                                .stroke(Color.secondary.opacity(0.3), lineWidth: 0.5))
                    }
                }
                Text(detail)
                    .font(.system(size: 12))
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
        }
        .padding(14)
        .background(Color(NSColor.controlBackgroundColor))
        .cornerRadius(10)
        .overlay(RoundedRectangle(cornerRadius: 10)
            .stroke(Color.secondary.opacity(0.15), lineWidth: 0.5))
    }
}

// =========================================================
// Shared components
// =========================================================

struct OnbOption: Identifiable {
    let id    = UUID()
    let label : String
    let icon  : String
}

struct OnbPill: View {
    let option   : OnbOption
    let selected : Bool
    let accent   : Color
    let action   : () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: option.icon).font(.system(size: 13)).frame(width: 18)
                Text(option.label)
                    .font(.system(size: 13, weight: selected ? .medium : .regular)).lineLimit(1)
                Spacer()
                if selected { Image(systemName: "checkmark").font(.system(size: 11, weight: .semibold)) }
            }
            .padding(.horizontal, 13).padding(.vertical, 10)
            .background(selected ? accent.opacity(0.10) : Color(NSColor.textBackgroundColor))
            .foregroundColor(selected ? accent : .primary)
            .cornerRadius(10)
            .overlay(RoundedRectangle(cornerRadius: 10)
                .stroke(selected ? accent : Color.secondary.opacity(0.2), lineWidth: selected ? 1 : 0.5))
        }
        .buttonStyle(.plain)
    }
}
