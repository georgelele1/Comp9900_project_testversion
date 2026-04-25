import AppKit
import SwiftUI
import Combine

final class MainWindowController: NSObject, ObservableObject {
    static let shared = MainWindowController()

    private var window: NSWindow?
    @Published var selectedNav: NavItem = .home

    private override init() {}

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

    private func buildWindow() {
        let splitVC = NSSplitViewController()
        splitVC.splitView.isVertical = true
        splitVC.splitView.dividerStyle = .thin

        let sidebarItem = NSSplitViewItem(sidebarWithViewController:
            NSHostingController(rootView: SidebarView(controller: self)))
        sidebarItem.minimumThickness = 238
        sidebarItem.maximumThickness = 238
        sidebarItem.canCollapse = false
        splitVC.addSplitViewItem(sidebarItem)

        let contentItem = NSSplitViewItem(viewController:
            NSHostingController(rootView: NavigationContentView(controller: self)))
        contentItem.minimumThickness = 520
        splitVC.addSplitViewItem(contentItem)

        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1040, height: 740),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )

        win.title = "Whispr"
        win.contentViewController = splitVC
        win.isReleasedWhenClosed = false
        win.minSize = NSSize(width: 860, height: 600)
        win.center()
        window = win
    }
}

// MARK: - Nav

enum NavItem: String, CaseIterable {
    case home       = "Home"
    case history    = "History"
    case dictionary = "Dictionary"
    case snippets   = "Snippets"
    case shortcuts  = "Shortcuts"
    case apiKeys    = "API Keys"

    var icon: String {
        switch self {
        case .home:       return "house"
        case .history:    return "clock"
        case .dictionary: return "book.closed"
        case .snippets:   return "text.bubble"
        case .shortcuts:  return "keyboard"
        case .apiKeys:    return "key"
        }
    }

    var group: String {
        switch self {
        case .home, .history:
            return "Workspace"
        case .dictionary, .snippets:
            return "Personalisation"
        case .shortcuts, .apiKeys:
            return "Settings"
        }
    }
}

// MARK: - NavigationContentView

struct NavigationContentView: View {
    let controller: MainWindowController
    @State private var currentNav: NavItem = .home

    var body: some View {
        ZStack {
            WhisprTheme.appBackground

            Group {
                switch currentNav {
                case .home:
                    HomeView()
                case .history:
                    HistoryView(backendClient: AppManager.shared.localBackendClient)
                case .dictionary:
                    DictionaryView(backendClient: AppManager.shared.localBackendClient)
                case .snippets:
                    SnippetsView(backendClient: AppManager.shared.localBackendClient)
                case .shortcuts:
                    ShortcutsView()
                case .apiKeys:
                    APIKeysView(backendClient: AppManager.shared.localBackendClient)
                }
            }
            .padding(18)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onReceive(controller.$selectedNav) { currentNav = $0 }
        .withWhisprTour()
    }
}

// MARK: - SidebarView

struct SidebarView: View {
    let controller: MainWindowController

    @State private var selectedNav      : NavItem = .home
    @State private var selectedLanguage : String  = LanguageManager.shared.current
    @State private var syncStatus       : String  = ""
    @State private var activeModel      : String  = AppManager.shared.localBackendClient.activeModel

    @State private var clearingHistory    : ClearState = .idle
    @State private var clearingDictionary : ClearState = .idle
    @State private var clearingSnippets   : ClearState = .idle
    @State private var resettingProfile   : ClearState = .idle

    @State private var pendingClear   : DataClearAction? = nil
    @State private var showClearAlert : Bool = false

    private var backendClient: LocalBackendClient { AppManager.shared.localBackendClient }

