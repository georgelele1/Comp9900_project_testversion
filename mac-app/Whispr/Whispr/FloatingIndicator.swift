import SwiftUI
import AppKit
import Combine

// =========================================================
// FloatingIndicator
//
// A persistent HUD anchored to the bottom-centre of the screen:
//   • Idle       — small capsule button (purple dot + "Whispr"), tap to open main window
//   • Listening  — expanded, red waveform + "Recording…" + shortcut hint
//   • Processing — expanded, spinner + "Transcribing…"
//   • Expanded   — "Open" button always visible on the right
//
// Uses NSPanel (nonactivatingPanel) so it never steals focus.
// =========================================================

final class FloatingIndicator: ObservableObject {

    private var panel: NSPanel?
    private var hostingView: NSHostingView<HUDRootView>?
    private var cancellables = Set<AnyCancellable>()

    // MARK: - Public API

    /// Call once at app launch to create the persistent panel and start observing status changes.
    func createPersistentPanel() {
        DispatchQueue.main.async { self.buildPanelIfNeeded() }

        AppManager.shared.$appStatus
            .receive(on: DispatchQueue.main)
            .sink { [weak self] status in
                self?.update(status: status)
            }
            .store(in: &cancellables)
    }

    // MARK: - Legacy shims (kept for compatibility with existing AppManager call sites)

    func showIndicator(status: AppStatus = .listening) {
        DispatchQueue.main.async { self.update(status: status) }
    }

    func hideIndicator() {
        // No longer truly hides — resets to the idle compact state instead.
        DispatchQueue.main.async { self.update(status: .idle) }
    }

    // MARK: - Internal

    private func update(status: AppStatus) {
        buildPanelIfNeeded()
        hostingView?.rootView = HUDRootView(status: status)
        resizePanel(for: status)
    }

    private func resizePanel(for status: AppStatus) {
        guard let p = panel else { return }
        let expanded = status == .listening || status == .processing
        let newW = expanded ? HUDLayout.maxWidth : HUDLayout.idleWidth
        guard p.frame.width != newW else { return }

        // Keep the bottom-centre anchor fixed while resizing.
        let oldFrame = p.frame
        let newX = oldFrame.midX - newW / 2
        let newFrame = NSRect(x: newX, y: oldFrame.minY, width: newW, height: HUDLayout.height)
        p.setFrame(newFrame, display: true, animate: true)
        hostingView?.frame = NSRect(x: 0, y: 0, width: newW, height: HUDLayout.height)
    }

    private func buildPanelIfNeeded() {
        guard panel == nil else { return }

        let rootView = HUDRootView(status: .idle)
        let hosting = NSHostingView(rootView: rootView)
        hosting.frame = NSRect(x: 0, y: 0, width: HUDLayout.idleWidth, height: HUDLayout.height)
        hostingView = hosting

        let p = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: HUDLayout.idleWidth, height: HUDLayout.height),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        p.isOpaque           = false
        p.backgroundColor    = .clear
        p.level              = .statusBar
        p.hasShadow          = true
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        p.ignoresMouseEvents = false
        p.contentView = hosting

        repositionPanel(p, width: HUDLayout.idleWidth)
        p.orderFrontRegardless()

        // Re-centre the panel if the screen configuration changes.
        NotificationCenter.default.addObserver(
            forName: NSApplication.didChangeScreenParametersNotification,
            object: nil,
            queue: .main
        ) { [weak self, weak p] _ in
            guard let p else { return }
            self?.repositionPanel(p, width: p.frame.width)
        }

        panel = p
    }

    private func repositionPanel(_ p: NSPanel, width: CGFloat) {
        guard let screen = NSScreen.main else { return }
        let sf = screen.visibleFrame
        let x  = sf.midX - width / 2
        let y  = sf.minY + 16
        p.setFrameOrigin(NSPoint(x: x, y: y))
    }
}

// =========================================================
// Layout constants
// =========================================================

enum HUDLayout {
    static let height: CGFloat    = 40
    static let maxWidth: CGFloat  = 270   // expanded (recording / processing)
    static let idleWidth: CGFloat = 108   // compact (idle)
}

// =========================================================
// HUDRootView
// =========================================================

struct HUDRootView: View {

    let status: AppStatus

    private var isExpanded: Bool {
        status == .listening || status == .processing
    }

