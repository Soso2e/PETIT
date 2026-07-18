import Foundation

enum PetitAPIError: LocalizedError {
    case invalidBaseURL
    case insecureURL
    case invalidResponse
    case httpStatus(Int, String)
    case requestMismatch

    var errorDescription: String? {
        switch self {
        case .invalidBaseURL:
            return "Tailscale ServeのURLを入力してください。"
        case .insecureURL:
            return "HTTPSのTailscale Serve URLを使用してください。"
        case .invalidResponse:
            return "PETITから正しい応答を受け取れませんでした。"
        case .httpStatus(let status, let message):
            return "PETIT APIエラー（\(status)）: \(message)"
        case .requestMismatch:
            return "応答のrequest IDが一致しません。"
        }
    }
}

struct PetitAPIClient {
    let baseURL: URL
    var session: URLSession = .shared

    static func normalizedBaseURL(from rawValue: String) -> URL? {
        let trimmed = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        let candidate = trimmed.contains("://") ? trimmed : "https://\(trimmed)"
        guard var components = URLComponents(string: candidate),
              components.scheme?.lowercased() == "https",
              components.host != nil else {
            return nil
        }

        components.path = ""
        components.query = nil
        components.fragment = nil
        return components.url
    }

    func health() async throws -> HealthResponse {
        try await request(path: "/api/health", method: "GET", body: Optional<Data>.none)
    }

    func chat(
        message: String,
        history: [ChatHistoryItem],
        sessionID: String,
        requestID: String
    ) async throws -> ChatResponse {
        let payload = ChatRequest(
            message: message,
            history: history,
            requestId: requestID,
            sessionId: sessionID
        )
        let body = try encoder.encode(payload)
        let response: ChatResponse = try await request(path: "/api/chat", method: "POST", body: body)
        if let returnedID = response.requestId, returnedID != requestID {
            throw PetitAPIError.requestMismatch
        }
        return response
    }

    func decideAction(approvalID: String, approved: Bool) async throws -> ChatResponse {
        let body = try encoder.encode(ActionDecision(approved: approved))
        return try await request(
            path: "/api/actions/\(approvalID)",
            method: "POST",
            body: body
        )
    }

    private var encoder: JSONEncoder {
        let value = JSONEncoder()
        value.keyEncodingStrategy = .convertToSnakeCase
        return value
    }

    private var decoder: JSONDecoder {
        let value = JSONDecoder()
        value.keyDecodingStrategy = .convertFromSnakeCase
        return value
    }

    private func request<Response: Decodable>(
        path: String,
        method: String,
        body: Data?
    ) async throws -> Response {
        guard baseURL.scheme?.lowercased() == "https" else {
            throw PetitAPIError.insecureURL
        }

        let relativePath = path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let url = baseURL.appending(path: relativePath)
        var request = URLRequest(url: url, timeoutInterval: 130)
        request.httpMethod = method
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if body != nil {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw PetitAPIError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw PetitAPIError.httpStatus(http.statusCode, message)
        }

        return try decoder.decode(Response.self, from: data)
    }
}
