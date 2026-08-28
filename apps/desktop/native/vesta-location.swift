import CoreLocation
import Foundation

// A one-shot CoreLocation fix for the main process, printed as culture-invariant "lat|lon|accuracy"
// on stdout (Swift's Double description is always dot-decimal). macOS geolocation in Electron's
// renderer hangs with no callback, so the app resolves a fix here instead, the same way it shells
// WinRT on Windows and GeoClue2 on Linux. Any failure exits non-zero with a reason on stderr; the
// caller falls back to timezone-only.

let TIMEOUT_SECONDS: TimeInterval = 15

func fail(_ reason: String) -> Never {
  FileHandle.standardError.write(Data("\(reason)\n".utf8))
  exit(1)
}

final class OneShotLocation: NSObject, CLLocationManagerDelegate {
  private let manager = CLLocationManager()

  func start() {
    manager.delegate = self
    manager.desiredAccuracy = kCLLocationAccuracyBest
    // Setting the delegate delivers the current authorization status on the next run-loop turn,
    // which is what drives the request below.
  }

  func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
    switch manager.authorizationStatus {
    case .notDetermined:
      manager.requestWhenInUseAuthorization()
    case .authorizedAlways, .authorizedWhenInUse:
      manager.requestLocation()
    case .denied, .restricted:
      fail("denied")
    @unknown default:
      fail("unknown-authorization")
    }
  }

  func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
    guard let location = locations.last else { return }
    let coord = location.coordinate
    print("\(coord.latitude)|\(coord.longitude)|\(location.horizontalAccuracy)")
    exit(0)
  }

  func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
    fail("error: \(error.localizedDescription)")
  }
}

let fetcher = OneShotLocation()
fetcher.start()
DispatchQueue.main.asyncAfter(deadline: .now() + TIMEOUT_SECONDS) {
  fail("timeout")
}
RunLoop.main.run()
