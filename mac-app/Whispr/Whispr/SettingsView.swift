import SwiftUI

struct LinkEntry: Identifiable {
    let id = UUID()
    var label: String
    var url: String
}

struct SettingsView: View {
    @State private var selectedLanguage   = Config.targetLanguage
    @State private var syncStatus: String = ""
    @State private var calendarEmail: String = "Not connected"

    // Quick Links
    @State private var links: [LinkEntry]  = []
    @State private var newLabel: String    = ""
    @State private var newURL: String      = ""
    @State private var linkStatus: String  = ""

    var backendClient: LocalBackendClient?

    var body: some View {
        ScrollView {
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

                // ── Quick Links ───────────────────────────────────
                VStack(alignment: .leading, spacing: 8) {
                    Text("Quick Links")
                        .font(.headline)

                    Text("Say the label during dictation to insert it as "Label (URL)".")
                        .font(.caption)
                        .foregroundColor(.secondary)

                    // Existing links
                    ForEach(links) { link in
                        HStack(spacing: 8) {
                            Text(link.label)
                                .font(.subheadline)
                                .frame(width: 100, alignment: .leading)
                            Text(link.url)
                                .font(.caption)
                                .foregroundColor(.secondary)
                                .lineLimit(1)
                                .truncationMode(.middle)
                            Spacer()
                            Button {
                                removeLink(link)
                            } label: {
                                Image(systemName: "minus.circle.fill")
                                    .foregroundColor(.red)
                            }
                            .buttonStyle(.plain)
                        }
                        .padding(.vertical, 2)
                    }

                    // Add new link
                    HStack(spacing: 6) {
                        TextField("Label (e.g. zoom link)", text: $newLabel)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 130)

                        TextField("https://...", text: $newURL)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 160)

                        Button("Add") {
                            addLink()
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                        .disabled(newLabel.isEmpty || newURL.isEmpty)
                    }

                    if !linkStatus.isEmpty {
                        Text(linkStatus)
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }

                Divider()

                // ── Google Calendar ───────────────────────────────
                VStack(alignment: .leading, spacing: 8) {
                    Text("Google Calendar")
                        .font(.headline)

                    HStack(spacing: 10) {
                        Image(systemName: calendarEmail == "Not connected"
                              ? "calendar.badge.exclamationmark"
                              : "calendar.badge.checkmark")
                            .foregroundColor(calendarEmail == "Not connected" ? .orange : .green)

                        Text(calendarEmail)
                            .font(.subheadline)
                            .foregroundColor(calendarEmail == "Not connected" ? .secondary : .primary)
                    }

                    if calendarEmail == "Not connected" || calendarEmail == "Connecting..." {
                        Button("Connect Google Calendar") { connectCalendar() }
                            .buttonStyle(.borderedProminent)
                            .controlSize(.small)
                            .disabled(calendarEmail == "Connecting...")
                    } else {
                        HStack(spacing: 8) {
                            Button("Switch account") { connectCalendar() }
                                .buttonStyle(.bordered)
                                .controlSize(.small)
                            Button("Disconnect") { disconnectCalendar() }
                                .buttonStyle(.bordered)
                                .controlSize(.small)
                                .foregroundColor(.red)
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
        }
        .frame(width: 460, height: 540)
        .onAppear {
            loadLinks()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                loadCurrentCalendarEmail()
            }
            backendClient?.fetchLanguageFromBackend { lang in
                if let lang = lang, Config.supportedLanguages.contains(lang) {
                    DispatchQueue.main.async {
                        selectedLanguage      = lang
                        Config.targetLanguage = lang
                    }
                }
            }
        }
    }

    // =========================================================
    // Quick Links helpers
    // =========================================================

    /// Load existing link snippets from backend
    private func loadLinks() {
        backendClient?.runPythonCommand(
            script: backendClient?.backendScriptPath?.replacingOccurrences(of: "app.py", with: "snippets.py") ?? "",
            arguments: ["cli", "list"]
        ) { result in
            guard case .success(let output) = result,
                  let data = output
                      .components(separatedBy: .newlines)
                      .compactMap { $0.data(using: .utf8) }
                      .first(where: { (try? JSONSerialization.jsonObject(with: $0)) != nil }),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let snippets = json["snippets"] as? [[String: Any]]
            else { return }

            let loaded = snippets.compactMap { s -> LinkEntry? in
                guard let trigger = s["trigger"] as? String,
                      let expansion = s["expansion"] as? String,
                      expansion.hasPrefix("http") else { return nil }
                let label = trigger
                let url   = expansion
                    .replacingOccurrences(of: "\\(trigger) (", with: "")
                    .replacingOccurrences(of: trigger + " (", with: "", options: .caseInsensitive)
                    .trimmingCharacters(in: CharacterSet(charactersIn: ")"))
                return LinkEntry(label: label, url: url.hasPrefix("http") ? url : expansion)
            }
            DispatchQueue.main.async { self.links = loaded }
        }
    }

    private func addLink() {
        let label     = newLabel.trimmingCharacters(in: .whitespacesAndNewlines)
        let url       = newURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !label.isEmpty, !url.isEmpty else { return }

        // Store as "Label (https://...)" so inline replacement looks natural
        let expansion = "\(label) (\(url))"

        backendClient?.runPythonCommand(
            script: backendClient?.backendScriptPath?.replacingOccurrences(of: "app.py", with: "snippets.py") ?? "",
            arguments: ["cli", "add", label, expansion]
        ) { result in
            DispatchQueue.main.async {
                if case .success = result {
                    self.links.append(LinkEntry(label: label, url: url))
                    self.newLabel  = ""
                    self.newURL    = ""
                    self.linkStatus = "Saved"
                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                        self.linkStatus = ""
                    }
                } else {
                    self.linkStatus = "Failed to save"
                }
            }
        }
    }

    private func removeLink(_ link: LinkEntry) {
        backendClient?.runPythonCommand(
            script: backendClient?.backendScriptPath?.replacingOccurrences(of: "app.py", with: "snippets.py") ?? "",
            arguments: ["cli", "remove", link.label]
        ) { result in
            DispatchQueue.main.async {
                if case .success = result {
                    self.links.removeAll { $0.id == link.id }
                }
            }
        }
    }

    // =========================================================
    // Calendar helpers
    // =========================================================

    private func loadCurrentCalendarEmail() {
        backendClient?.fetchCalendarEmail { email in
            DispatchQueue.main.async {
                calendarEmail = email ?? "Not connected"
            }
        }
    }

    private func connectCalendar() {
        DispatchQueue.main.async { calendarEmail = "Connecting..." }
        backendClient?.connectGoogleCalendar { email in
            DispatchQueue.main.async {
                calendarEmail = email ?? "Not connected"
            }
        }
    }

    private func disconnectCalendar() {
        backendClient?.disconnectGoogleCalendar { _ in
            DispatchQueue.main.async {
                calendarEmail = "Not connected"
            }
        }
    }
}