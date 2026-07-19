import SwiftUI

struct ChatView: View {
    @ObservedObject var settings: ConnectionSettingsStore
    @StateObject private var viewModel = ChatViewModel()
    @State private var draft = ""
    @State private var showsSettings = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                connectionBar
                Divider()
                messageList
                Divider()
                composer
            }
            .navigationTitle("PETIT")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showsSettings = true
                    } label: {
                        Image(systemName: "gearshape")
                    }
                }
            }
            .sheet(isPresented: $showsSettings) {
                ConnectionSettingsView(settings: settings) {
                    Task { await viewModel.checkConnection(settings: settings) }
                }
            }
            .task {
                await viewModel.checkConnection(settings: settings)
                if settings.baseURL == nil {
                    showsSettings = true
                }
            }
            .alert("通信エラー", isPresented: Binding(
                get: { viewModel.errorMessage != nil },
                set: { if !$0 { viewModel.errorMessage = nil } }
            )) {
                Button("閉じる", role: .cancel) {}
            } message: {
                Text(viewModel.errorMessage ?? "不明なエラー")
            }
        }
    }

    private var connectionBar: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(viewModel.isConnected ? Color.green : Color.secondary)
                .frame(width: 8, height: 8)
            Text(viewModel.connectionLabel)
                .font(.caption)
            Spacer()
            Button("再確認") {
                Task { await viewModel.checkConnection(settings: settings) }
            }
            .font(.caption)
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
    }

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 12) {
                    if viewModel.messages.isEmpty {
                        ContentUnavailableView(
                            "PETITに話しかける",
                            systemImage: "message.fill",
                            description: Text("設定からTailscale Serve URLを入力してください。")
                        )
                        .padding(.top, 80)
                    }

                    ForEach(viewModel.messages) { message in
                        MessageBubble(message: message) { action, approved in
                            Task {
                                await viewModel.decide(
                                    action: action,
                                    approved: approved,
                                    settings: settings
                                )
                            }
                        }
                        .id(message.id)
                    }

                    if viewModel.isSending {
                        HStack {
                            ProgressView()
                            Text("PETITが考え中…")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Spacer()
                        }
                        .padding(.horizontal)
                    }
                }
                .padding()
            }
            .onChange(of: viewModel.messages.count) {
                guard let last = viewModel.messages.last else { return }
                withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
            }
        }
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 8) {
            TextField("メッセージ", text: $draft, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...5)
                .submitLabel(.send)
                .onSubmit { submit() }

            Button(action: submit) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 30))
            }
            .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isSending)
        }
        .padding()
    }

    private func submit() {
        let message = draft
        draft = ""
        Task { await viewModel.send(message, settings: settings) }
    }
}

private struct MessageBubble: View {
    let message: DisplayMessage
    let onDecision: (PendingAction, Bool) -> Void

    var body: some View {
        HStack {
            if message.role == .user { Spacer(minLength: 44) }

            VStack(alignment: .leading, spacing: 8) {
                Text(message.text)
                    .textSelection(.enabled)

                if !message.tools.isEmpty {
                    Text("使用ツール: " + message.tools.joined(separator: ", "))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }

                ForEach(message.pendingActions) { action in
                    VStack(alignment: .leading, spacing: 8) {
                        Text("実行確認: \(action.name)")
                            .font(.caption.bold())
                        if !action.arguments.isEmpty {
                            Text(action.arguments.keys.sorted().map { "\($0): \(action.arguments[$0]!)" }.joined(separator: "\n"))
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)
                        }
                        HStack {
                            Button("実行する") { onDecision(action, true) }
                                .buttonStyle(.borderedProminent)
                            Button("キャンセル", role: .cancel) { onDecision(action, false) }
                                .buttonStyle(.bordered)
                        }
                    }
                    .padding(10)
                    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
                }
            }
            .padding(12)
            .background(
                message.role == .user ? Color.accentColor : Color(uiColor: .secondarySystemBackground),
                in: RoundedRectangle(cornerRadius: 16)
            )
            .foregroundStyle(message.role == .user ? Color.white : Color.primary)

            if message.role == .assistant { Spacer(minLength: 44) }
        }
    }
}

private struct ConnectionSettingsView: View {
    @ObservedObject var settings: ConnectionSettingsStore
    let onSave: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("PETIT接続先") {
                    TextField("https://PC名.tailnet.ts.net", text: $settings.baseURLText)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                }

                Section {
                    Text("`tailscale serve status`に表示されるHTTPS URLを入力します。APIキーやNotionトークンは入力しません。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("接続設定")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") {
                        onSave()
                        dismiss()
                    }
                    .disabled(settings.baseURL == nil)
                }
            }
        }
    }
}
