import XCTest
@testable import PETITMobile

final class PetitAPIClientTests: XCTestCase {
    func testNormalizesTailscaleURL() {
        let url = PetitAPIClient.normalizedBaseURL(from: " petit-pc.example.ts.net/ ")
        XCTAssertEqual(url?.absoluteString, "https://petit-pc.example.ts.net")
    }

    func testRejectsHTTPURL() {
        XCTAssertNil(PetitAPIClient.normalizedBaseURL(from: "http://petit-pc.example.ts.net"))
    }

    func testRejectsEmptyURL() {
        XCTAssertNil(PetitAPIClient.normalizedBaseURL(from: "   "))
    }
}
