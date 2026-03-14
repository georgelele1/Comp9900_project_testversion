import SwiftUI

struct SettingsView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Whispr Settings")
                .font(.title2)
                .bold()

            Text("Start: Command + Shift + Space")
            Text("Stop: Command + Shift + S")
            Text("Backend: local Python CLI")
            Text("Recording: temporary .m4a file")
        }
        .padding()
        .frame(width: 420, height: 180)
    }
}
