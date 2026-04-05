import AppKit
import SwiftUI
import Combine

// =========================================================
// MainWindowController
// Single persistent NSWindow with sidebar + content pane.
// =========================================================

final class MainWindowController: NSObject {
    static let shared = MainWindowController()

    private var window: NSWindow?
    @Published var selectedNav: NavItem = .home

    private override init() {}

    // MARK: - Show / hide

    func showWindow() {
        if let existing = window {
            existing.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        buildWindow()
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func navigate(to item: NavItem) {
        selectedNav = item
        showWindow()
    }

    // MARK: - Window construction

    private func buildWindow() {
        let splitVC = NSSplitViewController()
        splitVC.splitView.isVertical = true
        splitVC.splitView.dividerStyle = .thin

        let sidebarHost = NSHostingController(rootView: SidebarView(controller: self))
        let sidebarItem = NSSplitViewItem(sidebarWithViewController: sidebarHost)
        sidebarItem.minimumThickness = 220
        sidebarItem.maximumThickness = 220
        sidebarItem.canCollapse = false
        splitVC.addSplitViewItem(sidebarItem)

        let contentHost = NSHostingController(rootView: NavigationContentView(controller: self))
        let contentItem = NSSplitViewItem(viewController: contentHost)
        contentItem.minimumThickness = 480
        splitVC.addSplitViewItem(contentItem)

        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 980, height: 720),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        win.title = "Whispr"
        win.contentViewController = splitVC
        win.isReleasedWhenClosed = false
        win.minSize = NSSize(width: 820, height: 580)
        win.center()
        self.window = win
    }
}

// =========================================================
// Nav items
// =========================================================

enum NavItem: String, CaseIterable {
    case home       = "Home"
    case history    = "History"
    case dictionary = "Dictionary"
    case snippets   = "Snippets"

    var icon: String {
        switch self {
        case .home:       return "house"
        case .history:    return "clock"
        case .dictionary: return "book.closed"
        case .snippets:   return "text.bubble"
        }
    }
}

// =========================================================
// NavigationContentView — no backendClient args anywhere
// =========================================================

struct NavigationContentView: View {
    let controller: MainWindowController
    @State private var currentNav: NavItem = .home

    var body: some View {
        Group {
            switch currentNav {
            case .home:
                HomeView()                                                          // ← no args
            case .history:
                HistoryView(backendClient: AppManager.shared.localBackendClient)
            case .dictionary:
                DictionaryView(backendClient: AppManager.shared.localBackendClient)
            case .snippets:
                SnippetsView(backendClient: AppManager.shared.localBackendClient)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onReceive(controller.$selectedNav) { currentNav = $0 }
    }
}

// =========================================================
// SidebarView
// =========================================================

struct SidebarView: View {
    let controller: MainWindowController

    @State private var selectedNav      : NavItem = .home
    @State private var selectedLanguage : String  = Config.targetLanguage
    @State private var syncStatus       : String  = ""
    @State private var calendarEmail    : String  = "Not connected"

    private var backendClient: LocalBackendClient { AppManager.shared.localBackendClient }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {

            // ── Brand ─────────────────────────────────────────
            HStack(spacing: 10) {
                ZStack {
                    RoundedRectangle(cornerRadius: 7)
                        .fill(Color(red: 0.498, green: 0.467, blue: 0.867))
                        .frame(width: 28, height: 28)
                    Image(systemName: "mic.fill")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(.white)
                }
                Text("Whispr").font(.system(size: 15, weight: .medium))
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)

            Divider()

            // ── Nav ───────────────────────────────────────────
            VStack(alignment: .leading, spacing: 1) {
                Text("Menu")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundColor(.secondary)
                    .padding(.horizontal, 18)
                    .padding(.top, 12)
                    .padding(.bottom, 4)

                ForEach(NavItem.allCases, id: \.self) { item in
                    NavRow(item: item, isSelected: selectedNav == item) {
                        selectedNav = item
                        controller.navigate(to: item)
                    }
                }
            }

            Divider().padding(.top, 8)

            // ── Inline settings ───────────────────────────────
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 0) {

                    SettingsSection(title: "Hotkeys") {
                        HotkeyRow(label: "Start", keys: ["⌥", "Space"])
                        HotkeyRow(label: "Stop",  keys: ["⌥", "S"])
                    }

                    Divider().padding(.vertical, 10)

                    SettingsSection(title: "Output language") {
                        Picker("", selection: $selectedLanguage) {
                            ForEach(Config.supportedLanguages, id: \.self) { Text($0).tag($0) }
                        }
                        .pickerStyle(.menu)
                        .labelsHidden()
                        .onChange(of: selectedLanguage) { newValue in
                            Config.targetLanguage = newValue
                            syncStatus = "Saving..."
                            backendClient.syncLanguageToBackend { success in
                                syncStatus = success ? "Saved" : "Saved locally"
                                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { syncStatus = "" }
                            }
                        }
                        if !syncStatus.isEmpty {
                            Text(syncStatus).font(.caption2).foregroundColor(.secondary)
                        }
                    }

                    Divider().padding(.vertical, 10)

                    SettingsSection(title: "Google Calendar") {
                        HStack(spacing: 8) {
                            Circle()
                                .fill(calendarEmail == "Not connected" ? Color.gray : Color.green)
                                .frame(width: 7, height: 7)
                            Text(calendarEmail == "Not connected" ? "Not connected" : calendarEmail)
                                .font(.system(size: 12))
                                .foregroundColor(.secondary)
                                .lineLimit(1)
                                .truncationMode(.middle)
                        }
                        if calendarEmail == "Not connected" || calendarEmail == "Connecting..." {
                            Button("Connect") { connectCalendar() }
                                .buttonStyle(.borderedProminent)
                                .controlSize(.small)
                                .tint(Color(red: 0.498, green: 0.467, blue: 0.867))
                                .disabled(calendarEmail == "Connecting...")
                        } else {
                            HStack(spacing: 6) {
                                Button("Switch")     { connectCalendar() }.buttonStyle(.bordered).controlSize(.small)
                                Button("Disconnect") { disconnectCalendar() }
                                    .buttonStyle(.bordered).controlSize(.small).foregroundColor(.red)
                            }
                        }
                    }

                    Divider().padding(.vertical, 10)

                    VStack(alignment: .leading, spacing: 3) {
                        Text("Backend: local Python CLI")
                        Text("Recording: .wav file")
                        HStack(spacing: 4) {
                            Circle()
                                .fill(backendClient.isBackendAvailable ? Color.green : Color.red)
                                .frame(width: 6, height: 6)
                            Text(backendClient.isBackendAvailable ? "Available" : "Unavailable")
                        }
                    }
                    .font(.system(size: 10))
                    .foregroundColor(.secondary)
                    .padding(.horizontal, 14)
                    .padding(.bottom, 16)
                }
                .padding(.top, 10)
            }

            Spacer()
            Divider()

            VStack(alignment: .leading, spacing: 0) {
                SidebarBottomRow(icon: "questionmark.circle", label: "Help", isDestructive: false) {}
                SidebarBottomRow(icon: "power", label: "Quit Whispr", isDestructive: true) {
                    NSApp.terminate(nil)
                }
            }
            .padding(.vertical, 8)
        }
        .frame(width: 220)
        .background(Color(NSColor.controlBackgroundColor))
        .onAppear {
            loadCalendarEmail()
            backendClient.fetchLanguageFromBackend { lang in
                if let lang, Config.supportedLanguages.contains(lang) {
                    DispatchQueue.main.async {
                        selectedLanguage = lang
                        Config.targetLanguage = lang
                    }
                }
            }
        }
        .onReceive(controller.$selectedNav) { selectedNav = $0 }
    }

