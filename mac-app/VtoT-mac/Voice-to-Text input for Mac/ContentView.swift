import SwiftUI

struct TextResponse: Decodable {
    let text: String
}

struct ContentView: View {
    @State private var statusText = "Ready"
    @StateObject private var audio = AudioRecorder()

    var body: some View {
        VStack(spacing: 16) {
            Text("Whispr").font(.largeTitle)
            Text(statusText)
                .font(.headline)
                .multilineTextAlignment(.center)

            HStack(spacing: 12) {

                Button(audio.isRecording ? "Stop Recording" : "Start Recording") {
                    if audio.isRecording {
                        audio.stopRecording()
                        if let url = audio.outputURL {
                            statusText = "Saved:\n\(url.lastPathComponent)\n\(url.path)"
                        } else {
                            statusText = "No file URL"
                        }
                    } else {
                        do {
                            try audio.startRecording()
                            statusText = "Recording… speak now"
                        } catch {
                            statusText = "Record failed: \(error.localizedDescription)"
                        }
                    }
                }

                Button("Transcribe") {
                    Task { await uploadRecording() }
                }
            }
        }
        .frame(width: 560, height: 260)
        .padding()
    }

    @MainActor
    private func uploadRecording() async {
        guard let fileURL = audio.outputURL else {
            statusText = "No recording file"
            return
        }

        guard let backendURL = URL(string: "http://127.0.0.1:5055/transcribe") else {
            statusText = "Invalid backend URL"
            return
        }

        do {
            let fileData = try Data(contentsOf: fileURL)

            var request = URLRequest(url: backendURL)
            request.httpMethod = "POST"

            let boundary = "Boundary-\(UUID().uuidString)"
            request.setValue("multipart/form-data; boundary=\(boundary)",
                             forHTTPHeaderField: "Content-Type")

            var body = Data()

            // (Optional) extra fields if your backend accepts them
            body.appendFormField(named: "mode", value: "clean", boundary: boundary)
            body.appendFormField(named: "context", value: "generic", boundary: boundary)
            body.appendFormField(named: "prompt", value: "", boundary: boundary)

            // ✅ Correct: upload as .m4a
            body.append("--\(boundary)\r\n")
            body.append("Content-Disposition: form-data; name=\"file\"; filename=\"whispr_recording.m4a\"\r\n")
            body.append("Content-Type: audio/mp4\r\n\r\n")
            body.append(fileData)
            body.append("\r\n")
            body.append("--\(boundary)--\r\n")

            request.httpBody = body

            statusText = "Uploading…"

            let (data, response) = try await URLSession.shared.data(for: request)

            guard let http = response as? HTTPURLResponse else {
                statusText = "No HTTP response"
                return
            }

            guard (200...299).contains(http.statusCode) else {
                let errBody = String(data: data, encoding: .utf8) ?? "(no body)"
                statusText = "Backend error: \(http.statusCode)\n\(errBody)"
                return
            }

            let decoded = try JSONDecoder().decode(TextResponse.self, from: data)
            statusText = "Transcription:\n\(decoded.text)"

        } catch {
            statusText = "Upload failed: \(error.localizedDescription)"
        }
    }
}

// MARK: - Multipart helpers
private extension Data {
    mutating func append(_ string: String) {
        if let data = string.data(using: .utf8) { append(data) }
    }

    mutating func appendFormField(named name: String, value: String, boundary: String) {
        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n")
        append(value)
        append("\r\n")
    }
}
