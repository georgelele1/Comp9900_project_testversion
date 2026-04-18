import SwiftUI
import AppKit

// MARK: - ShortcutsView

struct ShortcutsView: View {

    @State private var startShortcut  : ShortcutKey = ShortcutManager.shared.startShortcut
    @State private var stopShortcut   : ShortcutKey = ShortcutManager.shared.stopShortcut
    @State private var recording      : RecordingTarget? = nil
    @State private var statusMessage  : String = ""

    private let accent = Color(red: 0.498, green: 0.467, blue: 0.867)

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Keyboard Shortcuts").font(.title2).bold()
                    Text("Click a shortcut to record a new key combination.")
                        .font(.caption).foregroundColor(.secondary)
                }
                Spacer()
                Button("Reset to defaults") { resetDefaults() }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
            }
            .padding()

            Divider()

            VStack(alignment: .leading, spacing: 20) {

                // Start recording shortcut
                shortcutRow(
                    icon:        "mic.fill",
                    iconColor:   .green,
                    label:       "Start Recording",
                    description: "Begin capturing your voice.",
                    shortcut:    startShortcut,
                    target:      .start
                )

                Divider()

                // Stop & transcribe shortcut
                shortcutRow(
                    icon:        "stop.circle.fill",
                    iconColor:   .red,
                    label:       "Stop & Transcribe",
                    description: "Stop recording and process the audio.",
                    shortcut:    stopShortcut,
                    target:      .stop
                )

                if !statusMessage.isEmpty {
                    Divider()
                    Text(statusMessage)
                        .font(.caption)
                        .foregroundColor(.secondary)
                        .padding(.horizontal, 4)
                }
            }
            .padding(24)

            Spacer()

            // Recording capture overlay
            if recording != nil {
                Divider()
                HStack {
                    Image(systemName: "keyboard")
                        .foregroundColor(accent)
                    Text("Press your desired key combination… ")
                        .font(.system(size: 13))
                    Text("Esc to cancel")
                        .font(.system(size: 12))
                        .foregroundColor(.secondary)
                    Spacer()
                    Button("Cancel") { recording = nil }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                }
                .padding(.horizontal, 24)
                .padding(.vertical, 12)
                .background(accent.opacity(0.06))
            }
        }
        .frame(width: 540, height: 340)
        .background(
            // Key capture monitor when recording
            KeyCaptureView(isActive: recording != nil) { keyCode, modifiers in
                handleCapture(keyCode: keyCode, modifiers: modifiers)
            }
            .frame(width: 0, height: 0)
        )
    }

    // MARK: - Row builder

    private func shortcutRow(
        icon: String,
        iconColor: Color,
        label: String,
        description: String,
        shortcut: ShortcutKey,
        target: RecordingTarget
    ) -> some View {
        HStack(spacing: 16) {
            // Icon
            ZStack {
                RoundedRectangle(cornerRadius: 8)
                    .fill(iconColor.opacity(0.1))
                    .frame(width: 36, height: 36)
                Image(systemName: icon)
                    .font(.system(size: 16))
                    .foregroundColor(iconColor)
            }

            // Label + description
            VStack(alignment: .leading, spacing: 2) {
                Text(label).font(.system(size: 13, weight: .medium))
                Text(description).font(.caption).foregroundColor(.secondary)
            }

            Spacer()

            // Shortcut pill — click to record
            let isRecording = recording == target
            Button {
                recording = isRecording ? nil : target
                statusMessage = ""
            } label: {
                HStack(spacing: 6) {
                    if isRecording {
                        Circle()
                            .fill(Color.red)
                            .frame(width: 6, height: 6)
                        Text("Recording…")
                            .font(.system(size: 12))
                            .foregroundColor(.red)
                    } else {
                        Text(shortcut.displayString)
                            .font(.system(size: 13, weight: .medium, design: .monospaced))
                            .foregroundColor(isRecording ? .red : .primary)
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 7)
                .background(isRecording ? Color.red.opacity(0.08) : Color(NSColor.controlBackgroundColor))
                .cornerRadius(8)
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(isRecording ? Color.red : accent, lineWidth: isRecording ? 1.5 : 1)
                )
            }
            .buttonStyle(.plain)
            .animation(.easeInOut(duration: 0.15), value: isRecording)
        }
    }

    // MARK: - Actions

    private func handleCapture(keyCode: Int32, modifiers: NSEvent.ModifierFlags) {
        guard let target = recording else { return }

        // Esc cancels
        if keyCode == 53 {
            recording = nil
            return
        }

        // Require at least one modifier
        let relevant = modifiers.intersection([.command, .option, .control, .shift])
        guard !relevant.isEmpty else {
            statusMessage = "Please use at least one modifier key (⌘ ⌃ ⌥ ⇧)."
            return
        }

        let new = ShortcutKey(keyCode: keyCode, modifiers: relevant.rawValue)

        // Check for conflict
        let other = target == .start ? stopShortcut : startShortcut
        if new == other {
            statusMessage = "That combination is already used by the other shortcut."
            return
        }

        switch target {
        case .start:
            startShortcut = new
            ShortcutManager.shared.startShortcut = new
        case .stop:
            stopShortcut = new
            ShortcutManager.shared.stopShortcut = new
        }

        recording     = nil
        statusMessage = "Shortcut saved."
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { statusMessage = "" }
    }

    private func resetDefaults() {
        ShortcutManager.shared.reset()
        startShortcut = ShortcutManager.shared.startShortcut
        stopShortcut  = ShortcutManager.shared.stopShortcut
        recording     = nil
        statusMessage = "Reset to ⌥Space and ⌥S."
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { statusMessage = "" }
    }

    enum RecordingTarget { case start, stop }
}

// MARK: - KeyCaptureView
// An invisible NSView that intercepts key events when active.

struct KeyCaptureView: NSViewRepresentable {
    let isActive: Bool
    let onCapture: (Int32, NSEvent.ModifierFlags) -> Void

    func makeNSView(context: Context) -> KeyCapture { KeyCapture(onCapture: onCapture) }

    func updateNSView(_ view: KeyCapture, context: Context) {
        if isActive {
            view.window?.makeFirstResponder(view)
        }
    }
}

final class KeyCapture: NSView {
    let onCapture: (Int32, NSEvent.ModifierFlags) -> Void

    init(onCapture: @escaping (Int32, NSEvent.ModifierFlags) -> Void) {
        self.onCapture = onCapture
        super.init(frame: .zero)
    }
    required init?(coder: NSCoder) { fatalError() }

    override var acceptsFirstResponder: Bool { true }

    override func keyDown(with event: NSEvent) {
        let mods = event.modifierFlags.intersection([.command, .option, .control, .shift])
        onCapture(Int32(event.keyCode), mods)
    }
}
