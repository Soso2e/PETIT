import SwiftUI

@main
struct PETITMobileApp: App {
    @StateObject private var settings = ConnectionSettingsStore()

    var body: some Scene {
        WindowGroup {
            ChatView(settings: settings)
        }
    }
}
