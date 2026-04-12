import Foundation
import AppKit
import Combine

final class AppManager: ObservableObject {
    static let shared = AppManager()
    private init() {}

    let hotkeyManager      = HotkeyManager()
    let audioRecorder      = AudioRecorder()
    let localBackendClient = LocalBackendClient()
    let activeAppDetector  = ActiveAppDetector()

    private var pill: FloatingStatusButton { .shared }

    @Published var appStatus: AppStatus = .idle
    @Published var lastOutputText: String = ""
    @Published var currentActiveApp: String = "Unknown"

    private var targetAppPID: pid_t = 0
    private var cancellables = Set<AnyCancellable>()

    // MARK: - Init

    func initialize() {
        // Create the persistent HUD — it observes $appStatus internally.
        floatingIndicator.createPersistentPanel()

        hotkeyManager.setupGlobalHotkey { [weak self] shouldStart in
            guard let self else { return }
            if shouldStart {
                self.startRecordingFromMenu()
            } else {
                self.stopRecordingAndProcess()
            }
        }
        // Intentionally no $isRecording sink here.
        // A sink on isRecording races with the manual stop path:
        // stopRecording() sets isRecording=false synchronously, but
        // updateAppStatus(.processing) is async, so the sink would
        // still see appStatus==.listening and fire a second stop.
        // Timeout auto-stop is handled by AudioRecorder.audioRecorderDidFinishRecording instead.
    }

    // MARK: - Dictionary

    func updateDictionary() {
        guard localBackendClient.isBackendAvailable else {
            showErrorAlert(message: "Python backend is not accessible")
            return
        }
        updateAppStatus(.processing)
        localBackendClient.runDictionaryUpdate { [weak self] result in
            guard let self else { return }
            DispatchQueue.main.async {
                switch result {
                case .success(let update):
                    self.updateAppStatus(.idle)
                    self.pill.update(.idle)
                    let alert = NSAlert()
                    alert.messageText = "Dictionary Updated"
                    var lines = ["Total terms: \(update.totalTerms)"]
                    if update.added.isEmpty {
                        lines.append("\nNo new terms were added this run.")
                    } else {
                        lines.append("\nNewly added (\(update.added.count)):")
                        for term in update.added {
                            var line = "  • \(term.phrase) [\(term.type)]"
                            if !term.aliases.isEmpty {
                                line += " — aliases: \(term.aliases.joined(separator: ", "))"
                            }
                            lines.append(line)
                        }
                    }
                    alert.informativeText = lines.joined(separator: "\n")
                    alert.addButton(withTitle: "OK")
                    alert.runModal()
                case .failure(let error):
                    self.updateAppStatus(.error)
                    self.pill.update(.error)
                    self.showErrorAlert(message: "Dictionary update failed: \(error.localizedDescription)")
                }
            }
        }
    }

    // MARK: - App detection

    func detectCurrentApp() {
        guard let activeApp = NSWorkspace.shared.frontmostApplication else {
            currentActiveApp = "Unknown"
            targetAppPID = 0
            return
        }
        currentActiveApp = activeApp.localizedName ?? "Unknown"
        targetAppPID     = activeApp.processIdentifier
    }

    // MARK: - Status

    func updateAppStatus(_ status: AppStatus) {
        DispatchQueue.main.async {
            self.appStatus = status
            MenuBarController.shared.updateIcon(status.menuBarIcon)
        }
    }

    // MARK: - Recording

    func startRecordingFromMenu() {
        detectCurrentApp()
        startRecording()
    }

    func startRecording() {
        guard localBackendClient.isBackendAvailable else {
            updateAppStatus(.error)
            pill.update(.error)
            showErrorAlert(message: "Python backend is not accessible")
            return
        }

        do {
            try audioRecorder.startRecording()
            updateAppStatus(.listening)   // HUD expands to "Recording…"
        } catch {
            updateAppStatus(.error)
            showErrorAlert(message: "Failed to start recording: \(error.localizedDescription)")
        }
    }

    func stopRecordingAndProcess() {
        guard let audioFileURL = audioRecorder.stopRecording() else {
            updateAppStatus(.error)
            pill.update(.error)
            showErrorAlert(message: "No audio file recorded")
            return
        }

        updateAppStatus(.processing)   // HUD switches to "Transcribing…"

        if FileManager.default.fileExists(atPath: audioFileURL.path) {
            print("audio path =", audioFileURL.path)
            print("file exists before run = true")
        } else {
            print("audio path =", audioFileURL.path)
            print("file exists before run = false")
        }

        localBackendClient.transcribeAudio(
            fileURL: audioFileURL,
            appName: currentActiveApp
        ) { [weak self] result in
            guard let self else { return }
            DispatchQueue.main.async {
                switch result {
                case .success(let text):
                    self.lastOutputText = text
                    self.updateAppStatus(.idle)   // HUD collapses back to small button
                    self.pasteTextToActiveApp(text: text)

                case .failure(let error):
                    self.updateAppStatus(.error)
                    self.pill.update(.error)
                    self.showErrorAlert(message: "Transcription failed: \(error.localizedDescription)")
                }
            }
        }
    }

    // MARK: - Alerts

    func showPermissionAlert() {
        let alert = NSAlert()
        alert.messageText = "Microphone Permission Required"
        alert.informativeText = "Whispr needs microphone access to record audio. Please enable it in System Settings > Privacy & Security > Microphone."
        alert.addButton(withTitle: "Open Settings")
        alert.addButton(withTitle: "Cancel")
        if alert.runModal() == .alertFirstButtonReturn,
           let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") {
            NSWorkspace.shared.open(url)
        }
    }

    func showErrorAlert(message: String) {
        let alert = NSAlert()
        alert.messageText = "Error"
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    // MARK: - Paste

    private func pasteTextToTargetApp(text: String) {
        let pasteboard = NSPasteboard.general
        let previous   = pasteboard.pasteboardItems

        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)

        let source = CGEventSource(stateID: .hidSystemState)

        let keyDown = CGEvent(keyboardEventSource: source, virtualKey: 0x09, keyDown: true)
        keyDown?.flags = .maskCommand
        keyDown?.post(tap: .cghidEventTap)

        let keyUp = CGEvent(keyboardEventSource: source, virtualKey: 0x09, keyDown: false)
        keyUp?.flags = .maskCommand
        keyUp?.post(tap: .cghidEventTap)

        // Restore the previous pasteboard contents after a short delay.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            pasteboard.clearContents()
            previousItems?.forEach { item in
                for type in item.types {
                    if let data = item.data(forType: type) {
                        pasteboard.setData(data, forType: type)
                    }
                }
            }
        }
    }
}
