// AtomOra Floating Chat Panel
// Native SwiftUI panel with dark frosted-glass effect.
// Communicates with Python backend via stdin (JSON lines).

import SwiftUI
import AppKit

// MARK: - Models

struct ChatMessage: Identifiable, Equatable {
    let id = UUID()
    let role: String
    let text: String
}

struct ChatAction: Codable {
    let action: String
    let role: String?
    let text: String?
}

// MARK: - State

class ChatState: ObservableObject {
    @Published var messages: [ChatMessage] = []

    func append(role: String, text: String) {
        DispatchQueue.main.async {
            self.messages.append(ChatMessage(role: role, text: text))
        }
    }

    func clear() {
        DispatchQueue.main.async {
            self.messages.removeAll()
        }
    }
}

// MARK: - Views

struct MessageBubble: View {
    let message: ChatMessage

    private var roleLabel: String {
        switch message.role {
        case "user":      return "You"
        case "assistant": return "AtomOra"
        default:          return "System"
        }
    }

    private var roleIcon: String {
        switch message.role {
        case "user":      return "mic.fill"
        case "assistant": return "atom"
        default:          return "gearshape"
        }
    }

    private var accentColor: Color {
        switch message.role {
        case "user":      return Color(red: 0.35, green: 0.78, blue: 1.0)
        case "assistant": return Color(red: 0.40, green: 0.95, blue: 0.55)
        default:          return Color.white.opacity(0.4)
        }
    }

    private var textOpacity: Double {
        message.role == "system" ? 0.5 : 0.88
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Role header
            HStack(spacing: 6) {
                Image(systemName: roleIcon)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundColor(accentColor)
                Text(roleLabel)
                    .font(.system(size: 12, weight: .bold, design: .rounded))
                    .foregroundColor(accentColor)
            }

            // Message body
            Text(message.text)
                .font(.system(size: 13, design: .default))
                .foregroundColor(.white.opacity(textOpacity))
                .textSelection(.enabled)
                .lineSpacing(4)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(.white.opacity(0.06))
        )
    }
}

struct TitleBar: View {
    var body: some View {
        HStack {
            Spacer()
            Text("AtomOra")
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .foregroundColor(.white.opacity(0.5))
            Spacer()
        }
        .padding(.top, 8)
        .padding(.bottom, 4)
    }
}

struct ChatContentView: View {
    @ObservedObject var state: ChatState

    var body: some View {
        VStack(spacing: 0) {
            TitleBar()

            Divider()
                .background(Color.white.opacity(0.1))

            ScrollViewReader { proxy in
                ScrollView(.vertical, showsIndicators: false) {
                    LazyVStack(spacing: 12) {
                        ForEach(state.messages) { msg in
                            MessageBubble(message: msg)
                                .id(msg.id)
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 12)
                }
                .onChange(of: state.messages.count) {
                    if let last = state.messages.last {
                        withAnimation(.easeOut(duration: 0.3)) {
                            proxy.scrollTo(last.id, anchor: .bottom)
                        }
                    }
                }
            }
        }
        .frame(minWidth: 320, idealWidth: 440, minHeight: 300, idealHeight: 580)
        .background(.ultraThinMaterial)
        .preferredColorScheme(.dark)
    }
}

// MARK: - App Delegate

class PanelDelegate: NSObject, NSApplicationDelegate {
    var panel: NSPanel!
    let chatState = ChatState()

    func applicationDidFinishLaunching(_ notification: Notification) {
        setupPanel()
        startStdinReader()
    }

    private func setupPanel() {
        let w: CGFloat = 420
        let h: CGFloat = 560

        panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: w, height: h),
            styleMask: [
                .titled,
                .closable,
                .resizable,
                .fullSizeContentView,
                .nonactivatingPanel,
            ],
            backing: .buffered,
            defer: false
        )

        if let screen = NSScreen.main {
            let x = screen.frame.width - w - 24
            let y = screen.frame.height - h - 80
            panel.setFrameOrigin(NSPoint(x: x, y: y))
        }

        // Force dark appearance
        panel.appearance = NSAppearance(named: .darkAqua)

        panel.title = "AtomOra"
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isMovableByWindowBackground = true
        panel.hidesOnDeactivate = false
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = true
        panel.minSize = NSSize(width: 300, height: 250)

        // Round the window corners
        panel.contentView?.wantsLayer = true
        panel.contentView?.layer?.cornerRadius = 14
        panel.contentView?.layer?.masksToBounds = true

        let hostingView = NSHostingView(rootView: ChatContentView(state: chatState))
        panel.contentView = hostingView

        panel.makeKeyAndOrderFront(nil)
    }

    private func startStdinReader() {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let decoder = JSONDecoder()
            while let line = readLine(strippingNewline: true) {
                guard !line.isEmpty,
                      let data = line.data(using: .utf8),
                      let action = try? decoder.decode(ChatAction.self, from: data)
                else { continue }

                switch action.action {
                case "append":
                    if let role = action.role, let text = action.text {
                        self?.chatState.append(role: role, text: text)
                    }
                case "clear":
                    self?.chatState.clear()
                case "show":
                    DispatchQueue.main.async {
                        self?.panel.makeKeyAndOrderFront(nil)
                    }
                case "hide":
                    DispatchQueue.main.async {
                        self?.panel.orderOut(nil)
                    }
                default:
                    break
                }
            }
            DispatchQueue.main.async {
                NSApplication.shared.terminate(nil)
            }
        }
    }
}

// MARK: - Entry

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = PanelDelegate()
app.delegate = delegate
app.run()
