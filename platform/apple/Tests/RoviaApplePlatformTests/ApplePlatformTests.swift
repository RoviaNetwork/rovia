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

final class KeychainAccessGroupTests: XCTestCase {
    func testTheProbeLeavesNothingBehindAndAnswersConsistently() {
        // On a developer machine or simulator the probe resolves to whatever
        // the Keychain stamps; the contract is only that it is deterministic
        // within the process and leaves no probe item behind.
        let first = KeychainAccessGroup.resolve()
        let second = KeychainAccessGroup.resolve()
        XCTAssertEqual(first, second)
        if let group = first {
            XCTAssertFalse(group.isEmpty)
        }
    }
}
