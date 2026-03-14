import AppKit

final class ActiveAppDetector {
    private let appModeMapping: [String: TranscriptionMode] = [
        "Visual Studio Code": .code,
        "Code": .code,
        "Xcode": .code,
        "Terminal": .code,
        "iTerm2": .code,
        "Sublime Text": .code,
        "PyCharm": .code,
        "Mail": .formal,
        "Microsoft Outlook": .formal,
        "Spark": .formal,
        "Messages": .chat,
        "Slack": .chat,
        "Discord": .chat,
        "Telegram": .chat,
        "WhatsApp": .chat,
        "Microsoft Word": .academic,
        "Pages": .academic,
        "Zotero": .academic,
        "EndNote": .academic,
        "Obsidian": .academic,
        "Notion": .academic,
        "Google Chrome": .generic,
        "Safari": .generic,
        "Firefox": .generic
    ]

    func getActiveAppAndMode() -> (appName: String, mode: TranscriptionMode) {
        guard let activeApp = NSWorkspace.shared.frontmostApplication,
              let appName = activeApp.localizedName else {
            return ("Unknown", .generic)
        }

        let mode = appModeMapping[appName] ?? .generic
        NSLog("Detected active app: \(appName) → mode: \(mode.rawValue)")
        return (appName, mode)
    }
}