    private func loadCalendarEmail() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            backendClient.fetchCalendarEmail { email in
                DispatchQueue.main.async { calendarEmail = email ?? "Not connected" }
            }
        }
    }
    private func connectCalendar() {
        calendarEmail = "Connecting..."
        backendClient.connectGoogleCalendar { email in
            DispatchQueue.main.async { calendarEmail = email ?? "Not connected" }
        }
    }
    private func disconnectCalendar() {
        backendClient.disconnectGoogleCalendar { _ in
            DispatchQueue.main.async { calendarEmail = "Not connected" }
        }
    }
}

// =========================================================
// Sidebar sub-components
// =========================================================

struct NavRow: View {
    let item: NavItem; let isSelected: Bool; let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 9) {
                Image(systemName: item.icon).font(.system(size: 13)).frame(width: 16)
                Text(item.rawValue).font(.system(size: 13, weight: isSelected ? .medium : .regular))
                Spacer()
            }
            .foregroundColor(isSelected ? .primary : .secondary)
            .padding(.horizontal, 10).padding(.vertical, 7)
            .background(RoundedRectangle(cornerRadius: 6)
                .fill(isSelected ? Color(NSColor.selectedContentBackgroundColor).opacity(0.15) : Color.clear))
            .overlay(Rectangle().fill(Color(red: 0.498, green: 0.467, blue: 0.867))
                .frame(width: 2).opacity(isSelected ? 1 : 0), alignment: .leading)
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 8)
    }
}

struct SettingsSection<Content: View>: View {
    let title: String; @ViewBuilder let content: () -> Content
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(size: 10, weight: .medium)).foregroundColor(.secondary)
                .textCase(.uppercase).tracking(0.5).padding(.horizontal, 14)
            VStack(alignment: .leading, spacing: 4) { content() }.padding(.horizontal, 12)
        }
    }
}

struct HotkeyRow: View {
    let label: String; let keys: [String]
    var body: some View {
        HStack {
            Text(label).font(.system(size: 12))
            Spacer()
            HStack(spacing: 3) {
                ForEach(keys, id: \.self) { key in
                    Text(key).font(.system(size: 10, design: .monospaced))
                        .padding(.horizontal, 5).padding(.vertical, 2)
                        .background(Color(NSColor.controlBackgroundColor))
                        .overlay(RoundedRectangle(cornerRadius: 4)
                            .stroke(Color.secondary.opacity(0.3), lineWidth: 0.5))
                        .cornerRadius(4)
                }
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 7)
        .background(Color(NSColor.textBackgroundColor))
        .cornerRadius(6)
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.secondary.opacity(0.15), lineWidth: 0.5))
    }
}

struct SidebarBottomRow: View {
    let icon: String; let label: String; var isDestructive: Bool = false; let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 9) {
                Image(systemName: icon).font(.system(size: 12)).frame(width: 16)
                Text(label).font(.system(size: 12))
                Spacer()
            }
            .foregroundColor(isDestructive ? .red : .secondary)
            .padding(.horizontal, 18).padding(.vertical, 6)
        }
        .buttonStyle(.plain)
    }
}
