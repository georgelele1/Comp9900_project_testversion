import Foundation
import Combine

final class LocalBackendClient: ObservableObject {
    @Published var isBackendAvailable = false

    private let pythonCandidates = [
        "/Users/yanbowang/opt/anaconda3/bin/python3.11",
        "/Users/yanbowang/opt/anaconda3/bin/python3",
        "/opt/homebrew/bin/python3.11",
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3.11",
        "/usr/local/bin/python3",
        "/usr/bin/python3"
    ]

    private let timeout: TimeInterval = 300

    private var pythonPath: String?
    private var backendScriptPath: String?

    init() {
        checkBackendAvailability()
    }

    private func checkBackendAvailability() {
        let fm = FileManager.default

        pythonPath = pythonCandidates.first(where: { fm.fileExists(atPath: $0) })

        if let root = findProjectRoot() {
            let candidate = root.appendingPathComponent("backend/app.py").path
            if fm.fileExists(atPath: candidate) {
                backendScriptPath = candidate
            }
        }

        print("python path =", pythonPath ?? "nil")
        print("backend path =", backendScriptPath ?? "nil")

        isBackendAvailable = (pythonPath != nil && backendScriptPath != nil)
    }

    private func findProjectRoot() -> URL? {
        let fm = FileManager.default
        var current = URL(fileURLWithPath: fm.currentDirectoryPath)

        for _ in 0..<8 {
            let backendCandidate = current.appendingPathComponent("backend/app.py").path
            if fm.fileExists(atPath: backendCandidate) {
                return current
            }
            current.deleteLastPathComponent()
        }

        let fallback = URL(fileURLWithPath: "/Users/yanbowang/Comp9900_project_testversion")
        let fallbackBackend = fallback.appendingPathComponent("backend/app.py").path
        if fm.fileExists(atPath: fallbackBackend) {
            return fallback
        }

        return nil
    }

    func transcribeAudio(
        fileURL: URL,
        appName: String,
        mode: TranscriptionMode,
        completion: @escaping (Result<String, Error>) -> Void
    ) {
        guard let pythonPath, let backendScriptPath else {
            completion(.failure(
                NSError(
                    domain: "LocalBackendClient",
                    code: -1,
                    userInfo: [NSLocalizedDescriptionKey: "Python or backend script not found"]
                )
            ))
            return
        }

        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.currentDirectoryURL = URL(fileURLWithPath: backendScriptPath).deletingLastPathComponent()
            process.executableURL = URL(fileURLWithPath: pythonPath)
            process.arguments = [
                backendScriptPath,
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
                print("file exists before run =", FileManager.default.fileExists(atPath: fileURL.path))
                print("Launching backend...")
                print("python =", pythonPath)
                print("script =", backendScriptPath)
                print("audio =", fileURL.path)
                print("args =", process.arguments ?? [])
                print("cwd =", process.currentDirectoryURL?.path ?? "nil")
                try process.run()
            } catch {
                DispatchQueue.main.async {
                    completion(.failure(error))
                }
                return
            }

            let group = DispatchGroup()
            group.enter()

            DispatchQueue.global(qos: .userInitiated).async {
                process.waitUntilExit()
                group.leave()
            }

            let waitResult = group.wait(timeout: .now() + self.timeout)
            if waitResult == .timedOut {
                process.terminate()
                DispatchQueue.main.async {
                    completion(.failure(
                        NSError(
                            domain: "LocalBackendClient",
                            code: -2,
                            userInfo: [NSLocalizedDescriptionKey: "Transcription timed out"]
                        )
                    ))
                }
                return
            }

            let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()

            let outputString = String(data: outputData, encoding: .utf8) ?? ""
            let errorString = String(data: errorData, encoding: .utf8) ?? ""

            print("STDOUT:", outputString)
            print("STDERR:", errorString)
            print("Exit code:", process.terminationStatus)

            DispatchQueue.main.async {
                let trimmed = outputString.trimmingCharacters(in: .whitespacesAndNewlines)

                guard !trimmed.isEmpty else {
                    completion(.failure(
                        NSError(
                            domain: "LocalBackendClient",
                            code: -4,
                            userInfo: [NSLocalizedDescriptionKey: "No output from backend"]
                        )
                    ))
                    return
                }

                let lines = trimmed
                    .components(separatedBy: .newlines)
                    .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                    .filter { !$0.isEmpty }

                guard let jsonLine = lines.last(where: { $0.hasPrefix("{") && $0.hasSuffix("}") }) else {
                    completion(.failure(
                        NSError(
                            domain: "LocalBackendClient",
                            code: -6,
                            userInfo: [NSLocalizedDescriptionKey: "No JSON line found in backend output: \(trimmed)"]
                        )
                    ))
                    return
                }

                guard let data = jsonLine.data(using: .utf8) else {
                    completion(.failure(
                        NSError(
                            domain: "LocalBackendClient",
                            code: -7,
                            userInfo: [NSLocalizedDescriptionKey: "Failed to encode backend JSON line"]
                        )
                    ))
                    return
                }

                do {
                    let response = try JSONDecoder().decode(BackendResponse.self, from: data)

                    if process.terminationStatus == 0 {
                        completion(.success(response.output))
                    } else {
                        completion(.failure(
                            NSError(
                                domain: "LocalBackendClient",
                                code: Int(process.terminationStatus),
                                userInfo: [
                                    NSLocalizedDescriptionKey: errorString.isEmpty
                                        ? "Backend exited with code \(process.terminationStatus)"
                                        : errorString
                                ]
                            )
                        ))
                    }
                } catch {
                    completion(.failure(
                        NSError(
                            domain: "LocalBackendClient",
                            code: -8,
                            userInfo: [NSLocalizedDescriptionKey: "Invalid JSON line from backend: \(jsonLine)"]
                        )
                    ))
                }
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
