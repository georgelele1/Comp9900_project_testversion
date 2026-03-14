import AppKit
import Carbon.HIToolbox

final class HotkeyManager {

    private var hotkeyMonitor: CFMachPort?
    private var runLoopSource: CFRunLoopSource?
    private var hotkeyHandler: ((Bool) -> Void)?

    // Start: Cmd + Shift + Space
    private let startHotkey = KeyCombo(keyCode: 49, modifiers: [.command, .shift])

    // Stop: Cmd + Shift + S
    private let stopHotkey = KeyCombo(keyCode: 1, modifiers: [.command, .shift])

    func setupGlobalHotkey(handler: @escaping (Bool) -> Void) {
        hotkeyHandler = handler

        let callback: CGEventTapCallBack = { _, type, event, refcon in

            guard let refcon else {
                return Unmanaged.passUnretained(event)
            }

            let manager = Unmanaged<HotkeyManager>.fromOpaque(refcon).takeUnretainedValue()

            let keyCode = Int32(event.getIntegerValueField(.keyboardEventKeycode))
            let modifiers = NSEvent.ModifierFlags(rawValue: UInt(event.flags.rawValue))

            let startMatch =
                keyCode == manager.startHotkey.keyCode &&
                modifiers.contains(manager.startHotkey.modifiers)

            let stopMatch =
                keyCode == manager.stopHotkey.keyCode &&
                modifiers.contains(manager.stopHotkey.modifiers)

            if type == .keyDown {

                if startMatch {
                    manager.hotkeyHandler?(true)
                    return nil
                }

                if stopMatch {
                    manager.hotkeyHandler?(false)
                    return nil
                }
            }

            return Unmanaged.passUnretained(event)
        }

        let mask = (1 << CGEventType.keyDown.rawValue)

        hotkeyMonitor = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .defaultTap,
            eventsOfInterest: CGEventMask(mask),
            callback: callback,
            userInfo: Unmanaged.passUnretained(self).toOpaque()
        )

        if let monitor = hotkeyMonitor {

            runLoopSource = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, monitor, 0)

            if let source = runLoopSource {
                CFRunLoopAddSource(CFRunLoopGetCurrent(), source, .commonModes)
            }
        }
    }

    func showHotkeyConfiguration() {
        let alert = NSAlert()
        alert.messageText = "Hotkeys"
        alert.informativeText = """
Start Recording: Cmd + Shift + Space
Stop Recording: Cmd + Shift + S
"""
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    struct KeyCombo {
        let keyCode: Int32
        let modifiers: NSEvent.ModifierFlags
    }
}
