import AppKit
import ApplicationServices

final class TextInserter {
    static func insertTextAtCursor(_ text: String) {
        let pasteboard = NSPasteboard.general
        let oldItems = pasteboard.pasteboardItems

        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)

        let source = CGEventSource(stateID: .hidSystemState)

        let vDown = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: true)
        vDown?.flags = .maskCommand

        let vUp = CGEvent(keyboardEventSource: source, virtualKey: 9, keyDown: false)
        vUp?.flags = .maskCommand

        vDown?.post(tap: .cghidEventTap)
        vUp?.post(tap: .cghidEventTap)

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            pasteboard.clearContents()
            oldItems?.forEach { item in
                for type in item.types {
                    if let value = item.string(forType: type) {
                        pasteboard.setString(value, forType: type)
                    }
                }
            }
        }
    }
}
