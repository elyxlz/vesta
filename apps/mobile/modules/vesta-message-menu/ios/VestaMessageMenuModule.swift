import ExpoModulesCore
import UIKit

private enum MessageTailSide: String, Enumerable {
  case none
  case leading
  case trailing
}

private struct MessageMenuAction: Record {
  @Field var id: String = ""
  @Field var title: String = ""
  @Field var systemImage: String?
  @Field var destructive: Bool = false
  @Field var disabled: Bool = false
}

private struct PreviewGeometryKey: Equatable {
  let bounds: CGRect
  let tailSide: String
  let tailCornerRadius: CGFloat
  let cornerRadius: CGFloat
}

private final class VestaMessageMenuView: ExpoView,
  UIContextMenuInteractionDelegate
{
  let onAction = EventDispatcher()
  let onOpenChange = EventDispatcher()

  var actions: [MessageMenuAction] = [] {
    didSet {
      interaction.updateVisibleMenu { [weak self] _ in
        self?.makeMenu() ?? UIMenu()
      }
    }
  }
  var tailSide: MessageTailSide = .none
  var tailCornerRadius: CGFloat = 6
  var previewCornerRadius: CGFloat = 22
  var bubbleFillColor: UIColor = .clear
  var bubbleStrokeColor: UIColor = .clear
  var bubbleStrokeWidth: CGFloat = 0

  private lazy var interaction = UIContextMenuInteraction(delegate: self)
  private let bubbleLayer = CAShapeLayer()
  private weak var directChild: UIView?
  private var cachedGeometryKey: PreviewGeometryKey?
  private var cachedVisiblePath: UIBezierPath?

  required init(appContext: AppContext? = nil) {
    super.init(appContext: appContext)
    backgroundColor = .clear
    clipsToBounds = false
    isOpaque = false
    bubbleLayer.fillColor = UIColor.clear.cgColor
    bubbleLayer.strokeColor = UIColor.clear.cgColor
    bubbleLayer.lineJoin = .round
    bubbleLayer.lineCap = .round
    bubbleLayer.zPosition = -1
    layer.insertSublayer(bubbleLayer, at: 0)
    addInteraction(interaction)
  }

  override func layoutSubviews() {
    super.layoutSubviews()
    updateBubbleLayer()
  }

  override func traitCollectionDidChange(
    _ previousTraitCollection: UITraitCollection?
  ) {
    super.traitCollectionDidChange(previousTraitCollection)
    updateBubbleLayer()
  }

  override func mountChildComponentView(
    _ childComponentView: UIView,
    index: Int
  ) {
    guard directChild == nil else {
      return
    }
    directChild = childComponentView
    super.mountChildComponentView(childComponentView, index: index)
    layer.insertSublayer(bubbleLayer, below: childComponentView.layer)
  }

  override func unmountChildComponentView(_ child: UIView, index: Int) {
    guard directChild === child else {
      return
    }
    directChild = nil
    super.unmountChildComponentView(child, index: index)
  }

  func contextMenuInteraction(
    _ interaction: UIContextMenuInteraction,
    configurationForMenuAtLocation location: CGPoint
  ) -> UIContextMenuConfiguration? {
    UIContextMenuConfiguration(
      identifier: nil,
      previewProvider: nil,
      actionProvider: { [weak self] _ in
        self?.makeMenu()
      }
    )
  }

  func contextMenuInteraction(
    _ interaction: UIContextMenuInteraction,
    configuration: UIContextMenuConfiguration,
    highlightPreviewForItemWithIdentifier identifier: any NSCopying
  ) -> UITargetedPreview? {
    makeTargetedPreview()
  }

  func contextMenuInteraction(
    _ interaction: UIContextMenuInteraction,
    configuration: UIContextMenuConfiguration,
    dismissalPreviewForItemWithIdentifier identifier: any NSCopying
  ) -> UITargetedPreview? {
    makeTargetedPreview()
  }

  func contextMenuInteraction(
    _ interaction: UIContextMenuInteraction,
    previewForHighlightingMenuWithConfiguration configuration:
      UIContextMenuConfiguration
  ) -> UITargetedPreview? {
    makeTargetedPreview()
  }

  func contextMenuInteraction(
    _ interaction: UIContextMenuInteraction,
    previewForDismissingMenuWithConfiguration configuration:
      UIContextMenuConfiguration
  ) -> UITargetedPreview? {
    makeTargetedPreview()
  }

  func contextMenuInteraction(
    _ interaction: UIContextMenuInteraction,
    willDisplayMenuFor configuration: UIContextMenuConfiguration,
    animator: (any UIContextMenuInteractionAnimating)?
  ) {
    onOpenChange(["open": true])
  }

  // Reports the close once the dismissal settles, so a composer refocused on it lands after the
  // menu hands focus back to the app window.
  func contextMenuInteraction(
    _ interaction: UIContextMenuInteraction,
    willEndFor configuration: UIContextMenuConfiguration,
    animator: (any UIContextMenuInteractionAnimating)?
  ) {
    guard let animator else {
      onOpenChange(["open": false])
      return
    }
    animator.addCompletion { [weak self] in
      self?.onOpenChange(["open": false])
    }
  }

  private func makeMenu() -> UIMenu {
    let children = actions.map { action in
      var attributes: UIMenuElement.Attributes = []
      if action.destructive {
        attributes.insert(.destructive)
      }
      if action.disabled {
        attributes.insert(.disabled)
      }

      return UIAction(
        title: action.title,
        image: action.systemImage.flatMap(UIImage.init(systemName:)),
        attributes: attributes,
        handler: { [weak self] _ in
          self?.onAction(["id": action.id])
        }
      )
    }
    return UIMenu(title: "", children: children)
  }

  private func makeTargetedPreview() -> UITargetedPreview? {
    guard window != nil else {
      return nil
    }

    layoutIfNeeded()
    let parameters = UIPreviewParameters()
    parameters.backgroundColor = .clear
    parameters.visiblePath = makeVisiblePath()
    return UITargetedPreview(view: self, parameters: parameters)
  }

  private func updateBubbleLayer() {
    guard !bounds.isEmpty else {
      return
    }

    CATransaction.begin()
    CATransaction.setDisableActions(true)
    bubbleLayer.frame = bounds
    bubbleLayer.path = makeVisiblePath().cgPath
    bubbleLayer.fillColor = bubbleFillColor.resolvedColor(
      with: traitCollection
    ).cgColor
    bubbleLayer.strokeColor = bubbleStrokeColor.resolvedColor(
      with: traitCollection
    ).cgColor
    bubbleLayer.lineWidth = bubbleStrokeWidth
    CATransaction.commit()
  }

  private func makeVisiblePath() -> UIBezierPath {
    let geometryKey = PreviewGeometryKey(
      bounds: bounds,
      tailSide: tailSide.rawValue,
      tailCornerRadius: tailCornerRadius,
      cornerRadius: previewCornerRadius
    )
    if geometryKey == cachedGeometryKey, let cachedVisiblePath {
      return cachedVisiblePath
    }

    // CALayer keeps the configured radius when opposite corners overlap; it
    // does not replace it with half the current view height. Keeping this
    // constant is important when a one-line bubble grows to multiple lines.
    let radius = max(0, previewCornerRadius)
    let tailRadius = min(radius, max(0, tailCornerRadius))
    let visiblePath = makeContinuousRoundedRectPath(
      rect: bounds,
      radius: radius,
      bottomLeadingRadius: tailSide == .leading ? tailRadius : radius,
      bottomTrailingRadius: tailSide == .trailing ? tailRadius : radius
    )
    cachedGeometryKey = geometryKey
    cachedVisiblePath = visiblePath
    return visiblePath
  }

  // UIKit's continuous-corner control points. Unlike a circular rounded
  // rect, the curve eases into each edge over a longer distance. That is the
  // same corner style React Native renders for `borderCurve: "continuous"`.
  private func makeCornerCurve(radius: CGFloat) -> UIBezierPath {
    let edgeExtent = 1.52866483 * radius
    let cornerCurve = UIBezierPath()
    cornerCurve.move(to: CGPoint(x: edgeExtent, y: 0))
    cornerCurve.addCurve(
      to: CGPoint(x: 0.63149399 * radius, y: 0.07491139 * radius),
      controlPoint1: CGPoint(x: 1.08849323 * radius, y: 0),
      controlPoint2: CGPoint(x: 0.86840689 * radius, y: 0)
    )
    cornerCurve.addCurve(
      to: CGPoint(x: 0.07491139 * radius, y: 0.63149399 * radius),
      controlPoint1: CGPoint(
        x: 0.37282392 * radius,
        y: 0.16905899 * radius
      ),
      controlPoint2: CGPoint(
        x: 0.16905899 * radius,
        y: 0.37282392 * radius
      )
    )
    cornerCurve.addCurve(
      to: CGPoint(x: 0, y: edgeExtent),
      controlPoint1: CGPoint(x: 0, y: 0.86840689 * radius),
      controlPoint2: CGPoint(x: 0, y: 1.08849323 * radius)
    )
    return cornerCurve
  }

  // The last bubble of a group has one tighter bottom corner on the sender's
  // side, so each bottom corner takes its own radius.
  private func makeContinuousRoundedRectPath(
    rect: CGRect,
    radius: CGFloat,
    bottomLeadingRadius: CGFloat,
    bottomTrailingRadius: CGFloat
  ) -> UIBezierPath {
    guard radius > 0, !rect.isEmpty else {
      return UIBezierPath(rect: rect)
    }

    let corners: [(CGFloat, CGAffineTransform, [CGPoint])] = [
      (
        radius,
        CGAffineTransform(
          a: 1,
          b: 0,
          c: 0,
          d: 1,
          tx: rect.minX,
          ty: rect.minY
        ),
        [
          CGPoint(x: rect.minX, y: rect.maxY),
          CGPoint(x: rect.maxX, y: rect.maxY),
          CGPoint(x: rect.maxX, y: rect.minY),
        ]
      ),
      (
        radius,
        CGAffineTransform(
          a: -1,
          b: 0,
          c: 0,
          d: 1,
          tx: rect.maxX,
          ty: rect.minY
        ),
        [
          CGPoint(x: rect.maxX, y: rect.maxY),
          CGPoint(x: rect.minX, y: rect.maxY),
          CGPoint(x: rect.minX, y: rect.minY),
        ]
      ),
      (
        bottomLeadingRadius,
        CGAffineTransform(
          a: 1,
          b: 0,
          c: 0,
          d: -1,
          tx: rect.minX,
          ty: rect.maxY
        ),
        [
          CGPoint(x: rect.minX, y: rect.minY),
          CGPoint(x: rect.maxX, y: rect.minY),
          CGPoint(x: rect.maxX, y: rect.maxY),
        ]
      ),
      (
        bottomTrailingRadius,
        CGAffineTransform(
          a: -1,
          b: 0,
          c: 0,
          d: -1,
          tx: rect.maxX,
          ty: rect.maxY
        ),
        [
          CGPoint(x: rect.maxX, y: rect.minY),
          CGPoint(x: rect.minX, y: rect.minY),
          CGPoint(x: rect.minX, y: rect.maxY),
        ]
      ),
    ]

    // Each corner is a clipping constraint rather than an independent patch.
    // Intersecting them preserves the configured radius even when the upper
    // and lower continuous curves overlap on a compact bubble.
    return corners.reduce(UIBezierPath(rect: rect)) { bodyPath, corner in
      guard corner.0 > 0 else {
        return bodyPath
      }
      let constraint = makeCornerCurve(radius: corner.0)
      constraint.apply(corner.1)
      corner.2.forEach(constraint.addLine)
      constraint.close()
      return UIBezierPath(
        cgPath: bodyPath.cgPath.intersection(constraint.cgPath)
      )
    }
  }
}

