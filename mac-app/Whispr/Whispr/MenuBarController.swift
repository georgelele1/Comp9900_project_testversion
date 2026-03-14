import AppKit
import Combine

final class MenuBarController: NSObject {
    static let shared = MenuBarController()

    private let statusItem: NSStatusItem
    private var cancellables = Set<AnyCancellable>()

    private override init() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        super.init()

        if let button = statusItem.button {
            button.image = AppStatus.idle.menuBarIcon
            button.imagePosition = .imageOnly
            button.title = ""
        }

        statusItem.isVisible = true
        setupMenu()
    }

    func updateIcon(_ image: NSImage) {
        DispatchQueue.main.async {
            self.statusItem.button?.image = image
            self.statusItem.button?.image?.isTemplate = true
            self.statusItem.button?.imagePosition = .imageOnly
            self.statusItem.button?.title = ""
            self.statusItem.isVisible = true
        }
    }

    private func setupMenu() {
        let menu = NSMenu()

        let statusItemMenu = NSMenuItem(title: "Status: Idle", action: nil, keyEquivalent: "")
        let currentAppItem = NSMenuItem(title: "Current App: Unknown", action: nil, keyEquivalent: "")
        let currentModeItem = NSMenuItem(title: "Mode: Generic", action: nil, keyEquivalent: "")
        let lastResultItem = NSMenuItem(title: "Last Result: No transcription yet", action: nil, keyEquivalent: "")

        menu.addItem(statusItemMenu)
        menu.addItem(currentAppItem)
        menu.addItem(currentModeItem)
        menu.addItem(lastResultItem)

        menu.addItem(.separator())

        let startItem = NSMenuItem(title: "Start Recording", action: #selector(startRecording), keyEquivalent: "r")
        startItem.target = self
        menu.addItem(startItem)

        let stopItem = NSMenuItem(title: "Stop Recording", action: #selector(stopRecording), keyEquivalent: "s")
        stopItem.target = self
        menu.addItem(stopItem)

        let settingsItem = NSMenuItem(title: "Settings", action: #selector(openSettings), keyEquivalent: ",")
        settingsItem.target = self
        menu.addItem(settingsItem)

        menu.addItem(.separator())

        let quitItem = NSMenuItem(title: "Quit Whispr", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        AppManager.shared.$appStatus
            .receive(on: DispatchQueue.main)
            .sink { status in
                switch status {
                case .idle:
                    statusItemMenu.title = "Status: Idle"
                case .listening:
                    statusItemMenu.title = "Status: Recording"
                case .processing:
                    statusItemMenu.title = "Status: Processing"
                case .error:
                    statusItemMenu.title = "Status: Error"
                }
            }
            .store(in: &cancellables)

        AppManager.shared.$currentActiveApp
            .receive(on: DispatchQueue.main)
            .sink { appName in
                currentAppItem.title = "Current App: \(appName)"
            }
            .store(in: &cancellables)

        AppManager.shared.$currentTranscriptionMode
            .receive(on: DispatchQueue.main)
            .sink { mode in
                currentModeItem.title = "Mode: \(mode.rawValue.capitalized)"
            }
            .store(in: &cancellables)

        AppManager.shared.$lastOutputText
            .receive(on: DispatchQueue.main)
            .sink { text in
                lastResultItem.title = text.isEmpty ? "Last Result: No transcription yet" : "Last Result: \(text)"
            }
            .store(in: &cancellables)

        statusItem.menu = menu
    }

    @objc private func startRecording() {
        AppManager.shared.startRecordingFromMenu()
    }

    @objc private func stopRecording() {
        AppManager.shared.stopRecordingAndProcess()
    }

    @objc private func openSettings() {
        NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
    }

    @objc private func quitApp() {
        NSApp.terminate(nil)
    }
}
