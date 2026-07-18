import XCTest
@testable import PETITMobile

final class PetitAPIClientTests: XCTestCase {
    func testNormalizesTailscaleURL() {
        let url = PetitAPIClient.normalizedBaseURL(from: " petit-pc.example.ts.net/ ")
        XCTAssertEqual(url?.absoluteString, "https://petit-pc.example.ts.net")
    }

    func testRejectsHTTPURL() {
        XCTAssertNil(
            PetitAPIClient.normalizedBaseURL(
                from: "http://petit-pc.example.ts.net"
            )
        )
    }

    func testRejectsEmptyURL() {
        XCTAssertNil(PetitAPIClient.normalizedBaseURL(from: "   "))
    }

    func testPingUsesShortTimeout() {
        XCTAssertEqual(PetitAPIClient.timeout(for: "/api/ping"), 5)
    }

    func testChatTimeoutIsBounded() {
        XCTAssertEqual(PetitAPIClient.timeout(for: "/api/chat"), 60)
    }

    func testNetworkFailureAffectsConnectivity() {
        XCTAssertTrue(PetitAPIError.networkUnavailable.affectsConnectivity)
    }

    func testAgentFailureDoesNotAffectConnectivity() {
        let error = PetitAPIError.apiFailure(
            code: "lm_studio",
            message: "model unavailable"
        )
        XCTAssertFalse(error.affectsConnectivity)
        XCTAssertFalse(PetitAPIError.timedOut.affectsConnectivity)
    }
}