    private var groupedNav: [(String, [NavItem])] {
        [
            ("Workspace", NavItem.allCases.filter { $0.group == "Workspace" }),
            ("Personalisation", NavItem.allCases.filter { $0.group == "Personalisation" }),
            ("Settings", NavItem.allCases.filter { $0.group == "Settings" })
        ]
    }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [
                    WhisprTheme.accent.opacity(0.20),
                    Color(NSColor.controlBackgroundColor)
                ],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 0) {

                brandHeader

                ScrollView(showsIndicators: false) {
                    VStack(alignment: .leading, spacing: 16) {
                        navMenu
                        modelCard
                        languageCard
                        dataManagementCard
                    }
                    .padding(.horizontal, 12)
                    .padding(.bottom, 12)
                }

                Spacer(minLength: 0)
                Divider()

                quitButton
            }
        }
        .frame(width: 238)
        .onAppear {
            backendClient.fetchLanguageFromBackend { lang in
                DispatchQueue.main.async {
                    LanguageManager.shared.syncFromBackend(lang)
                    selectedLanguage = LanguageManager.shared.current
                    MenuBarController.shared.refreshLanguageMenu()
                }
            }
        }
        .onReceive(controller.$selectedNav) { selectedNav = $0 }
        .onReceive(LanguageManager.shared.$current) { selectedLanguage = $0 }
        .onReceive(AppManager.shared.localBackendClient.$activeModel) { activeModel = $0 }
    }

    private var brandHeader: some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 13, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [WhisprTheme.accent, WhisprTheme.accent2],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 44, height: 44)

                Image(systemName: "mic.fill")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundColor(.white)
            }

            VStack(alignment: .leading, spacing: 3) {
                Text("Whispr")
                    .font(.system(size: 18, weight: .bold))

                Text("AI voice assistant")
                    .font(.system(size: 11))
                    .foregroundColor(.secondary)
            }

            Spacer()
        }
        .padding(14)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .stroke(Color.white.opacity(0.12), lineWidth: 0.8)
        )
        .padding(.horizontal, 12)
        .padding(.top, 14)
        .padding(.bottom, 12)
    }

    private var navMenu: some View {
        VStack(alignment: .leading, spacing: 14) {
            ForEach(groupedNav, id: \.0) { group, items in
                VStack(alignment: .leading, spacing: 6) {
                    Text(group)
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundColor(.secondary)
                        .textCase(.uppercase)
                        .tracking(0.7)
                        .padding(.horizontal, 8)

                    VStack(spacing: 3) {
                        ForEach(items, id: \.self) { item in
                            NavRow(item: item, isSelected: selectedNav == item) {
                                selectedNav = item
                                controller.navigate(to: item)
                            }
                        }
                    }
                }
            }
        }
    }

    private var modelCard: some View {
        Button {
            selectedNav = .apiKeys
            controller.navigate(to: .apiKeys)
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Label("Active Model", systemImage: "cpu")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(.secondary)
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.system(size: 9))
                        .foregroundColor(.secondary)
                }

                Text(activeModel)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(.primary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .padding(.horizontal, 9)
                    .padding(.vertical, 6)
                    .background(WhisprTheme.accent.opacity(0.10))
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .padding(12)
            .background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(WhisprTheme.border, lineWidth: 0.8)
            )
        }
        .buttonStyle(.plain)
    }

    private var languageCard: some View {
        VStack(alignment: .leading, spacing: 9) {
            Label("Output Language", systemImage: "globe")
                .font(.system(size: 11, weight: .semibold))
                .foregroundColor(.secondary)

            Picker("", selection: $selectedLanguage) {
                ForEach(Config.supportedLanguages, id: \.self) {
                    Text($0).tag($0)
                }
            }
            .pickerStyle(.menu)
            .labelsHidden()
            .onChange(of: selectedLanguage) { newValue in
                LanguageManager.shared.setLanguage(newValue)
                MenuBarController.shared.refreshLanguageMenu()
                syncStatus = "Saving…"

                backendClient.syncLanguageToBackend { success in
                    DispatchQueue.main.async {
                        syncStatus = success ? "Saved" : "Saved locally"
                        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                            syncStatus = ""
                        }
                    }
                }
            }

            if !syncStatus.isEmpty {
                Text(syncStatus)
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
        }
        .padding(12)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(WhisprTheme.border, lineWidth: 0.8)
        )
    }

    private var dataManagementCard: some View {
        VStack(alignment: .leading, spacing: 9) {
            Label("Data Management", systemImage: "externaldrive")
                .font(.system(size: 11, weight: .semibold))
                .foregroundColor(.secondary)

            VStack(spacing: 5) {
                ClearRow(label: "Transcription history", state: clearingHistory) {
                    armClear(.history)
                }

                ClearRow(label: "Personal dictionary", state: clearingDictionary) {
                    armClear(.dictionary)
                }

                ClearRow(label: "Voice snippets", state: clearingSnippets) {
                    armClear(.snippets)
                }

                ClearRow(label: "Profile context", state: resettingProfile) {
                    armClear(.profile)
                }

                Button {
                    armClear(.all)
                } label: {
                    HStack(spacing: 5) {
                        Image(systemName: "trash")
                        Text("Reset All Data")
                        Spacer()
                    }
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(.red)
                    .padding(.horizontal, 9)
                    .padding(.vertical, 7)
                    .background(Color.red.opacity(0.07))
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
                .buttonStyle(.plain)
                .padding(.top, 2)
            }
        }
        .padding(12)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(WhisprTheme.border, lineWidth: 0.8)
        )
        .alert(
            pendingClear?.alertTitle ?? "Confirm",
            isPresented: $showClearAlert,
            presenting: pendingClear
        ) { action in
            Button("Cancel", role: .cancel) {
                pendingClear = nil
            }

            Button(action.confirmLabel, role: .destructive) {
                executeClear(action)
                pendingClear = nil
            }
        } message: { action in
            Text(action.alertMessage)
        }
    }

    private var quitButton: some View {
        Button {
            NSApp.terminate(nil)
        } label: {
            HStack(spacing: 9) {
                Image(systemName: "power")
                    .font(.system(size: 12))
                    .frame(width: 16)

                Text("Quit Whispr")
                    .font(.system(size: 12))

                Spacer()
            }
            .foregroundColor(.red)
            .padding(.horizontal, 18)
            .padding(.vertical, 10)
        }
        .buttonStyle(.plain)
        .padding(.vertical, 6)
    }

    // MARK: - Data management

    private func armClear(_ action: DataClearAction) {
        pendingClear = action
        showClearAlert = true
    }

    private func executeClear(_ action: DataClearAction) {
        switch action {
        case .history:
            clearingHistory = .running
            backendClient.clearHistory { ok in
                clearingHistory = ok ? .done : .failed
                scheduleReset { clearingHistory = .idle }
            }

        case .dictionary:
            clearingDictionary = .running
            backendClient.clearDictionary { ok in
                clearingDictionary = ok ? .done : .failed
                scheduleReset { clearingDictionary = .idle }
            }

        case .snippets:
            clearingSnippets = .running
            backendClient.clearSnippets { ok in
                clearingSnippets = ok ? .done : .failed
                scheduleReset { clearingSnippets = .idle }
            }

        case .profile:
            resettingProfile = .running
            backendClient.resetProfile { ok in
                resettingProfile = ok ? .done : .failed
                scheduleReset { resettingProfile = .idle }
            }

        case .all:
            clearingHistory = .running
            clearingDictionary = .running
            clearingSnippets = .running
            resettingProfile = .running

            backendClient.resetAll { ok in
                let state: ClearState = ok ? .done : .failed
                clearingHistory = state
                clearingDictionary = state
                clearingSnippets = state
                resettingProfile = state

                scheduleReset {
                    clearingHistory = .idle
                    clearingDictionary = .idle
                    clearingSnippets = .idle
                    resettingProfile = .idle
                }
            }
        }
    }

    private func scheduleReset(_ block: @escaping () -> Void) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) {
            block()
        }
    }
}

