import AVFoundation
import SwiftUI
import UIKit
import VisionKit

/// Scans one QR code and hands back its text. Uses VisionKit's `DataScannerViewController`
/// where the device supports it, an `AVCaptureSession` with a metadata output otherwise, and
/// offers manual entry when there is no camera (a simulator) or no permission.
struct QRScannerView: View {
    let onScan: (String) -> Void
    let onManualEntry: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var access = AVCaptureDevice.authorizationStatus(for: .video)

    private var hasCamera: Bool {
        AVCaptureDevice.default(for: .video) != nil
    }

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Scan Pairing Code")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Cancel") { dismiss() }
                    }
                }
        }
        .task {
            if access == .notDetermined && hasCamera {
                _ = await AVCaptureDevice.requestAccess(for: .video)
                access = AVCaptureDevice.authorizationStatus(for: .video)
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if !hasCamera {
            unavailable(
                "No Camera",
                "This device has no camera. Type the address and code the Mac shows instead.")
        } else if access == .denied || access == .restricted {
            unavailable(
                "Camera Access Is Off",
                "Allow the camera for Family Office in Settings, or type the code instead.")
        } else if access == .authorized {
            ZStack(alignment: .bottom) {
                if DataScannerViewController.isSupported && DataScannerViewController.isAvailable {
                    DataScanner(onScan: onScan)
                } else {
                    CaptureScanner(onScan: onScan)
                }
                Text("Point the camera at the code in Settings > Devices on the Mac.")
                    .font(.callout)
                    .multilineTextAlignment(.center)
                    .padding(12)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
                    .padding(20)
            }
            .ignoresSafeArea(edges: .bottom)
        } else {
            ProgressView()
        }
    }

    private func unavailable(_ title: String, _ text: String) -> some View {
        ContentUnavailableView {
            Label(title, systemImage: "camera")
        } description: {
            Text(text)
        } actions: {
            Button("Enter Code Manually", action: onManualEntry)
                .buttonStyle(.borderedProminent)
        }
    }
}

/// VisionKit's live scanner, limited to QR codes; reports the first payload once.
private struct DataScanner: UIViewControllerRepresentable {
    let onScan: (String) -> Void

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let scanner = DataScannerViewController(
            recognizedDataTypes: [.barcode(symbologies: [.qr])],
            qualityLevel: .balanced,
            isHighlightingEnabled: true)
        scanner.delegate = context.coordinator
        try? scanner.startScanning()
        return scanner
    }

    func updateUIViewController(_ controller: DataScannerViewController, context: Context) {}

    static func dismantleUIViewController(_ controller: DataScannerViewController, coordinator: Coordinator) {
        controller.stopScanning()
    }

    func makeCoordinator() -> Coordinator { Coordinator(onScan: onScan) }

    @MainActor
    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        private let onScan: (String) -> Void
        private var done = false

        init(onScan: @escaping (String) -> Void) {
            self.onScan = onScan
        }

        func dataScanner(
            _ dataScanner: DataScannerViewController, didAdd addedItems: [RecognizedItem],
            allItems: [RecognizedItem]
        ) {
            for item in addedItems {
                if case .barcode(let barcode) = item, let text = barcode.payloadStringValue {
                    report(text, from: dataScanner)
                    return
                }
            }
        }

        private func report(_ text: String, from scanner: DataScannerViewController) {
            guard !done else { return }
            done = true
            scanner.stopScanning()
            onScan(text)
        }
    }
}

/// The fallback: an `AVCaptureSession` with a QR metadata output and a preview layer.
private struct CaptureScanner: UIViewControllerRepresentable {
    let onScan: (String) -> Void

    func makeUIViewController(context: Context) -> CaptureViewController {
        CaptureViewController(onScan: onScan)
    }

    func updateUIViewController(_ controller: CaptureViewController, context: Context) {}
}

private final class CaptureViewController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    private let onScan: (String) -> Void
    private let capture = CaptureSession()
    private var session: AVCaptureSession { capture.session }
    private var preview: AVCaptureVideoPreviewLayer?
    private var done = false

    init(onScan: @escaping (String) -> Void) {
        self.onScan = onScan
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) { nil }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        guard let camera = AVCaptureDevice.default(for: .video),
            let input = try? AVCaptureDeviceInput(device: camera), session.canAddInput(input)
        else { return }
        session.addInput(input)
        let output = AVCaptureMetadataOutput()
        guard session.canAddOutput(output) else { return }
        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]
        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        view.layer.addSublayer(layer)
        preview = layer
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        preview?.frame = view.bounds
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        capture.start()
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        capture.stop()
    }

    nonisolated func metadataOutput(
        _ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject],
        from connection: AVCaptureConnection
    ) {
        let texts = metadataObjects.compactMap { ($0 as? AVMetadataMachineReadableCodeObject)?.stringValue }
        guard let text = texts.first else { return }
        // The delegate queue is the main queue.
        MainActor.assumeIsolated {
            guard !done else { return }
            done = true
            capture.stop()
            onScan(text)
        }
    }
}

/// The capture session, started and stopped on its own serial queue as AVFoundation asks;
/// it is configured once on the main thread before the first start.
private final class CaptureSession: @unchecked Sendable {
    let session = AVCaptureSession()
    private let queue = DispatchQueue(label: "com.familyoffice.phone.capture")

    func start() {
        queue.async { [self] in
            if !session.isRunning { session.startRunning() }
        }
    }

    func stop() {
        queue.async { [self] in
            if session.isRunning { session.stopRunning() }
        }
    }
}