public final class VestaMessageMenuModule: Module {
  public func definition() -> ModuleDefinition {
    Name("VestaMessageMenu")

    View(VestaMessageMenuView.self) {
      Prop("actions") {
        (view: VestaMessageMenuView, actions: [MessageMenuAction]) in
        view.actions = actions
      }
      Prop("tailSide") {
        (view: VestaMessageMenuView, side: MessageTailSide) in
        view.tailSide = side
        view.setNeedsLayout()
      }
      Prop("tailCornerRadius") {
        (view: VestaMessageMenuView, radius: Double) in
        view.tailCornerRadius = CGFloat(radius)
        view.setNeedsLayout()
      }
      Prop("previewCornerRadius") {
        (view: VestaMessageMenuView, radius: Double) in
        view.previewCornerRadius = CGFloat(radius)
        view.setNeedsLayout()
      }
      Prop("bubbleFillColor") {
        (view: VestaMessageMenuView, color: UIColor) in
        view.bubbleFillColor = color
        view.setNeedsLayout()
      }
      Prop("bubbleStrokeColor") {
        (view: VestaMessageMenuView, color: UIColor) in
        view.bubbleStrokeColor = color
        view.setNeedsLayout()
      }
      Prop("bubbleStrokeWidth") {
        (view: VestaMessageMenuView, width: Double) in
        view.bubbleStrokeWidth = CGFloat(width)
        view.setNeedsLayout()
      }
      Events("onAction", "onOpenChange")
    }
  }
}