// MARK: - Nav Row

struct NavRow: View {
    let item: NavItem
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                ZStack {
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(isSelected ? WhisprTheme.accent.opacity(0.18) : Color.clear)
                        .frame(width: 28, height: 28)

                    Image(systemName: item.icon)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(isSelected ? WhisprTheme.accent : .secondary)
                }

                Text(item.rawValue)
                    .font(.system(size: 13, weight: isSelected ? .semibold : .regular))
                    .foregroundColor(isSelected ? .primary : .secondary)

                Spacer()

                if isSelected {
                    Circle()
                        .fill(WhisprTheme.accent)
                        .frame(width: 6, height: 6)
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 7)
            .background(
                Group {
                    if isSelected {
                        RoundedRectangle(cornerRadius: 11, style: .continuous)
                            .fill(.regularMaterial)
                    } else {
                        Color.clear
                    }
                }
            )
            .overlay(
                RoundedRectangle(cornerRadius: 11, style: .continuous)
                    .stroke(isSelected ? WhisprTheme.border : Color.clear, lineWidth: 0.8)
            )
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Clear UI

enum ClearState {
    case idle
    case running
    case done
    case failed

    var icon: String {
        switch self {
        case .idle:    return "trash"
        case .running: return "hourglass"
        case .done:    return "checkmark"
        case .failed:  return "xmark"
        }
    }

    var color: Color {
        switch self {
        case .idle:    return .secondary
        case .running: return WhisprTheme.accent
        case .done:    return .green
        case .failed:  return .red
        }
    }
}

enum DataClearAction {
    case history
    case dictionary
    case snippets
    case profile
    case all

    var alertTitle: String {
        switch self {
        case .history:    return "Clear History?"
        case .dictionary: return "Clear Dictionary?"
        case .snippets:   return "Clear Snippets?"
        case .profile:    return "Reset Profile?"
        case .all:        return "Reset All Data?"
        }
    }

    var alertMessage: String {
        switch self {
        case .history:
            return "This will delete all transcription history."
        case .dictionary:
            return "This will delete your personal dictionary terms."
        case .snippets:
            return "This will delete all saved voice snippets."
        case .profile:
            return "This will reset your profile and learned context."
        case .all:
            return "This will delete history, dictionary, snippets, and profile context."
        }
    }

    var confirmLabel: String {
        switch self {
        case .all:
            return "Reset All"
        default:
            return "Clear"
        }
    }
}

struct ClearRow: View {
    let label: String
    let state: ClearState
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 7) {
                Image(systemName: state.icon)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundColor(state.color)
                    .frame(width: 14)

                Text(label)
                    .font(.system(size: 11))
                    .foregroundColor(.primary)

                Spacer()
            }
            .padding(.horizontal, 9)
            .padding(.vertical, 7)
            .background(Color(NSColor.textBackgroundColor).opacity(0.65))
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}
