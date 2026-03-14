import SwiftUI
import AppKit

final class FloatingIndicator {
    private var indicatorWindow: NSWindow?

    func showIndicator() {
        DispatchQueue.main.async {
            guard self.indicatorWindow == nil else { return }

            let window = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 140, height: 48),
                styleMask: [.borderless, .nonactivatingPanel],
                backing: .buffered,
                defer: false
            )

            window.level = .floating
            window.isOpaque = false
            window.backgroundColor = .clear
            window.hasShadow = true
            window.collectionBehavior = [.canJoinAllSpaces, .transient]

            let (_, mode) = AppManager.shared.activeAppDetector.getActiveAppAndMode()
            let view = IndicatorView(mode: mode)
            window.contentView = NSHostingView(rootView: view)

            let mouseLocation = NSEvent.mouseLocation
            if let screen = NSScreen.main {
                let screenFrame = screen.frame
                let origin = NSPoint(x: mouseLocation.x + 20, y: screenFrame.height - mouseLocation.y - 68)
                window.setFrameOrigin(origin)
            }

            self.indicatorWindow = window
            window.orderFrontRegardless()
        }
    }

    func hideIndicator() {
        DispatchQueue.main.async {
            self.indicatorWindow?.close()
            self.indicatorWindow = nil
        }
    }
}

struct IndicatorView: View {
    let mode: TranscriptionMode

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 10)
                .fill(Color.black.opacity(0.85))

            VStack(spacing: 4) {
                HStack(spacing: 6) {
                    Image(systemName: "mic.fill")
                        .foregroundColor(.red)
                    Text("Listening")
                        .foregroundColor(.white)
                        .font(.system(size: 14, weight: .semibold))
                }

                Text(mode.rawValue.capitalized)
                    .foregroundColor(.gray)
                    .font(.system(size: 11))
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
        .frame(width: 140, height: 48)
    }
}
