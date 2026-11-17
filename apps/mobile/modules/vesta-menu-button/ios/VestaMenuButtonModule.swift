import ExpoModulesCore
import UIKit

private struct MenuButtonAction: Record {
  @Field var id: String = ""
  @Field var title: String = ""
  @Field var systemImage: String?
}

// The view is the touch target. The menu belongs to `anchor`, a button the
// caller places elsewhere (above a bar, for example): UIKit grows a menu out
// of its button, so the anchor's frame decides where the menu appears. A
// subview outside its parent's bounds receives no touch of its own.
private final class VestaMenuButtonView: ExpoView {
  let onAction = EventDispatcher()
  private let anchor = UIButton(type: .custom)
  private var anchorRect: CGRect?
  private var enabled = true

  var actions: [MenuButtonAction] = [] {
    didSet { anchor.menu = makeMenu() }
  }

  required init(appContext: AppContext? = nil) {
    super.init(appContext: appContext)
    backgroundColor = .clear
    clipsToBounds = false
    isAccessibilityElement = true
    accessibilityTraits = .button
    anchor.backgroundColor = .clear
    anchor.showsMenuAsPrimaryAction = true
    anchor.isAccessibilityElement = false
    addSubview(anchor)
    if #available(iOS 17.4, *) {
      // Zero duration: the menu opens on touch down, as a system button does.
      let press = UILongPressGestureRecognizer(
        target: self,
        action: #selector(handlePress(_:))
      )
      press.minimumPressDuration = 0
      addGestureRecognizer(press)
    }
  }

  override func layoutSubviews() {
    super.layoutSubviews()
    // Before iOS 17.4 a menu cannot be opened from code, so the anchor takes
    // the touch itself and the menu opens from the view.
    if #available(iOS 17.4, *), let anchorRect {
      anchor.frame = anchorRect
    } else {
      anchor.frame = bounds
    }
  }

  override func accessibilityActivate() -> Bool {
    openMenu()
    return true
  }

  func setAnchorRect(_ rect: [String: Double]) {
    anchorRect = CGRect(
      x: rect["x"] ?? 0,
      y: rect["y"] ?? 0,
      width: rect["width"] ?? 0,
      height: rect["height"] ?? 0
    )
    setNeedsLayout()
  }

  func setEnabled(_ value: Bool) {
    enabled = value
    anchor.isEnabled = value
  }

  @objc private func handlePress(_ recognizer: UILongPressGestureRecognizer) {
    if recognizer.state == .began {
      openMenu()
    }
  }

  private func openMenu() {
    guard enabled else {
      return
    }
    if #available(iOS 17.4, *) {
      anchor.performPrimaryAction()
    }
  }

  private func makeMenu() -> UIMenu {
    UIMenu(
      children: actions.map { action in
        UIAction(
          title: action.title,
          image: action.systemImage.flatMap { UIImage(systemName: $0) }
        ) { [weak self] _ in
          self?.onAction(["id": action.id])
        }
      }
    )
  }
}

public final class VestaMenuButtonModule: Module {
  public func definition() -> ModuleDefinition {
    Name("VestaMenuButton")

    View(VestaMenuButtonView.self) {
      Prop("actions") {
        (view: VestaMenuButtonView, actions: [MenuButtonAction]) in
        view.actions = actions
      }
      Prop("anchorRect") {
        (view: VestaMenuButtonView, rect: [String: Double]) in
        view.setAnchorRect(rect)
      }
      Prop("enabled") { (view: VestaMenuButtonView, enabled: Bool) in
        view.setEnabled(enabled)
      }
      Prop("label") { (view: VestaMenuButtonView, label: String?) in
        view.accessibilityLabel = label
      }
      Events("onAction")
    }
  }
}
