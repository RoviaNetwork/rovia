import Foundation
import XCTest
@testable import RoviaApplePlatform

final class ApplePlatformTests: XCTestCase {
    func testInMemorySecretStoreStoresAndDeletesValues() throws {
        let store = InMemorySecretStore()
        let secret = Data("synthetic-secret".utf8)

        try store.save(secret, for: "server/test")
        XCTAssertEqual(try store.read(for: "server/test"), secret)

        try store.delete(for: "server/test")
        XCTAssertNil(try store.read(for: "server/test"))
    }

    func testAppGroupStoreRejectsEmptyIdentifier() {
        let store = AppGroupStore(identifier: "")

        XCTAssertThrowsError(try store.containerURL()) { error in
            XCTAssertEqual(error as? AppGroupStoreError, .invalidIdentifier)
        }
    }
}
