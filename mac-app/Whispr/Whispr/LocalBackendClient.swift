import Foundation
import Combine

final class LocalBackendClient: ObservableObject {
    @Published var isBackendAvailable = false

    private let backendScriptPath = "/Users/yanbowang/Comp9900_project_testversion/backend/app.py"
    private let pythonPath = "/Users/yanbowang/opt/anaconda3/bin/python3.11"
    private let timeout: TimeInterval = 20

    init() {
        checkBackendAvailability()
    }

    private func checkBackendAvailability() {
        let fm = FileManager.default
        let pythonExists = fm.fileExists(atPath: pythonPath)
        let scriptExists = fm.fileExists(atPath: backendScriptPath)

        NSLog("python exists: \(pythonExists) -> \(pythonPath)")
        NSLog("script exists: \(scriptExists) -> \(backendScriptPath)")

        isBackendAvailable = pythonExists && scriptExists
    }

    func transcribeAudio(
        fileURL: URL,
        appName: String,
        mode: TranscriptionMode,
        completion: @escaping (Result<String, Error>) -> Void
    ) {
        guard isBackendAvailable else {
            completion(.failure(NSError(domain: "LocalBackendClient", code: -1, userInfo: [NSLocalizedDescriptionKey: "Python backend script not found"])))
            return
        }

        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: self.pythonPath)

            process.arguments = [
                self.backendScriptPath,
                "cli",
                fileURL.path,
                mode.rawValue,
                self.contextFromAppName(appName),
                ""
            ]

            let outputPipe = Pipe()
            let errorPipe = Pipe()
            process.standardOutput = outputPipe
            process.standardError = errorPipe

            do {
                try process.run()
            } catch {
                completion(.failure(error))
                return
            }

            let deadline = Date().addingTimeInterval(self.timeout)
            while process.isRunning && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.1)
            }

            if process.isRunning {
                process.terminate()
                completion(.failure(NSError(domain: "LocalBackendClient", code: -2, userInfo: [NSLocalizedDescriptionKey: "Transcription timed out"])))
                return
            }

            let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()

            let outputString = String(data: outputData, encoding: .utf8) ?? ""
            let errorString = String(data: errorData, encoding: .utf8) ?? ""

            if !errorString.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                NSLog("Backend stderr: \(errorString)")
            }

            if process.terminationStatus != 0 {
                completion(.failure(NSError(domain: "LocalBackendClient", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: errorString.isEmpty ? "Backend exited with code \(process.terminationStatus)" : errorString])))
                return
            }

            let trimmed = outputString.trimmingCharacters(in: .whitespacesAndNewlines)

            if let data = trimmed.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let ok = json["ok"] as? Bool,
               ok,
               let finalText = json["final_text"] as? String {
                completion(.success(finalText))
                return
            }

            if !trimmed.isEmpty {
                completion(.success(trimmed))
            } else {
                completion(.failure(NSError(domain: "LocalBackendClient", code: -4, userInfo: [NSLocalizedDescriptionKey: "No output from backend"])))
            }
        }
    }

    private func contextFromAppName(_ appName: String) -> String {
        switch appName {
        case "Mail", "Microsoft Outlook", "Spark":
            return "email"
        case "Messages", "Slack", "Discord", "Telegram", "WhatsApp":
            return "chat"
        case "Visual Studio Code", "Code", "Xcode", "Terminal", "iTerm2", "PyCharm":
            return "code"
        default:
            return "generic"
        }
    }
}
