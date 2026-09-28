import Foundation

public struct SubscriptionFetchPolicy: Equatable, Sendable {
    /// HTTPS is always allowed. HTTP needs an explicit opt-in per
    /// subscription — TLS verification is never disabled globally.
    public var allowInsecureHTTP: Bool
    public var timeout: TimeInterval
    public var maximumBytes: Int

    public init(
        allowInsecureHTTP: Bool = false,
        timeout: TimeInterval = 30,
        maximumBytes: Int = SubscriptionLimits.maximumBytes
    ) {
        self.allowInsecureHTTP = allowInsecureHTTP
        self.timeout = timeout
        self.maximumBytes = maximumBytes
    }
}

public enum SubscriptionFetchError: Error, Equatable, Sendable {
    case invalidURL
    case insecureSchemeBlocked
    case cancelled
    case timedOut
    case httpStatus(Int)
    case emptyBody
    case tooLarge
    case networkError
}

/// Minimal session surface the fetcher needs. `URLSession` conforms, tests
/// inject a stub — no `URLProtocol` subclassing, no real sockets in tests.
public protocol SubscriptionHTTPSession: Sendable {
    func data(for request: URLRequest) async throws -> (Data, URLResponse)
}

extension URLSession: SubscriptionHTTPSession {
    public func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        try await data(for: request, delegate: nil)
    }
}

/// Downloads a subscription URL. Returns raw bytes; decoding stays in
/// `SubscriptionDocumentDecoder`. Errors never carry the URL: tokens live in
/// query strings, and must not end up in logs or error surfaces.
public struct SubscriptionFetcher: Sendable {
    private let session: any SubscriptionHTTPSession
    public let policy: SubscriptionFetchPolicy

    public init(
        session: any SubscriptionHTTPSession = URLSession.shared,
        policy: SubscriptionFetchPolicy = SubscriptionFetchPolicy()
    ) {
        self.session = session
        self.policy = policy
    }

    public func fetch(_ url: URL) async throws -> Data {
        guard let scheme = url.scheme?.lowercased(), let host = url.host, !host.isEmpty else {
            throw SubscriptionFetchError.invalidURL
        }
        switch scheme {
        case "https":
            break
        case "http":
            guard policy.allowInsecureHTTP else {
                throw SubscriptionFetchError.insecureSchemeBlocked
            }
        default:
            throw SubscriptionFetchError.invalidURL
        }
        var request = URLRequest(
            url: url,
            cachePolicy: .reloadIgnoringLocalCacheData,
            timeoutInterval: policy.timeout
        )
        request.httpMethod = "GET"
        request.setValue("text/plain, */*;q=0.8", forHTTPHeaderField: "Accept")
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch is CancellationError {
            throw SubscriptionFetchError.cancelled
        } catch let error as URLError where error.code == .cancelled {
            throw SubscriptionFetchError.cancelled
        } catch let error as URLError where error.code == .timedOut {
            throw SubscriptionFetchError.timedOut
        } catch {
            throw SubscriptionFetchError.networkError
        }
        guard let http = response as? HTTPURLResponse else {
            throw SubscriptionFetchError.networkError
        }
        guard (200..<300).contains(http.statusCode) else {
            throw SubscriptionFetchError.httpStatus(http.statusCode)
        }
        guard !data.isEmpty else {
            throw SubscriptionFetchError.emptyBody
        }
        guard data.count <= policy.maximumBytes else {
            throw SubscriptionFetchError.tooLarge
        }
        return data
    }
}
