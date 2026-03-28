import SwiftUI

struct SettingsView: View {
    @State private var selectedLanguage = Config.targetLanguage
    @State private var syncStatus: String = ""

    // Inject the backend client so we can sync language to Python
    var backendClient: LocalBackendClient?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {

            Text("Whispr Settings")
                .font(.title2)
                .bold()

            Divider()

            // ── Hotkeys ───────────────────────────────────────
            Group {
                Label("Start recording:  Command + Shift + Space", systemImage: "mic")
                Label("Stop recording:   Command + Shift + S",     systemImage: "stop.circle")
            }
            .font(.subheadline)
            .foregroundColor(.secondary)

            Divider()

            // ── Output language ───────────────────────────────
            VStack(alignment: .leading, spacing: 8) {
                Text("Output language")
                    .font(.headline)

                Text("Transcribed text will be translated to this language.")
                    .font(.caption)
                    .foregroundColor(.secondary)

                HStack(spacing: 12) {
                    Picker("", selection: $selectedLanguage) {
                        ForEach(Config.supportedLanguages, id: \.self) { lang in
                            Text(lang).tag(lang)
                        }
                    }
                    .pickerStyle(.menu)
                    .frame(width: 160)
                    .onChange(of: selectedLanguage) { newValue in
                        Config.targetLanguage = newValue
                        syncStatus = "Saving..."
                        backendClient?.syncLanguageToBackend { success in
                            syncStatus = success ? "Saved" : "Saved locally"
                            // Clear status after 2 seconds
                            DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                                syncStatus = ""
                            }
                        }
                    }

                    if !syncStatus.isEmpty {
                        Text(syncStatus)
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
            }

            Divider()

            // ── Backend info ──────────────────────────────────
            Group {
                Text("Backend: local Python CLI")
                Text("Recording: temporary .m4a file")
            }
            .font(.caption)
            .foregroundColor(.secondary)

        }
        .padding()
        .frame(width: 420, height: 280)
        .onAppear {
            // Load language from backend on open to stay in sync
            backendClient?.fetchLanguageFromBackend { lang in
                if let lang = lang, Config.supportedLanguages.contains(lang) {
                    selectedLanguage    = lang
                    Config.targetLanguage = lang
                }
            }
        }
    }
}
