import ExpoModulesCore
import LinkPresentation
import UIKit

private func primaryAppIconURL() -> URL? {
  let iconDictionaries = ["CFBundleIcons", "CFBundleIcons~ipad"]
  let scaleSuffixes = ["@3x", "@2x", "@1x", ""]

  for dictionaryName in iconDictionaries {
    guard
      let icons = Bundle.main.object(forInfoDictionaryKey: dictionaryName)
        as? [String: Any],
      let primaryIcon = icons["CFBundlePrimaryIcon"] as? [String: Any],
      let iconFiles = primaryIcon["CFBundleIconFiles"] as? [String]
    else {
      continue
    }

    for iconName in iconFiles.reversed() {
      for scaleSuffix in scaleSuffixes {
        guard let iconURL = Bundle.main.url(
          forResource: "\(iconName)\(scaleSuffix)",
          withExtension: "png"
        ) else {
          continue
        }

        return iconURL
      }
    }
  }

  return nil
}

private func appIconPreview(
  icon: UIImage,
  suggestedSize: CGSize
) -> UIImage {
  let suggestedSide = min(suggestedSize.width, suggestedSize.height)
  let side = suggestedSide.isFinite && suggestedSide > 0
    ? max(suggestedSide, 44)
    : 120
  let canvasSize = CGSize(width: side, height: side)
  let inset = max(2, side * 0.055)
  let iconRect = CGRect(origin: .zero, size: canvasSize).insetBy(
    dx: inset,
    dy: inset
  )
  let cornerRadius = iconRect.width * 0.2237
  let renderer = UIGraphicsImageRenderer(size: canvasSize)

  return renderer.image { context in
    let path = UIBezierPath(
      roundedRect: iconRect,
      cornerRadius: cornerRadius
    )

    context.cgContext.saveGState()
    context.cgContext.setShadow(
      offset: CGSize(width: 0, height: max(0.5, side * 0.012)),
      blur: max(1, side * 0.035),
      color: UIColor.black.withAlphaComponent(0.2).cgColor
    )
    UIColor.white.setFill()
    path.fill()
    context.cgContext.restoreGState()

    context.cgContext.saveGState()
    path.addClip()
    icon.draw(in: iconRect)
    context.cgContext.restoreGState()

    UIColor.separator.withAlphaComponent(0.18).setStroke()
    path.lineWidth = max(0.5, side / 240)
    path.stroke()
  }
}

private func messagePreview(_ message: String) -> String {
  let collapsed = message
    .split(whereSeparator: { $0.isWhitespace })
    .joined(separator: " ")
  let limit = 96

  guard collapsed.count > limit else {
    return collapsed
  }

  return "\(collapsed.prefix(limit - 1))…"
}

public final class VestaShareModule: Module {
  public func definition() -> ModuleDefinition {
    Name("VestaShare")

    AsyncFunction("shareMessageAsync") {
      (
        message: String,
        title: String,
        promise: Promise
      ) in
      guard let presentingController =
        self.appContext?.utilities?.currentViewController()
      else {
        promise.reject(
          "ERR_VESTA_SHARE_UNAVAILABLE",
          "Could not find a view controller to present the share sheet."
        )
        return
      }
      guard
        let iconURL = primaryAppIconURL(),
        let icon = UIImage(contentsOfFile: iconURL.path)
      else {
        promise.reject(
          "ERR_VESTA_SHARE_ICON_UNAVAILABLE",
          "Could not load the installed Vesta app icon."
        )
        return
      }

      let messageProvider = NSItemProvider(object: message as NSString)
      let configuration = UIActivityItemsConfiguration(
        itemProviders: [messageProvider]
      )
      let previewText = messagePreview(message)
      let metadataPreview = appIconPreview(
        icon: icon,
        suggestedSize: CGSize(width: 120, height: 120)
      )
      let linkMetadata = LPLinkMetadata()
      linkMetadata.title = title
      linkMetadata.imageProvider = NSItemProvider(object: metadataPreview)
      if !previewText.isEmpty {
        linkMetadata.originalURL = URL(fileURLWithPath: previewText)
      }
      configuration.metadataProvider = { key in
        switch key {
        case .title:
          return title
        case .messageBody:
          return message
        case .linkPresentationMetadata:
          return linkMetadata
        default:
          return nil
        }
      }
      configuration.previewProvider = { _, _, suggestedSize in
        let preview = appIconPreview(
          icon: icon,
          suggestedSize: suggestedSize
        )
        return NSItemProvider(object: preview)
      }
      let shareController = UIActivityViewController(
        activityItemsConfiguration: configuration
      )
      shareController.completionWithItemsHandler = {
        activityType,
        completed,
        _,
        error
      in
        if let error {
          promise.reject(error)
        } else {
          promise.resolve([
            "completed": completed,
            "activityType": activityType?.rawValue ?? NSNull()
          ] as [String: Any])
        }
      }

      if let popover = shareController.popoverPresentationController {
        popover.sourceView = presentingController.view
        popover.sourceRect = CGRect(
          x: presentingController.view.bounds.midX,
          y: presentingController.view.bounds.midY,
          width: 0,
          height: 0
        )
        popover.permittedArrowDirections = []
      }

      presentingController.present(shareController, animated: true)
    }
    .runOnQueue(.main)
  }
}
