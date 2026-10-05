import AppKit
import Darwin

final class ReceiverDelegate: NSObject, NSApplicationDelegate {
    private var child: Process?
    private var stopping = false
    private let state = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".codex/move")
    func applicationDidFinishLaunching(_ notification: Notification) { launchReceiver() }
    private func launchReceiver() {
        guard !stopping else { return }
        do {
            let config = state.appendingPathComponent("config.json")
            let data = try Data(contentsOf: config)
            let settings = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            guard let python = settings?["runtime_python"] as? String else { throw NSError(domain:"Move", code:1, userInfo:[NSLocalizedDescriptionKey:"Missing runtime_python in Move configuration"]) }
            let script = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".codex/skills/move/scripts/move.py")
            let process = Process()
            process.executableURL = URL(fileURLWithPath: python)
            process.arguments = [script.path,"--config",config.path,"watch"]
            var environment = ProcessInfo.processInfo.environment
            environment["PATH"] = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            process.environment = environment
            let log = state.appendingPathComponent("receiver-native.log")
            if !FileManager.default.fileExists(atPath:log.path) { FileManager.default.createFile(atPath:log.path,contents:nil) }
            let output = try FileHandle(forWritingTo:log);output.seekToEndOfFile()
            process.standardOutput = output;process.standardError = output
            process.terminationHandler = { [weak self] _ in
                DispatchQueue.main.asyncAfter(deadline:.now()+10) { self?.launchReceiver() }
            }
            try process.run();child = process
        } catch {
            NSLog("Move receiver startup failed: %@",error.localizedDescription)
            DispatchQueue.main.asyncAfter(deadline:.now()+10) { [weak self] in self?.launchReceiver() }
        }
    }
    func applicationWillTerminate(_ notification:Notification) {
        stopping = true
        if let child = child,child.isRunning { child.terminate() }
    }
}
let app = NSApplication.shared
let delegate = ReceiverDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
signal(SIGTERM, SIG_IGN)
let termination = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
termination.setEventHandler { app.terminate(nil) }
termination.resume()
app.run()
