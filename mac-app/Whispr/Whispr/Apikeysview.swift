import SwiftUI

struct APIKeysView: View {

    @State private var selectedModel      : String  = AppManager.shared.localBackendClient.activeModel
    @State private var apiKeyInput        : String  = ""
    @State private var hasStoredKey       : Bool    = false
    @State private var isLoadingModel     : Bool    = false
    @State private var isSavingKey        : Bool    = false
    @State private var statusMessage      : String  = ""
    @State private var isError            : Bool    = false
    @State private var isLoadingBalance   : Bool    = false
    @State private var balanceError       : String? = nil
    @State private var lastCost           : Double? = nil
    @State private var coBalance          : Double? = nil
    @State private var coUsed             : Double? = nil
    @State private var oaiBalance         : Double? = nil
    @State private var oaiPlan            : String? = nil

    var backendClient: LocalBackendClient?
    private let accent = Color(red: 0.498, green: 0.467, blue: 0.867)

    private var needsKey: Bool { Config.requiresAPIKey(selectedModel) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    balanceSection
                    modelPicker
                    if needsKey { keySection }
                }
                .padding(24)
            }
        }
        .frame(width: 560, height: needsKey ? 460 : 360)
        .onAppear {
            loadCurrentState()
            loadBalance()
        }
    }

    // MARK: - Header

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Model & API Key").font(.title2).bold()
                Text("Gemini models are included via connectonion — no API key needed. OpenAI models require your own key.")
                    .font(.caption).foregroundColor(.secondary)
            }
            Spacer()
            if isLoadingModel { ProgressView().scaleEffect(0.8) }
        }
        .padding()
    }

    // MARK: - Model picker

    private var modelPicker: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionLabel("Choose a model", icon: "cpu")

            ForEach(Config.modelsByProvider, id: \.provider) { group in
                VStack(alignment: .leading, spacing: 8) {

                    // Provider label
                    HStack(spacing: 6) {
                        Image(systemName: group.provider == "Google" ? "star.fill" : "key")
                            .font(.system(size: 10))
                            .foregroundColor(providerColor(group.provider))
                        Text(group.provider)
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(providerColor(group.provider))
                        if group.provider == "Google" {
                            Text("included via connectonion")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                                .padding(.horizontal, 6).padding(.vertical, 2)
                                .background(Color.secondary.opacity(0.1))
                                .cornerRadius(4)
                        }
                    }

                    // Model pills
                    HStack(spacing: 8) {
                        ForEach(group.models) { option in
                            ModelPill(
                                option:     option,
                                isSelected: selectedModel == option.id,
                                accent:     accent
                            ) {
                                selectModel(option.id)
                            }
                        }
                    }
                }
            }
        }
    }

    // MARK: - API key section (OpenAI only)

    private var keySection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Divider()
            sectionLabel("OpenAI API Key", icon: "lock")

            if hasStoredKey {
                // Key already saved — show status + option to replace or remove
                HStack(spacing: 10) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(.green)
                    Text("API key stored")
                        .font(.subheadline)
                    Spacer()
                    Button("Replace") { hasStoredKey = false; apiKeyInput = "" }
                        .buttonStyle(.bordered).controlSize(.small)
                    Button("Remove") { removeKey() }
                        .buttonStyle(.bordered).controlSize(.small)
                        .tint(.red)
                }
                .padding(12)
                .background(Color.green.opacity(0.06))
                .cornerRadius(8)
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.green.opacity(0.2), lineWidth: 0.5))
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Paste your OpenAI API key below. It's stored locally in a .env file — never sent anywhere else.")
                        .font(.caption).foregroundColor(.secondary)

                    HStack(spacing: 10) {
                        SecureField("sk-…", text: $apiKeyInput)
                            .textFieldStyle(.roundedBorder)
                            .frame(maxWidth: .infinity)

                        Button(action: saveKey) {
                            if isSavingKey {
                                ProgressView().scaleEffect(0.75).frame(width: 60, height: 22)
                            } else {
                                Text("Save")
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(accent)
                        .disabled(apiKeyInput.trimmingCharacters(in: .whitespaces).isEmpty || isSavingKey)
                    }
                }
            }

            if !statusMessage.isEmpty {
                HStack(spacing: 4) {
                    Image(systemName: isError ? "xmark.circle.fill" : "checkmark.circle.fill")
                        .font(.system(size: 11))
                        .foregroundColor(isError ? .red : .green)
                    Text(statusMessage)
                        .font(.caption)
                        .foregroundColor(isError ? .red : .green)
                }
            }
        }
    }

    // MARK: - Balance section

    private var balanceSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionLabel("Usage & balance", icon: "coloncurrencysign.circle")

            HStack(spacing: 10) {
                // Last call cost
                balanceCard(
                    title: "Last call",
                    value: lastCost.map { $0 < 0.0001 ? "<$0.0001" : String(format: "$%.4f", $0) } ?? "—",
                    color: .primary
                )

                // Connectonion balance
                balanceCard(
                    title: "Connectonion",
                    value: coBalance.map { String(format: "$%.2f", $0) } ?? "—",
                    subtitle: coUsed.map { String(format: "$%.4f used", $0) },
                    color: (coBalance ?? 0) < 1 ? .orange : .green
                )

                // OpenAI balance
                balanceCard(
                    title: "OpenAI",
                    value: oaiBalance.map { String(format: "$%.2f", $0) } ?? (oaiPlan ?? (hasStoredKey ? "—" : "No key")),
                    subtitle: oaiPlan != nil && oaiBalance == nil ? oaiPlan : nil,
                    color: oaiBalance == nil ? .secondary : ((oaiBalance ?? 0) < 2 ? .orange : .green)
                )

                if isLoadingBalance {
                    ProgressView().scaleEffect(0.7)
                } else {
                    Button { loadBalance() } label: {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 12))
                            .foregroundColor(.secondary)
                    }
                    .buttonStyle(.plain)
                    .help("Refresh balances")
                }
            }
        }
    }

    private func balanceCard(title: String, value: String, subtitle: String? = nil, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.caption).foregroundColor(.secondary)
            Text(value)
                .font(.system(size: 14, weight: .semibold))
                .foregroundColor(color)
            if let subtitle {
                Text(subtitle).font(.caption2).foregroundColor(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(Color(NSColor.controlBackgroundColor))
        .cornerRadius(8)
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.15), lineWidth: 0.5))
    }

    // MARK: - Helpers

    private func sectionLabel(_ text: String, icon: String) -> some View {
        Label(text, systemImage: icon)
            .font(.system(size: 11, weight: .semibold))
            .foregroundColor(.secondary)
            .textCase(.uppercase)
            .tracking(0.4)
    }

    private func providerColor(_ provider: String) -> Color {
        provider == "Google" ? Color(red: 0.26, green: 0.52, blue: 0.96) : Color(red: 0.07, green: 0.73, blue: 0.49)
    }

    // MARK: - Actions

    private func loadBalance() {
        isLoadingBalance = true
        balanceError     = nil
        backendClient?.fetchBalance { result, err in
            DispatchQueue.main.async {
                self.isLoadingBalance = false
                self.coBalance        = result?.connectonionBalance
                self.coUsed           = result?.connectonionUsed
                self.oaiBalance       = result?.openAIBalance
                self.oaiPlan          = result?.openAIPlan
                self.balanceError     = result == nil ? (err ?? "Unavailable") : nil
            }
        }
    }

    private func loadCurrentState() {
        // Sync last known values from AppManager
        lastCost   = AppManager.shared.lastCost
        coBalance  = AppManager.shared.lastConnectonionBalance
        oaiBalance = AppManager.shared.lastOpenAIBalance
        oaiPlan    = AppManager.shared.lastOpenAIPlan

        isLoadingModel = true
        backendClient?.fetchModelFromBackend { model in
            DispatchQueue.main.async {
                // Fix: fall back to activeModel instead of defaultModel so
                // the picker never resets to Gemini if the backend returns nil
                self.selectedModel  = model ?? AppManager.shared.localBackendClient.activeModel
                self.isLoadingModel = false
            }
        }
        backendClient?.checkAPIKeyExists { exists in
            DispatchQueue.main.async { self.hasStoredKey = exists }
        }
        if coBalance == nil { loadBalance() }
    }

    private func selectModel(_ modelID: String) {
        guard modelID != selectedModel else { return }
        selectedModel = modelID
        backendClient?.setModelOnBackend(modelID) { _ in }
        // If switching away from OpenAI, clear key state display
        if !Config.requiresAPIKey(modelID) {
            statusMessage = ""
        }
    }

    private func saveKey() {
        let key = apiKeyInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty else { return }
        isSavingKey = true
        backendClient?.saveAPIKey(key) { success in
            DispatchQueue.main.async {
                self.isSavingKey    = false
                self.isError        = !success
                self.statusMessage  = success ? "Key saved" : "Failed to save key"
                if success {
                    self.hasStoredKey = true
                    self.apiKeyInput  = ""
                    // Fix: re-persist the selected OpenAI model after saving the key
                    // so the backend doesn't silently revert to its default
                    if Config.requiresAPIKey(self.selectedModel) {
                        self.backendClient?.setModelOnBackend(self.selectedModel) { _ in }
                    }
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 3) { self.statusMessage = "" }
            }
        }
    }

    private func removeKey() {
        backendClient?.removeAPIKey { success in
            DispatchQueue.main.async {
                if success { self.hasStoredKey = false }
                self.isError       = !success
                self.statusMessage = success ? "Key removed" : "Failed to remove key"
                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { self.statusMessage = "" }
            }
        }
    }
}

// MARK: - ModelPill

private struct ModelPill: View {
    let option    : Config.ModelOption
    let isSelected: Bool
    let accent    : Color
    let action    : () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 12))
                    .foregroundColor(isSelected ? accent : .secondary)
                Text(option.label)
                    .font(.system(size: 12))
                    .foregroundColor(isSelected ? .primary : .secondary)
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(isSelected ? accent.opacity(0.08) : Color(NSColor.controlBackgroundColor))
            .cornerRadius(8)
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(isSelected ? accent : Color.secondary.opacity(0.2),
                            lineWidth: isSelected ? 1 : 0.5)
            )
        }
        .buttonStyle(.plain)
    }
}
