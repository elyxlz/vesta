import ExpoModulesCore
import UIKit

public final class VestaOpenLinkModule: Module {
  public func definition() -> ModuleDefinition {
    Name("VestaOpenLink")

    AsyncFunction("openInOwningAppAsync") { (url: String, promise: Promise) in
      guard let link = URL(string: url) else {
        promise.resolve(false)
        return
      }
      UIApplication.shared.open(
        link,
        options: [.universalLinksOnly: true]
      ) { opened in
        promise.resolve(opened)
      }
    }
    .runOnQueue(.main)
  }
}
