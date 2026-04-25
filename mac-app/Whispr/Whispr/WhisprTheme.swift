import SwiftUI
import AppKit

enum WhisprTheme {
    static let accent = Color(red: 0.498, green: 0.467, blue: 0.867)
    static let accent2 = Color(red: 0.36, green: 0.62, blue: 0.96)
    static let softPurple = Color(red: 0.498, green: 0.467, blue: 0.867).opacity(0.14)
    static let card = Color(NSColor.textBackgroundColor).opacity(0.92)
    static let panel = Color(NSColor.controlBackgroundColor)
    static let border = Color.secondary.opacity(0.14)

    static var appBackground: some View {
        ZStack {
            LinearGradient(
                colors: [
                    accent.opacity(0.16),
                    accent2.opacity(0.10),
                    Color(NSColor.windowBackgroundColor)
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )

            Image(systemName: "waveform")
                .font(.system(size: 220, weight: .light))
                .foregroundColor(accent.opacity(0.045))
                .rotationEffect(.degrees(-12))
                .offset(x: 260, y: -180)
        }
        .ignoresSafeArea()
    }
}

struct WhisprCard<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .padding(18)
            .background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(WhisprTheme.border, lineWidth: 0.8)
            )
            .shadow(color: .black.opacity(0.06), radius: 14, x: 0, y: 6)
    }
}
