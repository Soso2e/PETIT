import Combine
import Foundation

struct DisplayMessage: Identifiable {
    let id = UUID()
    let role: ChatRole
    let text: String
    let tools: [String]
    let pendingActions: [PendingAction]
}

@MainActor
final class ChatViewModel: ObservableObject {
    @Published private(set) var messages: [DisplayMessage] = []
    @Published private(set) var isSending = false
    @Published private(set) var isConnected = false
    @Published private(set) var connectionLabel = "未接続"
    @Published var errorMessage: String?

    private var history: [ChatHistoryItem] = []

    func checkConnection(settings: ConnectionSettingsStore) async {
        guard let baseURL = settings.baseURL else {
            isConnected = false
            connectionLabel = "URL未設定"
            return
        }

        do {
            let health = try await PetitAPIClient(baseURL: baseURL).health()
            isConnected = health.status == "ok"
            connectionLabel = isConnected ? "PETIT接続OK" : "PETIT異常"
            errorMessage = nil
        } catch {
            isConnected = false
            connectionLabel = "接続失敗"
            errorMessage = error.localizedDescription
        }
    }

    func send(_ rawText: String, settings: ConnectionSettingsStore) async {
        let text = rawText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isSending else { return }
        guard let baseURL = settings.baseURL else {
            errorMessage = PetitAPIError.invalidBaseURL.localizedDescription
            return
        }

        let requestID = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        messages.append(DisplayMessage(role: .user, text: text, tools: [], pendingActions: []))
        isSending = true
        errorMessage = nil

        do {
            let response = try await PetitAPIClient(baseURL: baseURL).chat(
                message: text,
                history: history,
                sessionID: settings.sessionID,
                requestID: requestID
            )

            if let error = response.error, !error.isEmpty {
                throw PetitAPIError.httpStatus(200, error)
            }

            history.append(ChatHistoryItem(role: .user, content: text))
            if !response.reply.isEmpty {
                history.append(ChatHistoryItem(role: .assistant, content: response.reply))
                messages.append(
                    DisplayMessage(
                        role: .assistant,
                        text: response.reply,
                        tools: response.usedTools.map(\.name),
                        pendingActions: response.pendingActions
                    )
                )
            }
            isConnected = true
            connectionLabel = "PETIT接続OK"
        } catch {
            errorMessage = error.localizedDescription
            isConnected = false
            connectionLabel = "接続失敗"
        }

        isSending = false
    }

    func decide(
        action: PendingAction,
        approved: Bool,
        settings: ConnectionSettingsStore
    ) async {
        guard let baseURL = settings.baseURL else {
            errorMessage = PetitAPIError.invalidBaseURL.localizedDescription
            return
        }

        isSending = true
        do {
            let response = try await PetitAPIClient(baseURL: baseURL).decideAction(
                approvalID: action.approvalId,
                approved: approved
            )
            if let error = response.error, !error.isEmpty {
                throw PetitAPIError.httpStatus(200, error)
            }
            if !response.reply.isEmpty {
                history.append(ChatHistoryItem(role: .assistant, content: response.reply))
                messages.append(
                    DisplayMessage(
                        role: .assistant,
                        text: response.reply,
                        tools: response.usedTools.map(\.name),
                        pendingActions: response.pendingActions
                    )
                )
            }
        } catch {
            errorMessage = error.localizedDescription
        }
        isSending = false
    }
}