    var body: some View {
        ZStack {
            Capsule()
                .fill(Color(white: 0.08, opacity: 0.90))
                .overlay(Capsule().stroke(Color.white.opacity(0.12), lineWidth: 0.5))

            HStack(spacing: 0) {

                // Left status area
                HStack(spacing: 7) {
                    leftContent
                }
                .padding(.leading, 13)
                .frame(maxWidth: .infinity, alignment: .leading)

                if isExpanded {
                    Rectangle()
                        .fill(Color.white.opacity(0.13))
                        .frame(width: 1, height: 22)

                    openButton
                }
            }
        }
        .frame(
            width: isExpanded ? HUDLayout.maxWidth : HUDLayout.idleWidth,
            height: HUDLayout.height
        )
        // In idle/error state the whole capsule is tappable.
        .contentShape(Capsule())
        .onTapGesture {
            if status == .idle || status == .error {
                openMainWindow()
            }
        }
    }

    // MARK: - Left content

    @ViewBuilder
    private var leftContent: some View {
        switch status {
        case .idle:
            Circle()
                .fill(Color(red: 0.498, green: 0.467, blue: 0.867))
                .frame(width: 7, height: 7)
            Text("Whispr")
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(Color.white.opacity(0.82))

        case .listening:
            HUDWaveform()
            Text("Recording…")
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(Color(red: 0.94, green: 0.59, blue: 0.48))
            Text("⌥S to stop")
                .font(.system(size: 10))
                .foregroundColor(Color.white.opacity(0.32))

        case .processing:
            HUDSpinner()
            Text("Transcribing…")
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(Color(red: 0.686, green: 0.663, blue: 0.925))

        case .error:
            Circle()
                .fill(Color(red: 0.886, green: 0.294, blue: 0.290))
                .frame(width: 7, height: 7)
            Text("Error")
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(Color(red: 0.94, green: 0.76, blue: 0.76))
        }
    }

    // MARK: - Open button

    private var openButton: some View {
        Button(action: openMainWindow) {
            HStack(spacing: 4) {
                Image(systemName: "macwindow")
                    .font(.system(size: 10, weight: .medium))
                Text("Open")
                    .font(.system(size: 11, weight: .medium))
            }
            .foregroundColor(Color.white.opacity(0.62))
            .padding(.horizontal, 12)
            .frame(height: HUDLayout.height)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    // MARK: - Action

    private func openMainWindow() {
        MainWindowController.shared.navigate(to: .home)
        DispatchQueue.main.async { NSApp.activate(ignoringOtherApps: true) }
    }
}

// =========================================================
// HUDWaveform — 5-bar animated waveform shown while recording
// =========================================================

struct HUDWaveform: View {

    @State private var phases: [Double] = [0.3, 0.7, 0.4, 0.9, 0.5]

    private let count = 5
    private let barW: CGFloat = 3
    private let maxH: CGFloat = 16
    private let minH: CGFloat = 3

    var body: some View {
        HStack(alignment: .center, spacing: 2) {
            ForEach(0..<count, id: \.self) { i in
                RoundedRectangle(cornerRadius: 1.5)
                    .fill(Color(red: 0.886, green: 0.294, blue: 0.290).opacity(0.9))
                    .frame(width: barW, height: minH + CGFloat(phases[i]) * (maxH - minH))
                    .animation(
                        .easeInOut(duration: 0.42 + Double(i) * 0.07)
                        .repeatForever(autoreverses: true)
                        .delay(Double(i) * 0.09),
                        value: phases[i]
                    )
            }
        }
        .frame(height: maxH)
        .onAppear {
            let targets: [Double] = [0.9, 0.4, 1.0, 0.6, 0.8]
            for i in 0..<count {
                DispatchQueue.main.asyncAfter(deadline: .now() + Double(i) * 0.05) {
                    phases[i] = targets[i]
                }
            }
        }
    }
}

// =========================================================
// HUDSpinner — circular progress indicator shown while processing
// =========================================================

struct HUDSpinner: View {

    @State private var rotating = false

    var body: some View {
        Circle()
            .trim(from: 0, to: 0.75)
            .stroke(
                Color(red: 0.686, green: 0.663, blue: 0.925),
                style: StrokeStyle(lineWidth: 1.8, lineCap: .round)
            )
            .frame(width: 13, height: 13)
            .rotationEffect(.degrees(rotating ? 360 : 0))
            .animation(
                .linear(duration: 0.85).repeatForever(autoreverses: false),
                value: rotating
            )
            .onAppear { rotating = true }
    }
}
