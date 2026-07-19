import Combine
import Foundation

@MainActor
final class ConnectionSettingsStore: ObservableObject {
    private enum Keys {
        static let baseURL = "petit.baseURL"
        static let sessionID = "petit.sessionID"
    }

    @Published var baseURLText: String {
        didSet {
            UserDefaults.standard.set(baseURLText, forKey: Keys.baseURL)
        }
    }

    let sessionID: String

    init(defaults: UserDefaults = .standard) {
        baseURLText = defaults.string(forKey: Keys.baseURL) ?? ""

        if let saved = defaults.string(forKey: Keys.sessionID), !saved.isEmpty {
            sessionID = saved
        } else {
            let newID = UUID().uuidString
            defaults.set(newID, forKey: Keys.sessionID)
            sessionID = newID
        }
    }

    var baseURL: URL? {
        PetitAPIClient.normalizedBaseURL(from: baseURLText)
    }
}
