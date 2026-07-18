import Foundation

enum ChatRole: String, Codable, Sendable {
    case user
    case assistant
}

struct ChatHistoryItem: Codable, Equatable, Sendable {
    let role: ChatRole
    let content: String
}

struct ChatRequest: Encodable, Sendable {
    let message: String
    let history: [ChatHistoryItem]
    let requestId: String
    let sessionId: String
}

struct ChatResponse: Decodable, Sendable {
    let reply: String
    let usedTools: [UsedTool]
    let error: String?
    let requestId: String?
    let pendingActions: [PendingAction]
}

struct UsedTool: Decodable, Identifiable, Sendable {
    let name: String

    var id: String { name }
}

struct PendingAction: Decodable, Identifiable, Sendable {
    let approvalId: String
    let name: String
    let arguments: [String: JSONValue]

    var id: String { approvalId }
}

struct ActionDecision: Encodable, Sendable {
    let approved: Bool
}

struct HealthResponse: Decodable, Sendable {
    let status: String
    let chatModel: ModelHealth?
    let agentModel: ModelHealth?
}

struct ModelHealth: Decodable, Sendable {
    let serverOk: Bool?
    let model: String?
    let baseUrl: String?
}

enum JSONValue: Codable, Equatable, CustomStringConvertible, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported JSON value")
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    var description: String {
        switch self {
        case .string(let value): return value
        case .number(let value): return String(value)
        case .bool(let value): return value ? "true" : "false"
        case .object(let value):
            return value.keys.sorted().map { "\($0): \(value[$0]!)" }.joined(separator: ", ")
        case .array(let value): return value.map(\.description).joined(separator: ", ")
        case .null: return "null"
        }
    }
}
