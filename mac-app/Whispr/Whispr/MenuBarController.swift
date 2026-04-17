import AppKit
import SwiftUI
import Combine
import EventKit

final class MenuBarController: NSObject, NSMenuDelegate {
    static let shared = MenuBarController()

    private let statusItem: NSStatusItem
    private var cancellables = Set<AnyCancellable>()

    // Status zone
    private var statusMenuItem:  NSMenuItem?
    private var appMenuItem:     NSMenuItem?
    private var lastResultItem:  NSMenuItem?

    // Action zone
    private var startItem: NSMenuItem?
    private var stopItem:  NSMenuItem?

    // Config zone
    private var calendarMenuItem:   NSMenuItem?
    private var languageMenuItems:  [NSMenuItem] = []
    private var activeModelMenuItem: NSMenuItem?

    private var backendClient: LocalBackendClient {
        AppManager.shared.localBackendClient
    }

    // MARK: - Init

    private override init() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        super.init()
        if let button = statusItem.button {
            button.image = AppStatus.idle.menuBarIcon
            button.image?.isTemplate = true
            button.imagePosition = .imageOnly
            button.title = ""
        }
        statusItem.isVisible = true
        setupMenu()
    }

    // MARK: - Icon

    func updateIcon(_ image: NSImage) {
        DispatchQueue.main.async {
            self.statusItem.button?.image = image
            self.statusItem.button?.image?.isTemplate = true
            self.statusItem.button?.imagePosition = .imageOnly
            self.statusItem.button?.title = ""
            self.statusItem.isVisible = true
        }
    }

    // MARK: - Menu construction

    private func setupMenu() {
        let menu = NSMenu()
        menu.delegate = self

        // ── ZONE 1: Status (read-only context) ───────────────

        let statusDisplayItem = makeStatusItem(title: "Idle", icon: "circle.fill", color: .tertiaryLabelColor)
        menu.addItem(statusDisplayItem)
        self.statusMenuItem = statusDisplayItem

        let appItem = makeInfoItem(label: "App", value: "—", icon: "macwindow")
        menu.addItem(appItem)
        self.appMenuItem = appItem

        let resultItem = makeInfoItem(label: "Last result", value: "No transcription yet", icon: "text.bubble")
        resultItem.action = #selector(copyLastResult)
        resultItem.target = self
        menu.addItem(resultItem)
        self.lastResultItem = resultItem

        let modelItem = makeInfoItem(label: "Model", value: "…", icon: "cpu")
        modelItem.action = #selector(openAPIKeys)
        modelItem.target = self
        menu.addItem(modelItem)
        self.activeModelMenuItem = modelItem

        menu.addItem(makeSectionSeparator(label: "RECORDING"))

        // ── ZONE 2: Primary actions ───────────────────────────

        let start = NSMenuItem(title: "Start Recording", action: #selector(startRecording), keyEquivalent: "r")
        start.target = self
        start.image  = icon("record.circle.fill", color: .systemGreen, size: 14)
        menu.addItem(start)
        self.startItem = start

        let stop = NSMenuItem(title: "Stop & Transcribe", action: #selector(stopRecording), keyEquivalent: "s")
        stop.target    = self
        stop.image     = icon("stop.circle.fill", color: .systemRed, size: 14)
        stop.isEnabled = false
        menu.addItem(stop)
        self.stopItem = stop

        menu.addItem(makeSectionSeparator(label: "SETTINGS"))

        // ── ZONE 3: Configuration ─────────────────────────────

        let languageMenu = NSMenu()
        languageMenuItems.removeAll()
        for lang in Config.supportedLanguages {
            let item = NSMenuItem(title: lang, action: #selector(selectLanguage(_:)), keyEquivalent: "")
            item.target = self
            languageMenu.addItem(item)
            languageMenuItems.append(item)
        }
        let languageParent = NSMenuItem(title: "Output Language", action: nil, keyEquivalent: "")
        languageParent.image   = icon("globe", color: .secondaryLabelColor, size: 13)
        languageParent.submenu = languageMenu
        menu.addItem(languageParent)
        refreshLanguageMenu()

        let dictItem = NSMenuItem(title: "Update Dictionary", action: #selector(updateDictionary), keyEquivalent: "d")
        dictItem.target = self
        dictItem.image  = icon("text.book.closed", color: .secondaryLabelColor, size: 13)
        menu.addItem(dictItem)

        let calItem = NSMenuItem(title: "Calendar Access: Checking…", action: #selector(handleCalendarItem), keyEquivalent: "")
        calItem.target = self
        calItem.image  = icon("calendar", color: .secondaryLabelColor, size: 13)
        menu.addItem(calItem)
        calendarMenuItem = calItem

        menu.addItem(makeSectionSeparator(label: "APP"))

        // ── ZONE 4: System ────────────────────────────────────

        let openItem = NSMenuItem(title: "Open Whispr", action: #selector(openMainWindow), keyEquivalent: "o")
        openItem.target = self
        openItem.image  = icon("macwindow", color: .secondaryLabelColor, size: 13)
        menu.addItem(openItem)

        menu.addItem(.separator())

        let quitItem = NSMenuItem(title: "Quit Whispr", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target    = self
        quitItem.image     = icon("power", color: .systemRed, size: 13)
        quitItem.attributedTitle = NSAttributedString(
            string: "Quit Whispr",
            attributes: [.foregroundColor: NSColor.systemRed]
        )
        menu.addItem(quitItem)

        self.statusItem.menu = menu

        // ── Reactive bindings ─────────────────────────────────

        AppManager.shared.$appStatus
            .receive(on: DispatchQueue.main)
            .sink { [weak self] status in self?.applyStatus(status) }
            .store(in: &cancellables)

        AppManager.shared.$currentActiveApp
            .receive(on: DispatchQueue.main)
            .sink { [weak self] appName in
                self?.appMenuItem?.attributedTitle = self?.makeInfoAttributed(label: "App", value: appName)
            }
            .store(in: &cancellables)

        AppManager.shared.$lastOutputText
            .receive(on: DispatchQueue.main)
            .sink { [weak self] text in
                guard let self else { return }
                let display = text.isEmpty ? "No transcription yet" : String(text.prefix(55)) + (text.count > 55 ? "…" : "")
                self.lastResultItem?.attributedTitle = self.makeInfoAttributed(label: "Last result", value: display)
                self.lastResultItem?.isEnabled = !text.isEmpty
            }
            .store(in: &cancellables)

        // Update model item with cost + balance after each transcription
        Publishers.CombineLatest(
            AppManager.shared.$lastCost,
            AppManager.shared.$lastConnectonionBalance
        )
        .receive(on: DispatchQueue.main)
        .sink { [weak self] cost, coBalance in
            guard let self else { return }
            var parts: [String] = [AppManager.shared.localBackendClient.activeModel]
            if let cost {
                parts.append(cost < 0.0001 ? "<$0.0001" : String(format: "$%.4f", cost))
            }
            if let coBalance {
                parts.append(String(format: "$%.2f left", coBalance))
            }
            self.activeModelMenuItem?.attributedTitle = self.makeInfoAttributed(
                label: "Model", value: parts.joined(separator: " · ")
            )
        }
        .store(in: &cancellables)

        AppManager.shared.localBackendClient.$activeModel
            .receive(on: DispatchQueue.main)
            .sink { [weak self] model in
                guard let self else { return }
                self.activeModelMenuItem?.attributedTitle = self.makeInfoAttributed(label: "Model", value: model)
            }
            .store(in: &cancellables)

        LanguageManager.shared.$current
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.refreshLanguageMenu() }
            .store(in: &cancellables)

        AppManager.shared.localBackendClient.$calendarPermission
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.refreshCalendarItem() }
            .store(in: &cancellables)

        refreshCalendarItem()
    }

    // MARK: - Status application

    private func applyStatus(_ status: AppStatus) {
        let (label, color): (String, NSColor) = switch status {
        case .idle:       ("Idle",        .tertiaryLabelColor)
        case .listening:  ("Recording…",  .systemRed)
        case .processing: ("Transcribing…", .systemOrange)
        case .error:      ("Error",       .systemRed)
        }

        let iconName: String = switch status {
        case .idle:       "circle.fill"
        case .listening:  "record.circle.fill"
        case .processing: "waveform.circle.fill"
        case .error:      "exclamationmark.circle.fill"
        }

        statusMenuItem?.image = icon(iconName, color: color, size: 10)
        statusMenuItem?.attributedTitle = NSAttributedString(
            string: label,
            attributes: [
                .foregroundColor: color,
                .font: NSFont.systemFont(ofSize: 12, weight: .medium)
            ]
        )

        startItem?.isEnabled = (status == .idle || status == .error)
        stopItem?.isEnabled  = (status == .listening)

        startItem?.image = icon(
            "record.circle.fill",
            color: startItem?.isEnabled == true ? .systemGreen : .tertiaryLabelColor,
            size: 14
        )
    }

    // MARK: - menuWillOpen

    func menuWillOpen(_ menu: NSMenu) {
        AppManager.shared.detectCurrentApp()
        AppManager.shared.localBackendClient.refreshCalendarPermission()
    }

    // MARK: - Language

    func refreshLanguageMenu() {
        let lang = LanguageManager.shared.current
        languageMenuItems.forEach { $0.state = ($0.title == lang) ? .on : .off }
    }

    @objc private func selectLanguage(_ sender: NSMenuItem) {
        guard Config.supportedLanguages.contains(sender.title) else { return }
        LanguageManager.shared.setLanguage(sender.title)
        refreshLanguageMenu()
        backendClient.syncLanguageToBackend { _ in }
    }

    // MARK: - Calendar

    func refreshCalendarItem() {
        let status = EKEventStore.authorizationStatus(for: .event)
        switch status {
        case .authorized, .fullAccess:
            calendarMenuItem?.attributedTitle = makeInfoAttributed(label: "Calendar", value: "Granted ✓", valueColor: .systemGreen)
            calendarMenuItem?.action = nil
        case .denied, .restricted:
            calendarMenuItem?.attributedTitle = makeInfoAttributed(label: "Calendar", value: "Open Settings…", valueColor: .systemOrange)
            calendarMenuItem?.action = #selector(handleCalendarItem)
        default:
            calendarMenuItem?.attributedTitle = makeInfoAttributed(label: "Calendar", value: "Grant Access…", valueColor: .systemBlue)
            calendarMenuItem?.action = #selector(handleCalendarItem)
        }
    }

    @objc private func handleCalendarItem() {
        let status = EKEventStore.authorizationStatus(for: .event)
        switch status {
        case .authorized, .fullAccess:
            break
        case .denied, .restricted:
            backendClient.openCalendarSettings()
        default:
            backendClient.requestCalendarPermission { [weak self] _ in
                self?.refreshCalendarItem()
            }
        }
    }

    // MARK: - Actions

    @objc private func updateDictionary() { AppManager.shared.updateDictionary() }
    @objc private func startRecording()   { AppManager.shared.startRecording() }
    @objc private func stopRecording()    { AppManager.shared.stopRecordingAndProcess() }
    @objc private func openMainWindow()   { MainWindowController.shared.navigate(to: .home) }
    @objc private func openAPIKeys()      { MainWindowController.shared.navigate(to: .apiKeys) }
    @objc private func quitApp()          { NSApp.terminate(nil) }

    @objc private func copyLastResult() {
        let text = AppManager.shared.lastOutputText
        guard !text.isEmpty else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    // MARK: - Builder helpers

    /// A two-line status header item (large label, colored).
    private func makeStatusItem(title: String, icon iconName: String, color: NSColor) -> NSMenuItem {
        let item = NSMenuItem()
        item.isEnabled = false
        item.image = icon(iconName, color: color, size: 10)
        item.attributedTitle = NSAttributedString(
            string: title,
            attributes: [
                .foregroundColor: color,
                .font: NSFont.systemFont(ofSize: 12, weight: .medium)
            ]
        )
        return item
    }

    /// A key/value info row with muted label and normal value.
    private func makeInfoItem(label: String, value: String, icon iconName: String) -> NSMenuItem {
        let item = NSMenuItem()
        item.isEnabled = false
        item.image = icon(iconName, color: .tertiaryLabelColor, size: 13)
        item.attributedTitle = makeInfoAttributed(label: label, value: value)
        return item
    }

    private func makeInfoAttributed(
        label: String,
        value: String,
        valueColor: NSColor = .labelColor
    ) -> NSAttributedString {
        let str = NSMutableAttributedString(
            string: label + "  ",
            attributes: [
                .foregroundColor: NSColor.tertiaryLabelColor,
                .font: NSFont.systemFont(ofSize: 11)
            ]
        )
        str.append(NSAttributedString(
            string: value,
            attributes: [
                .foregroundColor: valueColor,
                .font: NSFont.systemFont(ofSize: 12)
            ]
        ))
        return str
    }

    /// A visually distinct section separator with a small caps label.
    private func makeSectionSeparator(label: String) -> NSMenuItem {
        let item = NSMenuItem()
        item.isEnabled = false
        item.attributedTitle = NSAttributedString(
            string: label,
            attributes: [
                .foregroundColor: NSColor.quaternaryLabelColor,
                .font: NSFont.systemFont(ofSize: 9, weight: .semibold),
                .kern: 1.2
            ]
        )
        // Add a top separator line before the label
        let separatorAbove = NSMenuItem.separator()
        // We return a combined separator + label pair via a convenience: just return the label item
        // (caller must also add a separator before calling this — handled inline above in setupMenu)
        return item
    }

    /// Renders an SF Symbol as a small tinted NSImage suitable for menu items.
    private func icon(_ name: String, color: NSColor, size: CGFloat) -> NSImage {
        let config = NSImage.SymbolConfiguration(pointSize: size, weight: .medium)
        let image  = NSImage(systemSymbolName: name, accessibilityDescription: nil)?
            .withSymbolConfiguration(config) ?? NSImage()
        return image.tinted(color)
    }
}

// MARK: - NSImage tint helper

private extension NSImage {
    func tinted(_ color: NSColor) -> NSImage {
        guard let copy = self.copy() as? NSImage else { return self }
        copy.lockFocus()
        color.set()
        NSRect(origin: .zero, size: copy.size).fill(using: .sourceAtop)
        copy.unlockFocus()
        copy.isTemplate = false
        return copy
    }
}
